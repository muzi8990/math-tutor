from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from math_tutor.mistakes.models import StudentContext
from math_tutor.mistakes.database import Database
from learning_helpers import seed_ready

NOW=datetime(2026,10,10,12,tzinfo=timezone.utc)


def test_due_priority_and_coverage():
    from math_tutor.learning.models import ReviewCandidate
    from math_tutor.learning.planning import select_candidates
    candidates=[ReviewCandidate(str(i),1,NOW,NOW-timedelta(days=1),'one','due') for i in range(4)]
    candidates += [ReviewCandidate('5',1,NOW,NOW-timedelta(hours=1),'two','due'),ReviewCandidate('6',1,NOW,None,'three','new')]
    assert [i.mistake_id for i in select_candidates(candidates,3)]==['0','1','5']
    assert len(select_candidates(candidates,5))==5
    assert all(i.due_at is not None for i in select_candidates(candidates,5))


def test_database_filters_future_unready_and_unsolved(tmp_path):
    from math_tutor.learning.service import LearningService
    db=Database(tmp_path/'db');db.migrate(); student=StudentContext(uuid4())
    due,aid=seed_ready(db,student)
    future,_=seed_ready(db,student)
    new,_=seed_ready(db,student)
    unready,_=seed_ready(db,student)
    with db.connect() as conn:
        conn.execute('INSERT INTO review_schedules(mistake_id,next_review_at) VALUES(?,?)',(due,(NOW-timedelta(days=1)).isoformat()))
        conn.execute('INSERT INTO review_schedules(mistake_id,next_review_at) VALUES(?,?)',(future,(NOW+timedelta(days=1)).isoformat()))
        conn.execute("UPDATE mistakes SET analysis_status='pending' WHERE id=?",(unready,))
    task=LearningService(db,clock=lambda:NOW).generate_today(student)
    assert [i.mistake_id for i in task.items]==[due,new]


def test_concurrent_generation_and_no_refresh(tmp_path):
    from math_tutor.learning.service import LearningService
    db=Database(tmp_path/'db');db.migrate();student=StudentContext(uuid4())
    seed_ready(db,student)
    service=LearningService(db,clock=lambda:NOW)
    with ThreadPoolExecutor(2) as pool:
        tasks=list(pool.map(lambda _:service.generate_today(student),range(2)))
    assert tasks[0].id==tasks[1].id
    assert len(tasks[0].items)==1
    seed_ready(db,student)
    assert len(service.generate_today(student).items)==1
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM daily_tasks').fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM learning_preferences').fetchone()[0]==1
