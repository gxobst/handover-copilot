"""Event domain schemas."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

SHIFT_KEY_REGEX = r"^\d{4}-\d{2}-\d{2}-(early|late|night)$"


class Category(StrEnum):
    """Event category enum."""

    DOWNTIME = "downtime"
    QUALITY = "quality"
    SAFETY = "safety"
    INFO = "info"


class EventCreate(BaseModel):
    """Schema for creating a new shift event."""

    shift_key: str = Field(
        ...,
        pattern=SHIFT_KEY_REGEX,
        description="Shift identifier in YYYY-MM-DD-(early|late|night) format",
    )
    machine: str = Field(..., min_length=1, description="Machine identifier")
    category: Category = Field(..., description="Event category")
    note: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Event note text (1-2000 characters)",
    )

    @field_validator("machine")
    @classmethod
    def validate_machine_not_whitespace(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Machine cannot be empty or whitespace-only")
        return v.strip()


class EventResponse(BaseModel):
    """Schema for returning a shift event."""

    id: UUID
    shift_key: str = Field(..., pattern=SHIFT_KEY_REGEX)
    machine: str
    category: Category
    note: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
