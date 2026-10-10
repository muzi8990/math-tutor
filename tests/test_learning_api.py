from datetime import datetime, timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from math_tutor.api import create_app
from math_tutor.settings import Settings
from math_tutor.mistakes.identity import get_student
from math_tutor.mistakes.models import StudentContext
from test_mistake_api import mistake_client
from learning_helpers import seed_ready

NOW=datetime(2026,10,10,12,tzinfo=timezone.utc)


def test_learning_routes_are_scoped_and_do_not_invoke_models(mistake_client):
    client,app,student=mistake_client
    assert client.get('/v1/learning/preferences').json()['daily_limit']==5
    app.state.learning_service.clock=lambda:NOW
    assert client.get('/v1/learning/daily-tasks/today').status_code==404
    mid,_=seed_ready(app.state.mistake_service.database,student)
    result=client.post('/v1/learning/daily-tasks')
    assert result.status_code==201,result.text
    task=result.json()
    assert task['items'][0]['mistake_id']==mid
    assert 'student_id' not in task and 'answer' not in str(task)
    assert client.post('/v1/learning/daily-tasks').json()['id']==task['id']
    assert client.get('/v1/learning/daily-tasks/today').json()['id']==task['id']
    assert client.get('/v1/learning/daily-tasks/'+task['id']).status_code==200
    assert client.get('/v1/learning/abilities').json()['items']==[]
    assert client.put('/v1/learning/preferences',json={'grade':11,'daily_enabled':True}).status_code==200
    app.dependency_overrides[get_student]=lambda:StudentContext(uuid4())
    assert client.get('/v1/learning/daily-tasks/'+task['id']).status_code==404


def test_empty_task_and_preference_validation(mistake_client):
    client,app,student=mistake_client
    for body in [{'daily_limit':0},{'generation_time':'25:00'},{'timezone':'bad'},{'grade':13},{'unexpected':1}]:
        assert client.put('/v1/learning/preferences',json=body).status_code==422
    task=client.post('/v1/learning/daily-tasks').json()
    assert task['items']==[] and task['available_count']==0 and task['message']


def test_learning_auth_required(tmp_path):
    with TestClient(create_app(Settings(_env_file=None,database_path=tmp_path/'db',asset_dir=tmp_path/'assets',log_file=None))) as client:
        assert client.get('/v1/learning/preferences').status_code==401
        assert client.post('/v1/learning/daily-tasks').status_code==401


def test_preferences_timezone_snapshot_and_next_run(mistake_client):
    client,app,student=mistake_client
    app.state.learning_service.clock=lambda:NOW
    task=client.post('/v1/learning/daily-tasks').json()
    values={'timezone':'Europe/London','daily_enabled':True,'generation_time':'09:00','daily_limit':3,'grade':10}
    assert client.put('/v1/learning/preferences',json=values).status_code==200
    assert client.post('/v1/learning/daily-tasks').json()['timezone']=='Asia/Shanghai'
    with app.state.mistake_service.database.connect() as conn:
        assert conn.execute('SELECT next_run_at FROM learning_preferences').fetchone()[0]==NOW.isoformat()
    values['daily_enabled']=False
    client.put('/v1/learning/preferences',json=values)
    with app.state.mistake_service.database.connect() as conn:
        assert conn.execute('SELECT next_run_at FROM learning_preferences').fetchone()[0] is None


def test_first_preference_save_keeps_authenticated_timezone(mistake_client):
    client,app,student=mistake_client
    app.dependency_overrides[get_student]=lambda:StudentContext(student.student_id,'Europe/London')
    app.state.learning_service.clock=lambda:NOW
    assert client.get('/v1/learning/preferences').json()['timezone']=='Europe/London'
    saved=client.put('/v1/learning/preferences',json={'daily_enabled':True})
    assert saved.status_code==200
    assert saved.json()['timezone']=='Europe/London'
    with app.state.mistake_service.database.connect() as conn:
        assert conn.execute('SELECT next_run_at FROM learning_preferences').fetchone()[0]=='2026-10-10T18:00:00+00:00'
