from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class MistakePatch(StrictModel):
    text: str | None = Field(default=None, max_length=20_000)
    grade: int | None = Field(default=None, ge=1, le=12, strict=True)
    note: str | None = Field(default=None, max_length=2000)


AnalysisStatus = Literal['pending', 'processing', 'ready', 'needs_confirmation', 'failed']
LearningStatus = Literal['new', 'practicing', 'reviewing', 'mastered']


class PracticeRequest(StrictModel):
    daily_task_item_id: UUID | None = None
