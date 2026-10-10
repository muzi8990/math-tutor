from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value=None):
    return (value or utc_now()).astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class StudentContext:
    student_id: UUID
    timezone: str = 'Asia/Shanghai'
