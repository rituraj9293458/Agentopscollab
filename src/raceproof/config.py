from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RACEPROOF_",
        env_file=PROJECT_ROOT / ".env",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+psycopg://raceproof:raceproof_dev_only@localhost:55432/raceproof"
    )
    investigation_model: str = "gemini-3.5-flash-lite"
    repair_model: str = "gemini-3.1-flash-lite"
    fallback_model: str = "gemini-3.8-flash"
    enable_model_fallback: bool = False
    model_name: str | None = None
    model_max_retries: int = Field(default=2, ge=0, le=5)
    max_model_requests: int = Field(default=12, ge=1, le=100)
    max_investigation_requests: int = Field(default=5, ge=1, le=50)
    max_repair_requests: int = Field(default=7, ge=1, le=50)
    max_total_tokens: int = Field(default=60_000, ge=1_000, le=2_000_000)
    model_pricing_json: str | None = None
    model_pricing_verified: bool = False
    allow_nonlocal_database: bool = False
    gemini_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    )
    max_repair_attempts: int = Field(default=3, ge=1, le=5)
    max_investigation_attempts: int = Field(default=3, ge=1, le=5)
    schedule_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    benchmark_runs: int = Field(default=20, ge=3, le=200)
    performance_regression_limit: float = Field(default=2.5, ge=1.0, le=10.0)
    artifact_dir: Path = Path("artifacts")

    @property
    def resolved_investigation_model(self) -> str:
        return self.model_name or self.investigation_model

    @property
    def resolved_repair_model(self) -> str:
        return self.model_name or self.repair_model

    @property
    def gemini_api_key_value(self) -> str | None:
        return self.gemini_api_key.get_secret_value() if self.gemini_api_key else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
