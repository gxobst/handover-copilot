"""Agent dispatcher module for invoking autonomous coding agents on alerts."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import subprocess
import sys
from typing import Any

from models import AlertContext

logger = logging.getLogger("on_call_engineer.dispatcher")

# EXACT VERBATIM SYSTEM PROMPT REQUIRED BY ISSUE #39
VERBATIM_SYSTEM_PROMPT = (
    "You are the on-call engineer for this repository. An alert just fired.\n\n"
    "Investigate the root cause. Read the code and reproduce the failure.\n"
    "If you find a real bug, make the smallest correction, run the backend tests,\n"
    "and commit the fix with a clear message.\n\n"
    "If the alert is a false positive, explain why and do not change the code."
)


@dataclass
class DispatchResult:
    """Outcome of an agent dispatch attempt."""

    success: bool
    command: str
    context: AlertContext
    return_code: int | None = None
    output: str = ""
    error: str = ""
    dry_run: bool = False
    prompt: str = ""


def build_full_agent_prompt(context: AlertContext) -> str:
    """Combine the verbatim system prompt with structured alert context."""
    return (
        f"{VERBATIM_SYSTEM_PROMPT}\n\n"
        f"---\n\n"
        f"## Incident Details\n\n"
        f"{context.to_markdown_summary()}\n\n"
        f"### Structured Alert JSON Payload\n"
        f"```json\n"
        f"{context.to_json(indent=2)}\n"
        f"```\n"
    )


class AgentDispatcher:
    """Dispatches a headless coding agent configured with system prompt and alert context."""

    def __init__(
        self,
        agent_cmd: str = "agy",
        dry_run: bool = False,
        timeout_seconds: int = 300,
    ) -> None:
        self.agent_cmd = agent_cmd
        self.dry_run = dry_run
        self.timeout_seconds = timeout_seconds

    def dispatch(self, context: AlertContext) -> DispatchResult:
        """Dispatch agent for the given alert context.

        In dry-run mode, logs the dispatch without launching any subprocess.
        In normal mode, invokes the configured agent CLI with verbatim system prompt and context.
        """
        full_prompt = build_full_agent_prompt(context)

        logger.info(
            "Preparing dispatch for alert '%s' [fingerprint=%s, severity=%s, env=%s]",
            context.alertname,
            context.fingerprint,
            context.severity,
            context.environment,
        )

        if self.dry_run:
            logger.info(
                "[DRY-RUN] Simulated dispatch for alert '%s' with command '%s'",
                context.alertname,
                self.agent_cmd,
            )
            logger.debug("[DRY-RUN] System prompt:\n%s", VERBATIM_SYSTEM_PROMPT)
            logger.debug("[DRY-RUN] Full prompt:\n%s", full_prompt)
            return DispatchResult(
                success=True,
                command=self.agent_cmd,
                context=context,
                return_code=0,
                output="[DRY-RUN] Agent dispatch simulated successfully.",
                dry_run=True,
                prompt=full_prompt,
            )

        # Build child environment with prompt and context
        child_env = os.environ.copy()
        child_env["ON_CALL_SYSTEM_PROMPT"] = VERBATIM_SYSTEM_PROMPT
        child_env["ON_CALL_ALERT_CONTEXT"] = context.to_json()
        child_env["ON_CALL_ALERT_NAME"] = context.alertname
        child_env["ON_CALL_ENVIRONMENT"] = context.environment
        child_env["ON_CALL_VERSION"] = context.version
        child_env["ON_CALL_SEVERITY"] = context.severity
        child_env["ON_CALL_DASHBOARD_URL"] = context.dashboard_url
        child_env["ON_CALL_RUNBOOK_URL"] = context.runbook_url
        child_env["ON_CALL_FIRING_TIMESTAMP"] = context.firing_timestamp
        child_env["ON_CALL_FINGERPRINT"] = context.fingerprint

        # Formulate effective command
        effective_cmd = self.agent_cmd
        if "{prompt}" in effective_cmd:
            effective_cmd = effective_cmd.replace("{prompt}", full_prompt)
        if "{system_prompt}" in effective_cmd:
            effective_cmd = effective_cmd.replace("{system_prompt}", VERBATIM_SYSTEM_PROMPT)
        if "{context}" in effective_cmd:
            effective_cmd = effective_cmd.replace("{context}", context.to_json())

        try:
            logger.info("Executing agent process: %s", self.agent_cmd)
            proc = subprocess.run(
                effective_cmd,
                input=full_prompt,
                text=True,
                shell=True,
                capture_output=True,
                env=child_env,
                timeout=self.timeout_seconds,
            )
            success = proc.returncode == 0
            if success:
                logger.info(
                    "Agent process completed successfully (exit 0) for alert '%s'",
                    context.alertname,
                )
            else:
                logger.warning(
                    "Agent process exited with code %d for alert '%s': %s",
                    proc.returncode,
                    context.alertname,
                    proc.stderr.strip()[:200],
                )

            return DispatchResult(
                success=success,
                command=effective_cmd,
                context=context,
                return_code=proc.returncode,
                output=proc.stdout,
                error=proc.stderr,
                dry_run=False,
                prompt=full_prompt,
            )
        except subprocess.TimeoutExpired as exc:
            logger.error("Agent process timed out after %d seconds for alert '%s'", self.timeout_seconds, context.alertname)
            return DispatchResult(
                success=False,
                command=effective_cmd,
                context=context,
                return_code=-1,
                output=exc.stdout or "" if isinstance(exc.stdout, str) else "",
                error=f"Timeout after {self.timeout_seconds}s",
                dry_run=False,
                prompt=full_prompt,
            )
        except Exception as exc:
            logger.error("Failed to execute agent process: %s", exc)
            return DispatchResult(
                success=False,
                command=effective_cmd,
                context=context,
                return_code=-1,
                output="",
                error=str(exc),
                dry_run=False,
                prompt=full_prompt,
            )
