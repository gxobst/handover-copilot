from functools import lru_cache
from typing import Any
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application and environment settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    environment: str = Field(
        default="local",
        validation_alias=AliasChoices("APP_ENV", "app_env", "environment"),
        description="Application environment (e.g. local, dev, prod)",
    )
    version: str = Field(
        default="0.1.0",
        validation_alias=AliasChoices("APP_VERSION", "app_version", "version"),
        description="Application version",
    )
    database_url: str = Field(
        default="sqlite:///./handover.db",
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
        description="Database connection URL",
    )
    llm_backend: str = Field(
        default="fake",
        validation_alias=AliasChoices("LLM_BACKEND", "llm_backend"),
        description="LLM backend implementation ('fake' or 'vertex')",
    )
    gcp_project: str = Field(
        default="",
        validation_alias=AliasChoices("GCP_PROJECT", "gcp_project"),
        description="Google Cloud project ID for Vertex AI",
    )
    gcp_location: str = Field(
        default="europe-west2",
        validation_alias=AliasChoices("GCP_LOCATION", "gcp_location"),
        description="Google Cloud region/location for Vertex AI",
    )
    llm_timeout_s: float = Field(
        default=20.0,
        validation_alias=AliasChoices("LLM_TIMEOUT_S", "llm_timeout_s"),
        description="LLM request timeout in seconds",
    )
    active_model: str = Field(
        default="gemini-3.5-flash-lite",
        validation_alias=AliasChoices("ACTIVE_MODEL", "active_model"),
        description="Active Gemini model name for report generation",
    )
    fallback_model: str = Field(
        default="gemini-3.1-flash-lite",
        validation_alias=AliasChoices("FALLBACK_MODEL", "fallback_model"),
        description="Fallback Gemini model name for report generation",
    )
    admin_token: str = Field(
        default="dev-admin-secret-key-12345",
        validation_alias=AliasChoices("ADMIN_TOKEN", "admin_token"),
        description="Admin token for bearer authentication against admin API",
    )
    relay_webhook_token: str = Field(
        default="dev-relay-token-secret-123",
        validation_alias=AliasChoices("RELAY_WEBHOOK_TOKEN", "relay_webhook_token"),
        description="Shared secret for validating incoming relay webhooks",
    )
    github_dispatch_pat: str = Field(
        default="",
        validation_alias=AliasChoices("GITHUB_DISPATCH_PAT", "github_dispatch_pat"),
        description="GitHub personal access token for repository dispatch",
    )
    github_repository: str = Field(
        default="gxobst/handover-copilot",
        validation_alias=AliasChoices("GITHUB_REPOSITORY", "github_repository"),
        description="Target GitHub repository for repository dispatch (owner/repo)",
    )
    relay_dedupe_cooldown_seconds: int = Field(
        default=1800,
        validation_alias=AliasChoices(
            "RELAY_DEDUPE_COOLDOWN_SECONDS", "relay_dedupe_cooldown_seconds"
        ),
        description="Cooldown window in seconds for alert fingerprint deduplication",
    )

    @field_validator("relay_webhook_token", mode="before")
    @classmethod
    def _validate_relay_webhook_token(cls, v: Any) -> str:
        if v is None or (isinstance(v, str) and not v.strip()):
            return "dev-relay-token-secret-123"
        return str(v)
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "otel_exporter_otlp_endpoint",
        ),
        description="OTLP exporter endpoint URL",
    )
    otel_exporter_otlp_headers: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OTEL_EXPORTER_OTLP_HEADERS",
            "otel_exporter_otlp_headers",
        ),
        description="OTLP exporter headers (comma-separated key=value)",
    )

    @property
    def app_env(self) -> str:
        return self.environment

    @property
    def app_version(self) -> str:
        return self.version


@lru_cache
def get_settings() -> Settings:
    """Dependency provider returning cached Settings instance."""
    return Settings()
