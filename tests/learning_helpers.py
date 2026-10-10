"""Real SQLite fixtures with complete analysis shape; no production test hooks."""
import json
from uuid import uuid4
from math_tutor.mistakes.models import timestamp


def seed_ready(db, student, *, grade=8, created='2026-10-01T00:00:00+00:00', core=None, point=None):
    mid,job,aid=map(str,[uuid4(),uuid4(),uuid4()])
    payload={'status':'solved','problem_text':'求 2+2','core_knowledge_points':[{'id':'K1','name':'运算','description':'运算规则'}],
        'detailed_knowledge_points':[{'id':'D1','name':'加法','description':'求和','parent_id':'K1'}],
        'steps':[{'index':1,'description':'求和','formula':'2+2=4','knowledge_point_ids':['D1'],'knowledge_application':'加法'}],
        'answer':'4','clarifications':[]}
    with db.connect() as conn:
        conn.execute("INSERT INTO mistakes(id,student_id,grade,analysis_status,created_at,updated_at) VALUES(?,?,?,'ready',?,?)",(mid,str(student.student_id),grade,created,created))
        conn.execute("INSERT INTO analysis_jobs(id,mistake_id,content_version,status,next_retry_at,created_at) VALUES(?,?,1,'done',?,?)",(job,mid,created,created))
        conn.execute('INSERT INTO analyses VALUES(?,?,?,1,?,?,?,?)',(aid,job,mid,json.dumps(payload),'fake','test',created))
        if point:
            conn.execute("INSERT INTO mistake_knowledge_points VALUES(?,?,?,'confirmed')",(aid,'D1',point))
        if core:
            conn.execute("INSERT INTO mistake_knowledge_points VALUES(?,?,?,'confirmed')",(aid,'K1',core))
    return mid,aid


def add_attempt(db, mid, aid, when, *, status='correct', independent=True, hint_count=0, diagnoses=None, version=1):
    ident=str(uuid4())
    with db.connect() as conn:
        conn.execute('''INSERT INTO attempts(id,mistake_id,content_version,text,status,hint_count,independent,evidence,diagnoses,created_at,idempotency_key,analysis_id)
            VALUES(?,?,?,'4',?,?,?,'student work',?,?,?,?)''',
            (ident,mid,version,status,hint_count,int(independent),json.dumps(diagnoses or []),timestamp(when),ident,aid))
    return ident
