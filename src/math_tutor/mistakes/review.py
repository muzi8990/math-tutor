"""Pure, deterministic learning-state and spaced-review rules."""
from dataclasses import dataclass,replace
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ReviewState:
    stage: int = 0
    next_review_at: datetime | None = None
    last_review_at: datetime | None = None
    correct_dates: tuple[str,...] = ()
    due_passed: bool = False
    learning_status: str = 'new'


@dataclass(frozen=True)
class ReviewDecision:
    state: ReviewState
    learning_status: str


class ReviewPolicy:
    def __init__(self,intervals):
        self.intervals=intervals

    def apply(self,state,attempt,now,timezone_name):
        zone=ZoneInfo(timezone_name)
        local=now.astimezone(zone)
        day=local.date().isoformat()
        if attempt['status']=='undetermined':
            return ReviewDecision(state,state.learning_status)
        if attempt['status']=='incorrect' or not attempt['independent']:
            new=ReviewState(next_review_at=(local+timedelta(days=self.intervals[0])).astimezone(timezone.utc),last_review_at=now,learning_status='practicing')
            return ReviewDecision(new,'practicing')
        if day in state.correct_dates:
            return ReviewDecision(state,state.learning_status)
        dates=(*state.correct_dates,day)[-3:]
        due_passed=state.due_passed or (state.next_review_at is not None and now>=state.next_review_at)
        mastered=(len(dates)>=2 and due_passed) or state.learning_status=='mastered'
        learning='mastered' if mastered else 'reviewing'
        interval=self.intervals[-1] if mastered else self.intervals[min(state.stage,len(self.intervals)-1)]
        new=ReviewState(stage=min(state.stage+1,len(self.intervals)),next_review_at=(local+timedelta(days=interval)).astimezone(timezone.utc),last_review_at=now,correct_dates=dates,due_passed=due_passed,learning_status=learning)
        return ReviewDecision(new,learning)
