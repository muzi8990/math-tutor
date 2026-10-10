from datetime import datetime,timezone,timedelta
from math_tutor.mistakes.review import ReviewPolicy,ReviewState

NOW=datetime(2026,10,9,1,tzinfo=timezone.utc)


def test_mastery_requires_different_dates_and_due_review():
    policy=ReviewPolicy([1,3,7])
    first=policy.apply(ReviewState(),{'status':'correct','independent':True},NOW,'Asia/Shanghai')
    assert first.learning_status=='reviewing'
    assert first.state.next_review_at==NOW+timedelta(days=1)
    same=policy.apply(first.state,{'status':'correct','independent':True},NOW+timedelta(hours=1),'Asia/Shanghai')
    assert same.state==first.state
    early=policy.apply(first.state,{'status':'correct','independent':True},NOW+timedelta(hours=16),'Asia/Shanghai')
    assert early.learning_status=='reviewing'  # new local date but not yet due
    due=policy.apply(first.state,{'status':'correct','independent':True},NOW+timedelta(days=1),'Asia/Shanghai')
    assert due.learning_status=='mastered'
    assert due.state.next_review_at==NOW+timedelta(days=8)
    wrong=policy.apply(due.state,{'status':'incorrect','independent':True},NOW+timedelta(days=2),'Asia/Shanghai')
    assert wrong.learning_status=='practicing'
    assert wrong.state.correct_dates==()
    assert wrong.state.next_review_at==NOW+timedelta(days=3)


def test_assisted_and_undetermined():
    policy=ReviewPolicy([1,3,7])
    state=ReviewState(learning_status='reviewing',correct_dates=('2026-10-08',),next_review_at=NOW)
    unknown=policy.apply(state,{'status':'undetermined','independent':True},NOW,'Asia/Shanghai')
    assert unknown.state==state
    assisted=policy.apply(state,{'status':'correct','independent':False},NOW,'Asia/Shanghai')
    assert assisted.learning_status=='practicing'
    assert assisted.state.correct_dates==()
    assert assisted.state.stage==0


def test_timezone_boundary_and_invalid_hint_independence():
    policy=ReviewPolicy([1,3,7])
    first=policy.apply(ReviewState(),{'status':'correct','independent':True},datetime(2026,10,8,16,30,tzinfo=timezone.utc),'Asia/Shanghai')
    assert first.state.correct_dates==('2026-10-09',)
