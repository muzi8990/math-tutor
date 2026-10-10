"""Immutable rule inputs and typed persisted outputs."""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field


class TaskItem(BaseModel):
    id: str
    mistake_id: str | None
    mistake_id_snapshot: str
    content_version: int
    reason: str
    due_at: datetime | None
    status: Literal['pending','completed','needs_confirmation','invalidated']
    attempt_id: str | None
    outcome: str | None
    independent: bool | None


class DailyTask(BaseModel):
    id: str
    local_date: date
    timezone: str
    source: str
    policy_version: str
    created_at: datetime
    items: list[TaskItem] = Field(default_factory=list)
    completed_count: int = 0
    available_count: int = 0
    message: str | None = None


@dataclass(frozen=True)
class AbilityEvidence:
    point_id: str
    mistake_id: str
    attempt_id: str
    analysis_id: str
    created_at: datetime
    local_date: date
    correct: bool
    provenance: str


class AbilitySummary(BaseModel):
    point_id: str
    evidence_count: int
    question_count: int
    date_count: int
    accuracy: float | None
    state: Literal['insufficient_evidence','needs_practice','basic','stable']
    recent_errors: list[str] = Field(default_factory=list)
    evidence: list[AbilityEvidence] = Field(default_factory=list)


@dataclass(frozen=True)
class ReviewCandidate:
    mistake_id: str
    content_version: int
    created_at: datetime
    due_at: datetime | None
    group_id: str
    reason: str
