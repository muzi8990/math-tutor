from datetime import timedelta
import os
from pathlib import Path
from threading import Event, Thread
from time import monotonic

from math_tutor.mistakes.models import utc_now
from math_tutor.mistakes.cli import finish_threads
from test_mistake_attempts import ready,submit
from test_mistake_api import mistake_client,png,upload
from test_analysis import analysis_data


def test_orphan_sweep_keeps_recent_and_referenced_images(mistake_client):
    client,app,student=mistake_client
    service=app.state.mistake_service
    upload(client)
    old=service.storage.put(student.student_id,png(),'image/png')
    recent=service.storage.put(student.student_id,png(),'image/png')
    path=service.storage.path(old.storage_key)
    old_time=(utc_now()-timedelta(days=2)).timestamp()
    os.utime(path,(old_time,old_time))
    temporary=path.with_suffix('.tmp')
    temporary.write_bytes(b'partial private image')
    os.utime(temporary,(old_time,old_time))
    with service.database.connect() as conn:
        referenced=conn.execute('SELECT storage_key FROM assets').fetchone()[0]
    ref_path=service.storage.path(referenced)
    os.utime(ref_path,(old_time,old_time))
    assert service.storage.sweep_orphans(service.database,utc_now())==2
    assert not path.exists() and not temporary.exists()
    assert service.storage.path(recent.storage_key).exists()
    assert ref_path.exists()


def test_shutdown_deadline_does_not_wait_for_stuck_call():
    stopped=Event()
    thread=Thread(target=lambda:stopped.wait(5),daemon=True)
    thread.start()
    begin=monotonic()
    assert finish_threads([thread],0.02)==1
    assert monotonic()-begin<0.5
    stopped.set()
    thread.join(1)


def test_human_correction_audits_and_rebuilds_review(ready):
    from math_tutor.mistakes.diagnosis import Judgment,Diagnosis
    client,app,record=ready
    service=app.state.mistake_service
    student=app.dependency_overrides[__import__('math_tutor.mistakes.identity',fromlist=['get_student']).get_student]()
    practice=client.post('/v1/mistakes/'+record['id']+'/practice-sessions').json()
    first=submit(client,record,practice_id=practice['id']).json()
    correction=Judgment(status='incorrect',evidence='人工确认学生答案错误',diagnoses=[Diagnosis(category='calculation',evidence='实际写了5',explanation='计算错误')])
    corrected=service.correct_attempt(student,record['id'],first['id'],correction,reason='老师复核原图',actor_id='teacher-001')
    assert corrected['status']=='incorrect'
    assert corrected['provenance']=='human_confirmed'
    assert client.get('/v1/mistakes/'+record['id']).json()['learning_status']=='practicing'
    assert client.get('/v1/mistakes/stats').json()['independent_accuracy']==0
    with service.database.connect() as conn:
        audit=conn.execute('SELECT * FROM attempt_corrections').fetchone()
        assert audit['reason']=='老师复核原图'
        assert 'correct' in audit['original_payload']


def test_startup_failure_removes_owned_log_handlers(tmp_path,monkeypatch):
    import pytest
    from fastapi.testclient import TestClient
    from math_tutor import api,Settings
    from math_tutor.mistakes.database import Database
    removed=[]
    monkeypatch.setattr(api,'configure_logging',lambda config:[42])
    monkeypatch.setattr(api,'remove_handlers',lambda handlers:removed.append(handlers))
    def fail(self): raise RuntimeError('database version error')
    monkeypatch.setattr(Database,'migrate',fail)
    with pytest.raises(RuntimeError):
        with TestClient(api.create_app(Settings(_env_file=None,database_path=tmp_path/'db',log_file=None))):
            pass
    assert removed==[[42]]


def test_worker_periodically_sweeps_old_orphans(mistake_client):
    from test_analysis_worker import worker
    client,app,student=mistake_client
    service=app.state.mistake_service
    orphan=service.storage.put(student.student_id,png(),'image/png')
    path=service.storage.path(orphan.storage_key)
    old=(utc_now()-timedelta(days=2)).timestamp()
    os.utime(path,(old,old))
    w=worker(app,None)
    w.run_once(utc_now()+timedelta(hours=2))
    assert not path.exists()
