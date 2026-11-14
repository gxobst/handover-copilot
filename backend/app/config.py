from functools import lru_cache
from pydantic import AliasChoices, Field
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
