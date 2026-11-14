"""Pydantic schemas for admin settings API."""

import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

# Model names must match a non-empty character pattern (allowing alphanumeric, dot, underscore, dash, slash)
MODEL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9._/-]+$")


def validate_model_name_value(v: object, field_name: str) -> str:
    """Validate model name with pattern-only check and whitespace stripping."""
    if v is None:
        raise ValueError(f"{field_name} cannot be null")
    if not isinstance(v, str):
        raise ValueError(f"{field_name} must be a string")
    stripped = v.strip()
    if not stripped:
        raise ValueError(f"{field_name} cannot be empty or whitespace-only")
    if len(stripped) > 128:
        raise ValueError(f"{field_name} must be at most 128 characters")
    if not MODEL_NAME_PATTERN.match(stripped):
        raise ValueError(
            f"{field_name} contains invalid characters; must match pattern '^[a-zA-Z0-9._-]+$'"
        )
    return stripped


class AdminSettingsResponse(BaseModel):
    """Response payload containing current active and fallback models."""

    model_config = ConfigDict(extra="forbid")

    active_model: str = Field(
        ...,
        description="Currently active model name used for report generation",
    )
    fallback_model: str = Field(
        ...,
        description="Fallback model name used if active model fails",
    )


class AdminSettingsUpdate(BaseModel):
    """Request payload for updating active and/or fallback models."""

    model_config = ConfigDict(extra="forbid")

    active_model: Optional[str] = Field(
        default=None,
        description="New active model name (must match ^[a-zA-Z0-9._-]+$)",
    )
    fallback_model: Optional[str] = Field(
        default=None,
        description="New fallback model name (must match ^[a-zA-Z0-9._-]+$)",
    )

    @field_validator("active_model", "fallback_model", mode="before")
    @classmethod
    def validate_model_field(cls, v: object, info: ValidationInfo) -> Optional[str]:
        if v is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return validate_model_name_value(v, info.field_name or "model")

    @model_validator(mode="after")
    def validate_at_least_one_field(self) -> "AdminSettingsUpdate":
        if self.active_model is None and self.fallback_model is None:
            raise ValueError("At least one of active_model or fallback_model must be provided")
        return self
