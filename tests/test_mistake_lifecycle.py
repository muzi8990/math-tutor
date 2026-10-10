from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from math_tutor import MathTutor, ProblemAnalysis, Settings
from math_tutor.api import create_app
from math_tutor.mistakes.database import Database
from math_tutor.mistakes.identity import get_student
from math_tutor.mistakes.models import StudentContext, utc_now, timestamp
from math_tutor.mistakes.worker import AnalysisWorker
from test_tutor import backend
from test_analysis import analysis_data
from test_mistake_api import mistake_client, upload, png
from test_mistake_attempts import ready


def test_real_sdk_lifecycle_survives_restart(tmp_path,backend,analysis_data):
    sdk,requests,responses=backend
    responses[:]=[json.dumps(analysis_data),json.dumps({'status':'correct','evidence':'24÷6=4，答案一致。','diagnoses':[]})]
    settings=Settings(_env_file=None,database_path=tmp_path/'db',asset_dir=tmp_path/'assets',log_file=None)
    student=StudentContext(uuid4())
    factory=lambda s:MathTutor(settings=s,client=sdk)
    app=create_app(settings,tutor_factory=factory)
    app.dependency_overrides[get_student]=lambda:student
    with TestClient(app) as http:
        record=upload(http).json()
    second=create_app(settings,tutor_factory=factory)
    second.dependency_overrides[get_student]=lambda:student
    with TestClient(second) as http:
        assert len(http.get('/v1/mistakes').json()['items'])==1
        assert AnalysisWorker(second.state.mistake_service).run_once()
        practice=http.post(f"/v1/mistakes/{record['id']}/practice-sessions").json()
        result=http.post(f"/v1/mistakes/{record['id']}/attempts",data={'text':'4块','practice_id':practice['id']},headers={'Idempotency-Key':'unique'})
        assert result.status_code==201,result.text
        assert result.json()['status']=='correct'
        service=second.state.mistake_service
        service.clock=lambda:utc_now()+timedelta(days=2)
        assert len(http.get('/v1/reviews/today').json()['items'])==1
        assert http.delete('/v1/mistakes/'+record['id']).status_code==204
        assert AnalysisWorker(service).cleanup_once()
    assert all('responseJsonSchema' in request['generationConfig'] for request in requests)


def test_concurrent_same_key_calls_model_once(ready):
    from math_tutor.mistakes.diagnosis import Judgment
    client,app,record=ready
    service=app.state.mistake_service
    started,release=Event(),Event()
    class BlockingJudge:
        calls=0
        def judge(self,*args):
            self.calls+=1
            started.set()
            assert release.wait(5)
            return Judgment(status='correct',evidence='一致')
    judge=BlockingJudge()
    service.judge=judge
    student=app.dependency_overrides[get_student]()
    args=(student,record['id'],'4',None,None,None,'concurrent')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(service.submit_attempt,*args)
        assert started.wait(5)
        second=pool.submit(service.submit_attempt,*args).result(5)
        assert second[1] is None
        release.set()
        assert first.result(5)[1] is True
    assert judge.calls==1
    assert len(service.get(student,record['id'])['attempts'])==1


def test_identity_explicit_loopback_only(tmp_path):
    settings=Settings(_env_file=None,database_path=tmp_path/'db',asset_dir=tmp_path/'assets',log_file=None,enable_local_identity=True,local_student_id=uuid4())
    with TestClient(create_app(settings),client=('127.0.0.1',1234)) as http:
        assert http.get('/v1/mistakes').status_code==200
    with TestClient(create_app(settings),client=('203.0.113.5',1234)) as http:
        assert http.get('/v1/mistakes').status_code==401


def test_upload_unknown_fields_rejected(mistake_client):
    client,_,_=mistake_client
    response=client.post('/v1/mistakes',files={'image':('x.png',png(),'image/png')},data={'student_id':str(uuid4())})
    assert response.status_code==422


def test_concurrent_migrations_are_safe(tmp_path):
    path=tmp_path/'db'
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(Database(path).migrate) for _ in range(4)]
        for future in futures: future.result()
    with Database(path).connect() as conn:
        assert conn.execute('SELECT count(*) FROM schema_migrations').fetchone()[0]==5


def test_catalog_mapping_and_filter(ready):
    client,app,record=ready
    repository=app.state.mistake_service.repository
    student=app.dependency_overrides[get_student]()
    point_id=uuid4()
    repository.put_knowledge_point(point_id,'除法的意义')
    detail=client.get('/v1/mistakes/'+record['id']).json()
    repository.map_knowledge_point(student,record['id'],detail['analysis_id'],'K1',point_id)
    assert len(client.get('/v1/mistakes',params={'knowledge_point_id':str(point_id)}).json()['items'])==1
    assert client.get('/v1/mistakes',params={'knowledge_point_id':str(uuid4())}).json()['items']==[]


def test_work_image_is_sent_through_real_sdk(mistake_client,backend,analysis_data):
    sdk,requests,responses=backend
    client,app,_=mistake_client
    record=upload(client).json()
    responses[:]=[json.dumps(analysis_data),json.dumps({'status':'undetermined','evidence':'学生作答图片无可辨认答案','diagnoses':[]})]
    app.state.mistake_service.tutor_factory=lambda settings:MathTutor(settings=settings,client=sdk)
    assert AnalysisWorker(app.state.mistake_service).run_once()
    result=client.post('/v1/mistakes/'+record['id']+'/attempts',files={'image':('作答.png',png(),'image/png')},headers={'Idempotency-Key':'image-one'})
    assert result.status_code==201,result.text
    assert result.json()['status']=='undetermined'
    assert 'inlineData' in requests[-1]['contents'][0]['parts'][-1]
    assert result.json()['asset_id']
    assert client.get('/v1/mistakes/'+record['id']).json()['learning_status']=='new'
