"""Validated configuration: constructor > environment > dotenv > defaults."""

from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    )
    model: str = Field(default="gemini-2.5-flash", validation_alias="GEMINI_MODEL", min_length=1)
    grade: int | None = Field(default=None, ge=1, le=12, validation_alias="TUTOR_GRADE")
    max_turns: int = Field(default=30, ge=1, validation_alias="TUTOR_MAX_TURNS")
    timeout_ms: int = Field(default=60_000, ge=1, validation_alias="TUTOR_TIMEOUT_MS")
    temperature: float = Field(default=0.1, ge=0, le=2, validation_alias="TUTOR_TEMPERATURE")
    max_output_tokens: int = Field(default=4096, ge=1, validation_alias="TUTOR_MAX_OUTPUT_TOKENS")
    service_max_sessions: int = Field(default=100, ge=1, validation_alias="TUTOR_SERVICE_MAX_SESSIONS")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO", validation_alias="TUTOR_LOG_LEVEL")
    log_file: Path | None = Field(default=Path("logs/math-tutor.log"), validation_alias="TUTOR_LOG_FILE")
    database_path: Path = Field(default=Path("data/mistakes.sqlite3"), validation_alias="TUTOR_DATABASE_PATH")
    asset_dir: Path = Field(default=Path("data/assets"), validation_alias="TUTOR_ASSET_DIR")
    student_timezone: str = Field(default="Asia/Shanghai", validation_alias="TUTOR_STUDENT_TIMEZONE")
    review_intervals: list[Annotated[int, Field(strict=True)]] = Field(default_factory=lambda: [1, 3, 7], validation_alias="TUTOR_REVIEW_INTERVALS")
    local_student_id: UUID | None = Field(default=None, validation_alias="TUTOR_LOCAL_STUDENT_ID")
    enable_local_identity: bool = Field(default=False, validation_alias="TUTOR_ENABLE_LOCAL_IDENTITY")
    worker_concurrency: int = Field(default=1, ge=1, le=16, validation_alias="TUTOR_WORKER_CONCURRENCY")
    job_lease_seconds: int = Field(default=180, ge=30, validation_alias="TUTOR_JOB_LEASE_SECONDS")
    quality_model_review: Literal["off", "on_risk", "always"] = Field(default="on_risk", validation_alias="TUTOR_QUALITY_MODEL_REVIEW")
    quality_max_repairs: int = Field(default=1, ge=0, le=1, validation_alias="TUTOR_QUALITY_MAX_REPAIRS")

    @field_validator("student_timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("学生时区无效。") from exc
        return value

    @field_validator("review_intervals")
    @classmethod
    def valid_intervals(cls, value):
        if not value or any(isinstance(n, bool) or n <= 0 for n in value) or value != sorted(set(value)):
            raise ValueError("复习间隔必须为递增正整数。")
        return value

    @field_validator("model", mode="before")
    @classmethod
    def strip_model(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("api_key")
    @classmethod
    def nonempty_key(cls, value):
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("API Key 不能为空白。")
        return value

    @field_validator("grade", "max_turns", "timeout_ms", "max_output_tokens", "service_max_sessions", "quality_max_repairs", mode="before")
    @classmethod
    def reject_boolean_and_float(cls, value):
        if isinstance(value, (bool, float)):
            raise ValueError("必须为整数。")
        return value
