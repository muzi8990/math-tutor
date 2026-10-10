from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest
from math_tutor.mistakes.database import Database
from math_tutor.mistakes.models import StudentContext
from math_tutor.learning.schemas import LearningPreferences
from math_tutor.learning.service import LearningService
from math_tutor.learning.scheduler import next_generation
from learning_helpers import seed_ready

NOW=datetime(2026,10,10,12,tzinfo=timezone.utc)


@pytest.mark.parametrize('now,time,want',[
    ('2026-03-08T05:00:00+00:00','02:30','2026-03-08T07:00:00+00:00'),
    ('2026-11-01T04:00:00+00:00','01:30','2026-11-01T05:30:00+00:00'),
])
def test_dst_missing_and_repeated_times(now,time,want):
    prefs=LearningPreferences(timezone='America/New_York',daily_enabled=True,generation_time=time)
    assert next_generation(datetime.fromisoformat(now),prefs,allow_today=True).isoformat()==want


def test_next_day_uses_local_calendar():
    prefs=LearningPreferences(timezone='America/New_York',daily_enabled=True,generation_time='19:00')
    assert next_generation(datetime(2026,3,7,23,tzinfo=timezone.utc),prefs,allow_today=False).isoformat()=='2026-03-08T23:00:00+00:00'
    assert next_generation(NOW,LearningPreferences(),allow_today=True) is None


def setup_scheduler(tmp_path):
    from math_tutor.learning.scheduler import LearningScheduler
    db=Database(tmp_path/'db');db.migrate(); student=StudentContext(uuid4())
    service=LearningService(db,clock=lambda:NOW)
    service.update_preferences(student,LearningPreferences(daily_enabled=True))
    seed_ready(db,student)
    return db,student,service,LearningScheduler(db,clock=lambda:NOW)


def test_daily_schedule_idempotent_and_manual_first(tmp_path):
    db,student,service,scheduler=setup_scheduler(tmp_path)
    first=service.generate_today(student)
    assert scheduler.run_once()=={'generated':0,'existing':1,'failed':0}
    assert service.today(student).id==first.id
    assert scheduler.run_once()=={'generated':0,'existing':0,'failed':0}
    with db.connect() as conn:
        assert conn.execute('SELECT next_run_at FROM learning_preferences').fetchone()[0]=='2026-10-11T11:00:00+00:00'


def test_concurrent_scanners_and_restart_do_not_create_history(tmp_path):
    db,student,service,scheduler=setup_scheduler(tmp_path)
    with db.connect() as conn:
        conn.execute("UPDATE learning_preferences SET next_run_at='2026-09-01T00:00:00+00:00'")
    with ThreadPoolExecutor(2) as pool: results=list(pool.map(lambda _:scheduler.run_once(),range(2)))
    assert sum(r['generated'] for r in results)==1
    with db.connect() as conn:
        assert conn.execute('SELECT local_date FROM daily_tasks').fetchone()[0]=='2026-10-10'
        assert conn.execute('SELECT count(*) FROM daily_tasks').fetchone()[0]==1


def test_restart_before_today_time_and_disable(tmp_path):
    db,student,service,scheduler=setup_scheduler(tmp_path)
    scheduler.clock=lambda:NOW-timedelta(hours=2)
    with db.connect() as conn: conn.execute("UPDATE learning_preferences SET next_run_at='2026-09-01T00:00:00+00:00'")
    assert scheduler.run_once()['generated']==0
    with db.connect() as conn: assert conn.execute('SELECT next_run_at FROM learning_preferences').fetchone()[0]=='2026-10-10T11:00:00+00:00'
    service.update_preferences(student,LearningPreferences(daily_enabled=False))
    scheduler.clock=lambda:NOW
    assert scheduler.run_once()['generated']==0


def test_one_student_failure_does_not_block_others(tmp_path):
    db,student,service,scheduler=setup_scheduler(tmp_path)
    bad=StudentContext(uuid4());service.update_preferences(bad,LearningPreferences(daily_enabled=True))
    with db.connect() as conn: conn.execute("UPDATE learning_preferences SET timezone='broken/zone' WHERE student_id=?",(str(bad.student_id),))
    assert scheduler.run_once()=={'generated':1,'existing':0,'failed':1}
    assert scheduler.run_once()['failed']==1
