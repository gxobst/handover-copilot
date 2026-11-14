"""Prompt construction for LLM handover report generation."""

from datetime import datetime
import json
from typing import Any, Sequence

SYSTEM_PROMPT = """You are a shift handover assistant for a manufacturing plant.
From the raw shift events, produce a handover for the incoming shift lead.
Rules:
- Use only facts present in the events. Never invent machines, numbers, or causes.
- summary: max 5 sentences, most severe first (safety > downtime > quality > info).
- open_actions: only unfinished, concrete actions. owner = the role named in the events,
  otherwise "Shift lead". priority reflects urgency.
- safety_notes: every safety-category event must be represented here.
- If information is missing, state that explicitly instead of guessing.
Return JSON matching the provided schema."""


def _extract_event_fields(event: Any) -> tuple[str, str, str, str]:
    """Extract (time, machine, category, note) from a dict, Pydantic model, or ORM object."""
    # Extract time / created_at
    time_val: Any = None
    if isinstance(event, dict):
        time_val = event.get("time") or event.get("created_at")
        machine = str(event.get("machine", ""))
        category = event.get("category", "")
        note = str(event.get("note", ""))
    else:
        time_val = getattr(event, "time", None) or getattr(event, "created_at", None)
        machine = str(getattr(event, "machine", ""))
        category = getattr(event, "category", "")
        note = str(getattr(event, "note", ""))

    if isinstance(time_val, datetime):
        time_str = time_val.isoformat()
    elif time_val is not None:
        time_str = str(time_val)
    else:
        time_str = ""

    # Normalize category string (handling enums)
    category_str = category.value if hasattr(category, "value") else str(category)

    return time_str, machine, category_str, note


def build_user_prompt(shift_key: str, events: Sequence[Any]) -> str:
    """Format the shift identifier followed by compact JSON lines for each event."""
    extracted = [_extract_event_fields(e) for e in events]

    # Sort events chronologically by timestamp
    extracted.sort(key=lambda item: item[0])

    lines: list[str] = [f"Shift: {shift_key}"]
    for time_str, machine, category, note in extracted:
        record = {
            "time": time_str,
            "machine": machine,
            "category": category,
            "note": note,
        }
        lines.append(json.dumps(record, separators=(",", ":")))

    return "\n".join(lines)
