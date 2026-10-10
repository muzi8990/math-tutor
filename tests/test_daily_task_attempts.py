from uuid import uuid4
import pytest
from math_tutor.mistakes.diagnosis import Judgment, Diagnosis
from test_mistake_attempts import ready, submit
from test_mistake_api import mistake_client
from test_analysis import analysis_data


def start_daily(client, record):
    task=client.post('/v1/learning/daily-tasks').json()
    item=next(i for i in task['items'] if i['mistake_id']==record['id'])
    practice=client.post('/v1/mistakes/'+record['id']+'/practice-sessions',json={'daily_task_item_id':item['id']})
    assert practice.status_code==201,practice.text
    return task,item,practice.json()


@pytest.mark.parametrize('status',['correct','incorrect','undetermined'])
def test_actual_attempt_drives_task_completion(ready,status):
    client,app,record=ready
    class Judge:
        def judge(self,*args):
            return Judgment(status=status,evidence='实际作答',diagnoses=[] if status!='incorrect' else [Diagnosis(category='unknown',evidence='5',explanation='缺少过程')])
    app.state.mistake_service.judge=Judge()
    task,item,practice=start_daily(client,record)
    first=submit(client,record,practice_id=practice['id'])
    assert first.status_code==201,first.text
    assert submit(client,record,practice_id=practice['id']).json()['id']==first.json()['id']
    updated=client.get('/v1/learning/daily-tasks/'+task['id']).json()
    expected='needs_confirmation' if status=='undetermined' else 'completed'
    assert updated['items'][0]['status']==expected
    assert updated['items'][0]['attempt_id']==first.json()['id']
    assert updated['items'][0]['independent'] is True
    assert updated['completed_count']==(0 if status=='undetermined' else 1)


def test_uncertain_retry_and_hints(ready):
    client,app,record=ready
    class Judge:
        def judge(self,*args): return Judgment(status='undetermined',evidence='图片不清楚')
    old=app.state.mistake_service.judge; app.state.mistake_service.judge=Judge()
    task,item,p=start_daily(client,record)
    submit(client,record,practice_id=p['id'])
    app.state.mistake_service.judge=old
    url='/v1/mistakes/'+record['id']+'/practice-sessions'
    p=client.post(url,json={'daily_task_item_id':item['id']}).json()
    app.state.mistake_service.hint_provider=lambda *args:'先算总量'
    client.post(url+'/'+p['id']+'/hints')
    submit(client,record,key='again',practice_id=p['id'])
    updated=client.get('/v1/learning/daily-tasks/'+task['id']).json()
    assert updated['items'][0]['status']=='completed'
    assert updated['items'][0]['independent'] is False
    assert client.post(url,json={'daily_task_item_id':item['id']}).status_code==409


def test_free_practice_does_not_complete_daily_task(ready):
    client,app,record=ready
    task=client.post('/v1/learning/daily-tasks').json()
    practice=client.post('/v1/mistakes/'+record['id']+'/practice-sessions').json()
    submit(client,record,practice_id=practice['id'])
    assert client.get('/v1/learning/daily-tasks/'+task['id']).json()['items'][0]['status']=='pending'


def test_teacher_correction_updates_task_and_ability(ready):
    client,app,record=ready
    from math_tutor.mistakes.identity import get_student
    student=app.dependency_overrides[get_student]()
    task,item,p=start_daily(client,record)
    result=submit(client,record,practice_id=p['id']).json()
    app.state.mistake_service.correct_attempt(student,record['id'],result['id'],Judgment(status='undetermined',evidence='需核对题意'),reason='核对',actor_id='teacher')
    updated=client.get('/v1/learning/daily-tasks/'+task['id']).json()
    assert updated['items'][0]['status']=='needs_confirmation' and updated['completed_count']==0
