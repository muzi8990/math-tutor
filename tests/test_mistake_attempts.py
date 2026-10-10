from datetime import timedelta
from uuid import uuid4
import pytest
from math_tutor import ProblemAnalysis, TutorError
from math_tutor.mistakes.models import utc_now
from test_mistake_api import mistake_client, upload
from test_analysis import analysis_data
from test_analysis_worker import worker


@pytest.fixture
def ready(mistake_client,analysis_data):
    from math_tutor.mistakes.diagnosis import Judgment
    client,app,student=mistake_client
    record=upload(client).json()
    worker(app,ProblemAnalysis.model_validate(analysis_data)).run_once(utc_now()+timedelta(seconds=1))
    class FakeJudge:
        calls=0
        def judge(self,*args):
            self.calls+=1
            return Judgment(status='correct',evidence='答案匹配',diagnoses=[])
    app.state.mistake_service.judge=FakeJudge()
    return client,app,record


def submit(client,record,key='one',**data):
    return client.post('/v1/mistakes/'+record['id']+'/attempts',data={'text':'4',**data},headers={'Idempotency-Key':key})


def test_same_key_same_result_and_different_content_conflicts(ready):
    client,app,record=ready
    first=submit(client,record)
    assert first.status_code==201,first.text
    second=submit(client,record)
    assert second.json()['id']==first.json()['id']
    assert app.state.mistake_service.judge.calls==1
    assert submit(client,record,text='5').status_code==409
    assert first.json()['independent'] is False


def test_practice_hints_control_independence(ready):
    client,app,record=ready
    url='/v1/mistakes/'+record['id']+'/practice-sessions'
    practice=client.post(url).json()
    assert 'id' in practice
    first=submit(client,record,practice_id=practice['id'])
    assert first.json()['independent'] is True
    assert submit(client,record,key='two',practice_id=practice['id']).status_code==409
    second=client.post(url).json()
    app.state.mistake_service.hint_provider=lambda *args:'先找总数和份数。'
    assert client.post(url+'/'+second['id']+'/hints').status_code==200
    assert submit(client,record,key='three',practice_id=second['id']).json()['independent'] is False


def test_failed_model_same_key_retry_and_invalid_state(ready):
    client,app,record=ready
    original=app.state.mistake_service.judge
    class Failing:
        def judge(self,*args): raise TutorError('模型暂不可用')
    app.state.mistake_service.judge=Failing()
    assert submit(client,record).status_code==502
    assert client.get('/v1/mistakes/'+record['id']).json()['attempts']==[]
    app.state.mistake_service.judge=original
    assert submit(client,record).status_code==201
    pending=upload(client,allow_duplicate='true').json()
    assert submit(client,pending).status_code==409
    assert client.post('/v1/mistakes/'+record['id']+'/attempts',data={'text':'4'}).status_code==422
