from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RACEPROOF_", env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://raceproof:raceproof_dev_only@localhost:55432/raceproof"
    )
    model_name: str = "gemini-3.8-flash"
    max_repair_attempts: int = Field(default=3, ge=1, le=5)
    max_investigation_attempts: int = Field(default=3, ge=1, le=5)
    schedule_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    benchmark_runs: int = Field(default=20, ge=3, le=200)
    performance_regression_limit: float = Field(default=2.5, ge=1.0, le=10.0)
    artifact_dir: Path = Path("artifacts")


@lru_cache
def get_settings() -> Settings:
    return Settings()
