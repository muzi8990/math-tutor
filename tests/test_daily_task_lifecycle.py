from uuid import uuid4
from test_daily_task_attempts import start_daily
from test_mistake_attempts import ready, submit
from test_mistake_api import mistake_client
from test_analysis import analysis_data
from learning_helpers import seed_ready


def test_wrong_item_owner_mistake_and_invalidated_version(ready):
    client,app,record=ready
    from math_tutor.mistakes.models import StudentContext
    student=next(iter(app.dependency_overrides.values()))()
    task,item,p=start_daily(client,record)
    other,_=seed_ready(app.state.mistake_service.database,student)
    url='/v1/mistakes/'+other+'/practice-sessions'
    assert client.post(url,json={'daily_task_item_id':item['id']}).status_code==409
    foreign,_=seed_ready(app.state.mistake_service.database,StudentContext(uuid4()))
    with app.state.mistake_service.database.connect() as conn:
        conn.execute('UPDATE daily_tasks SET student_id=? WHERE id=?',(str(uuid4()),task['id']))
    assert client.post('/v1/mistakes/'+record['id']+'/practice-sessions',json={'daily_task_item_id':item['id']}).status_code==404


def test_edit_and_delete_invalidate_without_refill(ready):
    client,app,record=ready
    task,item,p=start_daily(client,record)
    assert client.patch('/v1/mistakes/'+record['id'],json={'text':'更正题干'}).status_code==200
    updated=client.get('/v1/learning/daily-tasks/'+task['id']).json()
    assert updated['items'][0]['status']=='invalidated' and updated['available_count']==0
    assert submit(client,record,practice_id=p['id']).status_code==409
    assert client.delete('/v1/mistakes/'+record['id']).status_code==204
    updated=client.get('/v1/learning/daily-tasks/'+task['id']).json()
    assert updated['items'][0]['mistake_id'] is None
    assert updated['items'][0]['mistake_id_snapshot']==record['id']


def test_reanalysis_invalidates_completed_item(ready):
    client,app,record=ready
    task,item,p=start_daily(client,record)
    submit(client,record,practice_id=p['id'])
    client.post('/v1/mistakes/'+record['id']+'/analyze')
    updated=client.get('/v1/learning/daily-tasks/'+task['id']).json()
    assert updated['items'][0]['status']=='invalidated'
    assert updated['completed_count']==0


def test_existing_sessions_do_not_double_count_completion(ready):
    client,app,record=ready
    task,item,p=start_daily(client,record)
    second=client.post('/v1/mistakes/'+record['id']+'/practice-sessions',json={'daily_task_item_id':item['id']}).json()
    first=submit(client,record,practice_id=p['id']).json()
    latest=submit(client,record,key='second',practice_id=second['id']).json()
    updated=client.get('/v1/learning/daily-tasks/'+task['id']).json()
    assert updated['completed_count']==1
    assert updated['items'][0]['attempt_id']==latest['id']
