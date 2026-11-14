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
