"""Handover report generation service orchestrating events, LLMs, fallback, and persistence."""

import time
from typing import Any, Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.repo import (
    EventRepository,
    ReportRepository,
    get_event_repository,
    get_report_repository,
)
from app.db.session import get_db
from app.errors import GenerationFailedException
from app.llm.client import LLMClient, get_llm_client
from app.llm.prompt import build_user_prompt
from app.schemas.reports import ReportContent, ReportResponse
from app.settings_store import get_admin_settings
from app.telemetry import (
    get_logger,
    record_fallback_used,
    record_generation_duration,
    record_report_generated,
    trace_span,
)


class HandoverService:
    """Service orchestrating shift event retrieval, LLM handover report generation with fallback, and versioned persistence."""

    def __init__(
        self,
        event_repo: EventRepository,
        report_repo: ReportRepository,
        llm_client: Optional[LLMClient] = None,
        settings: Optional[Settings] = None,
        db: Optional[Session] = None,
    ) -> None:
        self.event_repo = event_repo
        self.report_repo = report_repo
        self.settings = settings or get_settings()
        self.llm_client = llm_client or get_llm_client(self.settings)
        self.db = db

    def _resolve_model_settings(self) -> tuple[str, str]:
        """Resolve active and fallback model names per-request via settings_store."""
        session = self.db or getattr(self.report_repo, "session", None)
        admin_settings = get_admin_settings(db=session, settings=self.settings)
        return admin_settings.active_model, admin_settings.fallback_model

    def _ensure_safety_notes_coverage(
        self,
        safety_notes: list[str],
        events: list[Any],
    ) -> list[str]:
        """Enforce AC-4: Ensure every safety-category event is represented in safety_notes."""
        notes = list(safety_notes)
        safety_events = [
            e
            for e in events
            if (
                e.category.value
                if hasattr(e.category, "value")
                else str(e.category)
            ).lower()
            == "safety"
        ]
        for se in safety_events:
            machine = getattr(se, "machine", "")
            note_text = getattr(se, "note", "")
            represented = any(
                (note_text.lower() in n.lower())
                or (machine.lower() in n.lower() and "safety" in n.lower())
                for n in notes
            )
            if not represented:
                notes.append(f"[{machine}] {note_text}")
        return notes

    def _normalize_report_content(self, content: ReportContent) -> ReportContent:
        """Normalize generated report content by cleaning markdown heading artifacts."""
        content.summary = content.summary.removeprefix("# ").strip()
        return content

    def generate_report(self, shift_key: str) -> ReportResponse:
        """Generate, validate, and persist a handover report for a shift."""
        start_time = time.perf_counter()
        logger = get_logger("handover")

        with trace_span("handover.load_events") as span:
            events = self.event_repo.list_by_shift(shift_key)
            span.set_attribute("event_count", len(events))

        if not events:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="No events found for shift",
            )

        active_model, fallback_model = self._resolve_model_settings()

        with trace_span("handover.build_prompt") as span:
            prompt = build_user_prompt(shift_key, events)

        content: Optional[ReportContent] = None
        model_used: str = active_model

        # Attempt primary model generation (AC-3)
        try:
            with trace_span(
                "gemini.generate",
                attributes={"model": active_model, "handover.is_fallback": False},
            ) as gen_span:
                content = self.llm_client.generate_handover(
                    prompt=prompt,
                    model_name=active_model,
                    timeout_s=self.settings.llm_timeout_s,
                )
                if not isinstance(content, ReportContent):
                    content = ReportContent.model_validate(content)
                content = self._normalize_report_content(content)
                tokens = getattr(content, "tokens", None) or getattr(content, "token_count", None)
                if tokens is not None:
                    gen_span.set_attribute("tokens", tokens)
            model_used = active_model
        except Exception as primary_exc:
            # Primary model failed; record fallback metric and attempt fallback once (AC-7)
            fallback_reason = f"primary_failed_{type(primary_exc).__name__}"
            record_fallback_used(reason=fallback_reason)
            logger.warning(
                "Primary model generation failed, falling back",
                primary_model=active_model,
                fallback_model=fallback_model,
                error_type=type(primary_exc).__name__,
                shift_key=shift_key,
            )
            try:
                with trace_span(
                    "gemini.generate",
                    attributes={"model": fallback_model, "handover.is_fallback": True},
                ) as fallback_span:
                    content = self.llm_client.generate_handover(
                        prompt=prompt,
                        model_name=fallback_model,
                        timeout_s=self.settings.llm_timeout_s,
                    )
                    if not isinstance(content, ReportContent):
                        content = ReportContent.model_validate(content)
                    content = self._normalize_report_content(content)
                    tokens = getattr(content, "tokens", None) or getattr(content, "token_count", None)
                    if tokens is not None:
                        fallback_span.set_attribute("tokens", tokens)
                model_used = fallback_model
            except Exception as fallback_exc:
                duration_s = time.perf_counter() - start_time
                duration_ms = int(duration_s * 1000)
                record_report_generated(outcome="error", model=fallback_model)
                record_generation_duration(duration_s, outcome="error")
                logger.error(
                    "Handover generation failed for both models",
                    outcome="error",
                    model=fallback_model,
                    shift_key=shift_key,
                    duration_ms=duration_ms,
                )
                # Atomic failure: double failure -> 502 with title "Generation Failed" and no partial report saved (AC-8)
                raise GenerationFailedException(
                    detail=(
                        f"Report generation failed for active model '{active_model}' "
                        f"and fallback model '{fallback_model}'. "
                        f"Primary error: {primary_exc}; Fallback error: {fallback_exc}"
                    )
                ) from fallback_exc

        # Enforce AC-4 safety notes coverage inside handover.validate span
        with trace_span("handover.validate") as val_span:
            safety_notes = self._ensure_safety_notes_coverage(content.safety_notes, events)
            val_span.set_attribute("safety_notes_count", len(safety_notes))

        # Versioning & persistence with unique constraint race handling (AC-5) inside db.save_report span
        with trace_span("db.save_report") as db_span:
            latest_version = self.report_repo.get_latest_version(shift_key)
            version = (latest_version or 0) + 1
            try:
                report = self.report_repo.create(
                    shift_key=shift_key,
                    version=version,
                    summary=content.summary,
                    open_actions=content.open_actions,
                    safety_notes=safety_notes,
                    model_used=model_used,
                    event_count=len(events),
                )
            except IntegrityError:
                # Re-read latest version and retry once on conflict
                latest_version = self.report_repo.get_latest_version(shift_key)
                version = (latest_version or 0) + 1
                report = self.report_repo.create(
                    shift_key=shift_key,
                    version=version,
                    summary=content.summary,
                    open_actions=content.open_actions,
                    safety_notes=safety_notes,
                    model_used=model_used,
                    event_count=len(events),
                )
            db_span.set_attribute("report_id", str(report.id))
            db_span.set_attribute("version", version)

        duration_s = time.perf_counter() - start_time
        duration_ms = int(duration_s * 1000)
        record_report_generated(outcome="success", model=model_used)
        record_generation_duration(duration_s, outcome="success")
        logger.info(
            "Handover report generated",
            outcome="success",
            model=model_used,
            shift_key=shift_key,
            report_id=str(report.id),
            duration_ms=duration_ms,
        )
        return report


def get_llm_client_dep(
    settings: Settings = Depends(get_settings),
) -> LLMClient:
    """Dependency provider returning configured LLMClient."""
    return get_llm_client(settings)


def get_handover_service(
    event_repo: EventRepository = Depends(get_event_repository),
    report_repo: ReportRepository = Depends(get_report_repository),
    llm_client: LLMClient = Depends(get_llm_client_dep),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> HandoverService:
    """Dependency provider returning HandoverService instance."""
    return HandoverService(
        event_repo=event_repo,
        report_repo=report_repo,
        llm_client=llm_client,
        settings=settings,
        db=db,
    )


def generate_report(
    shift_key: str,
    event_repo: EventRepository,
    report_repo: ReportRepository,
    llm_client: Optional[LLMClient] = None,
    settings: Optional[Settings] = None,
    db: Optional[Session] = None,
) -> ReportResponse:
    """Convenience helper to generate a report using HandoverService."""
    service = HandoverService(
        event_repo=event_repo,
        report_repo=report_repo,
        llm_client=llm_client,
        settings=settings,
        db=db,
    )
    return service.generate_report(shift_key)
