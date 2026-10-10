from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest
from math_tutor.mistakes.database import Database
from math_tutor.mistakes.models import StudentContext
from learning_helpers import seed_ready, add_attempt

NOW=datetime(2026,10,10,12,tzinfo=timezone.utc)


def evidence(count, correct, *, days=2):
    from math_tutor.learning.models import AbilityEvidence
    return [AbilityEvidence('point',f'm{i%3}',f'a{i}','analysis',NOW-timedelta(days=count-i),
        (NOW-timedelta(days=i%days)).date(),result,'model_inferred') for i,result in enumerate(correct)]


@pytest.mark.parametrize('correct,state',[
    ([True,True],'insufficient_evidence'),
    ([True,False,True],'basic'),
    ([False,True,True,True,True],'stable'),
    ([True,True,True,True,False,False],'needs_practice'),
    ([False,False,True],'needs_practice'),
])
def test_assessment_requires_diverse_evidence(correct,state):
    from math_tutor.learning.ability import summarize
    summary=summarize(evidence(len(correct),correct))[0]
    assert summary.state==state
    assert summary.evidence_count==len(correct)


def test_stability_requires_multiple_dates():
    from math_tutor.learning.ability import summarize
    assert summarize(evidence(5,[True]*5,days=1))[0].state=='basic'


@pytest.fixture
def evidence_db(tmp_path):
    from math_tutor.learning.catalog import CatalogService
    db=Database(tmp_path/'db'); db.migrate(); student=StudentContext(uuid4())
    core,point=map(str,[uuid4(),uuid4()]); catalog=CatalogService(db)
    catalog.put_point(core,'运算',None,7,9); catalog.put_point(point,'加法',core,7,9)
    return db,student,core,point


def test_window_dedup_hints_unknown_and_student_scope(evidence_db):
    from math_tutor.learning.ability import collect_evidence
    db,student,core,point=evidence_db
    mid,aid=seed_ready(db,student,core=core,point=point)
    add_attempt(db,mid,aid,NOW-timedelta(days=30))
    add_attempt(db,mid,aid,NOW+timedelta(seconds=1))
    add_attempt(db,mid,aid,NOW-timedelta(hours=3))
    last=add_attempt(db,mid,aid,NOW-timedelta(hours=2),status='incorrect',diagnoses=[{'category':'calculation','evidence':'2+2=5','knowledge_point_ids':['D1']}])
    add_attempt(db,mid,aid,NOW-timedelta(hours=1),hint_count=1)
    add_attempt(db,mid,aid,NOW,status='undetermined')
    foreign,fid=seed_ready(db,StudentContext(uuid4()),point=point)
    add_attempt(db,foreign,fid,NOW)
    with db.connect() as conn: rows=collect_evidence(conn,student,NOW)
    assert len(rows)==1 and rows[0].attempt_id==last and rows[0].correct is False


@pytest.mark.parametrize('diagnoses',[
    [{'category':'unknown','evidence':'5','knowledge_point_ids':['D1']}],
    [{'category':'concept','evidence':'5','knowledge_point_ids':['K1']}],
    [{'category':'concept','evidence':'','knowledge_point_ids':['D1']}],
    [],
])
def test_wrong_answer_does_not_blame_all_points(evidence_db,diagnoses):
    from math_tutor.learning.ability import collect_evidence
    db,student,core,point=evidence_db
    mid,aid=seed_ready(db,student,core=core,point=point)
    add_attempt(db,mid,aid,NOW,status='incorrect',diagnoses=diagnoses)
    with db.connect() as conn: assert collect_evidence(conn,student,NOW)==[]


def test_mapping_is_bound_to_attempt_analysis_and_current_version(evidence_db):
    from math_tutor.learning.ability import collect_evidence
    db,student,core,point=evidence_db
    mid,aid=seed_ready(db,student,point=point)
    ident=add_attempt(db,mid,aid,NOW)
    with db.connect() as conn:
        # A later independent analysis mapping must not steal an earlier answer.
        conn.execute("UPDATE attempts SET analysis_id=NULL WHERE id=?",(ident,))
        assert collect_evidence(conn,student,NOW)==[]
        conn.execute('UPDATE attempts SET analysis_id=? WHERE id=?',(aid,ident))
        assert len(collect_evidence(conn,student,NOW))==1
        conn.execute('UPDATE mistakes SET content_version=2 WHERE id=?',(mid,))
        assert collect_evidence(conn,student,NOW)==[]


def test_local_window_boundary_is_calendar_based(evidence_db):
    from math_tutor.learning.ability import collect_evidence
    db,student,core,point=evidence_db
    mid,aid=seed_ready(db,student,point=point)
    included=add_attempt(db,mid,aid,datetime(2026,9,10,16,tzinfo=timezone.utc))
    add_attempt(db,mid,aid,datetime(2026,9,10,15,59,tzinfo=timezone.utc))
    with db.connect() as conn: assert [e.attempt_id for e in collect_evidence(conn,student,NOW)]==[included]
