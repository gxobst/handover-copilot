"""LLM client abstractions for Vertex AI and deterministic fake double."""

import json
from typing import Any, Protocol, runtime_checkable

from app.config import Settings, get_settings
from app.llm.exceptions import LLMError, ModelNotFound
from app.llm.prompt import SYSTEM_PROMPT
from app.schemas.reports import ActionPriority, OpenAction, ReportContent

# Models recognized by FakeLLMClient for offline simulation
KNOWN_MODELS = frozenset(
    {
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash",
        "gemini-4-argon",
    }
)


@runtime_checkable
class LLMClient(Protocol):
    """Protocol defining the interface for handover report LLM clients."""

    def generate_handover(
        self, prompt: str, model_name: str, timeout_s: float = 20.0
    ) -> ReportContent:
        """Generate structured ReportContent from a formatted prompt."""
        ...


class VertexLLMClient:
    """Production LLM client calling Google Cloud Vertex AI via google-genai SDK."""

    def __init__(
        self,
        project: str = "",
        location: str = "europe-west2",
        client: Any = None,
    ) -> None:
        self.project = project
        self.location = location
        if client is not None:
            self._client = client
        else:
            from google import genai

            self._client = genai.Client(
                vertexai=True,
                project=project or None,
                location=location or None,
            )

    def generate_handover(
        self, prompt: str, model_name: str, timeout_s: float = 20.0
    ) -> ReportContent:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=ReportContent,
            temperature=0.2,
            max_output_tokens=2048,
            thinking_config=types.ThinkingConfig(thinking_level="low"),
            http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
        )

        try:
            response = self._client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
        except errors.APIError as err:
            err_str = str(err).lower()
            if err.code == 404 or (err.code == 400 and "not found" in err_str) or "not found" in err_str:
                raise ModelNotFound(f"Model '{model_name}' not found: {err}") from err
            raise LLMError(f"Vertex AI API error ({err.code}): {err}") from err
        except Exception as err:
            err_str = str(err).lower()
            if "not found" in err_str or "404" in err_str:
                raise ModelNotFound(f"Model '{model_name}' not found: {err}") from err
            raise LLMError(f"Vertex AI request failed: {err}") from err

        try:
            if hasattr(response, "parsed") and isinstance(response.parsed, ReportContent):
                return response.parsed
            if hasattr(response, "parsed") and response.parsed is not None:
                return ReportContent.model_validate(response.parsed)
            if hasattr(response, "text") and response.text:
                return ReportContent.model_validate_json(response.text)
            raise LLMError("Vertex AI returned an empty response with no content")
        except LLMError:
            raise
        except Exception as err:
            raise LLMError(f"Failed to parse ReportContent from LLM response: {err}") from err


class FakeLLMClient:
    """Offline, deterministic LLM client for cost-free testing and failure simulation."""

    def generate_handover(
        self, prompt: str, model_name: str, timeout_s: float = 20.0
    ) -> ReportContent:
        if not model_name or model_name not in KNOWN_MODELS:
            raise ModelNotFound(
                f"Model '{model_name}' is not recognized, unavailable, or deprecated. "
                f"Known models: {sorted(KNOWN_MODELS)}"
            )

        events: list[dict[str, Any]] = []
        for line in prompt.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass

        safety_events = [e for e in events if str(e.get("category", "")).lower() == "safety"]
        downtime_events = [e for e in events if str(e.get("category", "")).lower() == "downtime"]
        quality_events = [e for e in events if str(e.get("category", "")).lower() == "quality"]
        info_events = [e for e in events if str(e.get("category", "")).lower() == "info"]

        # Summary: max 5 sentences, most severe first (safety > downtime > quality > info)
        sentences: list[str] = []
        if safety_events:
            sentences.append(f"{len(safety_events)} safety event(s) recorded during the shift.")
        if downtime_events:
            machines = sorted(set(str(e.get("machine", "")) for e in downtime_events if e.get("machine")))
            m_desc = f" on {', '.join(machines)}" if machines else ""
            sentences.append(f"{len(downtime_events)} downtime incident(s) occurred{m_desc}.")
        if quality_events:
            sentences.append(f"{len(quality_events)} quality check issue(s) reported.")
        if info_events:
            sentences.append(f"{len(info_events)} operational info update(s) logged.")
        if not sentences:
            sentences.append("Shift completed normally with no operational incidents recorded.")
        summary = " ".join(sentences[:5])

        # Open actions: concrete, unfinished actions with appropriate owner and priority
        open_actions: list[OpenAction] = []
        for e in safety_events:
            machine = e.get("machine", "equipment")
            note = e.get("note", "safety issue")
            open_actions.append(
                OpenAction(
                    action=f"Investigate safety incident on {machine}: {note}",
                    owner="Safety Officer",
                    priority=ActionPriority.HIGH,
                )
            )
        for e in downtime_events:
            machine = e.get("machine", "equipment")
            note = e.get("note", "downtime issue")
            priority = ActionPriority.HIGH if "stop" in note.lower() else ActionPriority.MEDIUM
            open_actions.append(
                OpenAction(
                    action=f"Complete repairs on {machine}: {note}",
                    owner="Maintenance",
                    priority=priority,
                )
            )
        for e in quality_events:
            machine = e.get("machine", "equipment")
            note = e.get("note", "quality check")
            open_actions.append(
                OpenAction(
                    action=f"Verify quality specifications on {machine}: {note}",
                    owner="Quality Lead",
                    priority=ActionPriority.MEDIUM,
                )
            )

        if not open_actions:
            open_actions.append(
                OpenAction(
                    action="Conduct standard handover walkthrough and review shift logs",
                    owner="Shift lead",
                    priority=ActionPriority.LOW,
                )
            )

        # Safety notes: AC-4 / plan.md §9 - every safety event MUST be represented
        safety_notes: list[str] = []
        for e in safety_events:
            machine = e.get("machine", "General")
            note = e.get("note", "Safety incident logged")
            safety_notes.append(f"[{machine}] {note}")

        return ReportContent(
            summary=summary,
            open_actions=open_actions,
            safety_notes=safety_notes,
        )


def get_llm_client(settings: Settings | None = None) -> LLMClient:
    """Factory returning configured LLMClient based on application settings."""
    if settings is None:
        settings = get_settings()

    backend = (settings.llm_backend or "").strip().lower()
    if backend == "fake":
        return FakeLLMClient()
    if backend == "vertex":
        return VertexLLMClient(
            project=settings.gcp_project,
            location=settings.gcp_location,
        )
    raise ValueError(
        f"Unsupported LLM backend: '{settings.llm_backend}'. Expected 'fake' or 'vertex'."
    )
