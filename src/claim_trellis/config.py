from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration. Secrets are read from the environment only."""

    model_config = SettingsConfigDict(
        env_prefix="CLAIM_TRELLIS_",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    data_dir: Path = Path(".claim-trellis")
    database_path: Path | None = None
    database_url: str | None = Field(
        default=None, validation_alias=AliasChoices("DATABASE_URL", "CLAIM_TRELLIS_DATABASE_URL")
    )
    storage_backend: Literal["auto", "sqlite", "postgres"] = "auto"
    auth_mode: Literal["local", "supabase"] = "local"
    supabase_url: str | None = Field(default=None, validation_alias="SUPABASE_URL")
    supabase_publishable_key: str | None = Field(
        default=None, validation_alias="SUPABASE_PUBLISHABLE_KEY"
    )
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    max_source_chars: int = Field(default=2_000_000, ge=10_000)
    judgment_provider: str = "typesafe_jev"
    jev_model: str = "jev-1.13.0"
    jev_endpoint: str = "https://api.typesafe.ai/v1/systemone"
    jev_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    jev_max_retries: int = Field(default=3, ge=0, le=8)
    jev_api_key: str | None = Field(default=None, validation_alias="TYPESAFE_API_KEY")
    auto_accept_enabled: bool = False
    hosted_provider_enabled: bool = False
    relation_confidence_threshold: float = Field(default=0.90, ge=0, le=1)
    alignment_confidence_threshold: float = Field(default=0.85, ge=0, le=1)

    @property
    def resolved_database_path(self) -> Path:
        return self.database_path or self.data_dir / "audits.db"

    @property
    def selected_storage_backend(self) -> Literal["sqlite", "postgres"]:
        if self.storage_backend != "auto":
            return self.storage_backend
        return "postgres" if self.database_url else "sqlite"

    def validate_runtime(self) -> None:
        if self.selected_storage_backend == "postgres" and not self.database_url:
            raise ValueError("PostgreSQL storage requires DATABASE_URL.")
        if self.selected_storage_backend == "postgres" and self.auth_mode != "supabase":
            raise ValueError("PostgreSQL storage requires Supabase authentication.")
        if self.auth_mode == "supabase":
            if self.selected_storage_backend != "postgres":
                raise ValueError("Supabase authentication requires PostgreSQL storage.")
            if not self.supabase_url or not self.supabase_publishable_key:
                raise ValueError("Supabase authentication requires URL and publishable key.")
            if not self.supabase_url.startswith("https://"):
                raise ValueError("Supabase URL must use HTTPS.")

    def ensure_local_paths(self) -> None:
        if self.selected_storage_backend != "sqlite":
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.resolved_database_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
