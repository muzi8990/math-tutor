import json
from datetime import timedelta
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from math_tutor import MathTutor
from math_tutor.api import create_app
from math_tutor.settings import Settings
from math_tutor.mistakes.identity import get_student
from math_tutor.mistakes.models import StudentContext, utc_now
from math_tutor.mistakes.worker import AnalysisWorker
from math_tutor.learning.catalog import CatalogService
from test_tutor import backend
from test_analysis import analysis_data
from test_mistake_api import upload


@pytest.mark.parametrize('grade,stage',[(3,'小学3年级'),(8,'初中二年级'),(11,'高中二年级'),(None,'高中二年级')])
def test_k12_daily_review_flow(tmp_path,backend,analysis_data,grade,stage):
    sdk,requests,responses=backend
    analysis_data['answer']='4'
    responses[:]=[json.dumps(analysis_data,ensure_ascii=False)]
    settings=Settings(_env_file=None,database_path=tmp_path/'db',asset_dir=tmp_path/'assets',log_file=None,quality_model_review='off')
    factory=lambda config:MathTutor(settings=config,client=sdk)
    app=create_app(settings,tutor_factory=factory)
    student=StudentContext(uuid4());app.dependency_overrides[get_student]=lambda:student
    with TestClient(app) as client:
        client.put('/v1/learning/preferences',json={'grade':11})
        record=upload(client,**({'grade':str(grade)} if grade else {})).json()
        now=utc_now()+timedelta(seconds=1)
        service=app.state.mistake_service;service.clock=lambda:now
        app.state.learning_service.clock=lambda:now
        AnalysisWorker(service).run_once(now)
        assert stage in requests[0]['systemInstruction']['parts'][0]['text']
        detail=client.get('/v1/mistakes/'+record['id']).json()
        assert detail['analysis_status']=='ready' and detail['grade']==grade
        core,point=map(str,[uuid4(),uuid4()]); catalog=CatalogService(service.database)
        catalog.put_point(core,'运算',None,1,12);catalog.put_point(point,'平均分',core,1,12)
        catalog.map_point(student,record['id'],detail['analysis_id'],'K1.1',point)
        first=client.post('/v1/learning/daily-tasks').json()
        item=first['items'][0]
        p=client.post('/v1/mistakes/'+record['id']+'/practice-sessions',json={'daily_task_item_id':item['id']}).json()
        response=client.post('/v1/mistakes/'+record['id']+'/attempts',data={'text':'4','practice_id':p['id']},headers={'Idempotency-Key':'day1'})
        assert response.status_code==201,response.text
        assert client.get('/v1/learning/daily-tasks/today').json()['completed_count']==1
        now+=timedelta(days=1,seconds=1)
        second=client.post('/v1/learning/daily-tasks').json()
        assert second['id']!=first['id'] and second['items'][0]['reason']=='due_review'
        p=client.post('/v1/mistakes/'+record['id']+'/practice-sessions',json={'daily_task_item_id':second['items'][0]['id']}).json()
        client.post('/v1/mistakes/'+record['id']+'/attempts',data={'text':'4','practice_id':p['id']},headers={'Idempotency-Key':'day2'})
        abilities=client.get('/v1/learning/abilities').json()['items']
        assert abilities[0]['evidence_count']==2 and abilities[0]['state']=='insufficient_evidence'
        assert len(requests)==1  # Model transport proves query/planning/decimal comparison are local.
        app.dependency_overrides[get_student]=lambda:StudentContext(uuid4())
        assert client.get('/v1/learning/daily-tasks/'+first['id']).status_code==404
