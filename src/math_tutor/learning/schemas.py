"""Student-facing inputs; unknown fields are rejected."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import Field, field_validator
from ..education import Grade
from ..mistakes.schemas import StrictModel


class LearningPreferences(StrictModel):
    grade: Grade | None = None
    timezone: str = 'Asia/Shanghai'
    daily_enabled: bool = Field(default=False, strict=True)
    generation_time: str = Field(default='19:00', pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
    daily_limit: int = Field(default=5, ge=1, le=10, strict=True)

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError('学生时区无效。') from exc
        return value
