from datetime import timedelta
import json
from math_tutor import MathTutor, TutorError
from math_tutor.mistakes.worker import AnalysisWorker
from math_tutor.mistakes.models import utc_now, timestamp
from test_mistake_api import mistake_client, upload
from test_analysis import analysis_data
import pytest


class FakeTutor:
    def __init__(self, answer): self.answer = answer
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def analyze_problem(self,*args,**kw):
        if isinstance(self.answer, Exception): raise self.answer
        return self.answer


def worker(app, answer):
    return AnalysisWorker(app.state.mistake_service, tutor_factory=lambda s: FakeTutor(answer))


def test_worker_saves_schema_snapshot_and_hides_solution(mistake_client, analysis_data):
    from math_tutor import ProblemAnalysis
    client,app,_ = mistake_client
    record = upload(client).json()
    w = worker(app,ProblemAnalysis.model_validate(analysis_data))
    assert w.run_once(utc_now()+timedelta(seconds=1))
    detail = client.get('/v1/mistakes/'+record['id']).json()
    assert detail['analysis_status'] == 'ready'
    assert 'answer' not in detail['analysis']
    assert detail['knowledge_mappings'][0]['mapping_status'] == 'unmapped'
    assert client.get('/v1/mistakes/'+record['id']+'?include_solution=true').json()['analysis']['answer'] == '每袋4块。'
    assert not w.run_once(utc_now()+timedelta(seconds=2))


def test_claim_single_owner_and_lease_recovery(mistake_client):
    client,app,_ = mistake_client
    upload(client)
    w = worker(app, None)
    now = utc_now()+timedelta(seconds=1)
    first = w.claim(now)
    assert first
    assert w.claim(now) is None
    second = w.claim(now+timedelta(seconds=181))
    assert second['lease_token'] != first['lease_token']
    assert not w.finish(first, None, now)


def test_retry_and_terminal_failure(mistake_client):
    client,app,_ = mistake_client
    record = upload(client).json()
    w = worker(app,TutorError('bad',status_code=429,error_code='provider'))
    now = utc_now()+timedelta(seconds=1)
    assert w.run_once(now)
    assert not w.run_once(now+timedelta(seconds=1))
    w.tutor_factory = lambda s: FakeTutor(TutorError('bad',status_code=400,error_code='provider'))
    assert w.run_once(now+timedelta(seconds=3))
    assert client.get('/v1/mistakes/'+record['id']).json()['analysis_status']=='failed'


def test_enqueue_reuses_active_job(mistake_client):
    client,_,_ = mistake_client
    record = upload(client).json()
    url='/v1/mistakes/'+record['id']+'/analyze'
    assert client.post(url).json()['id'] == client.post(url).json()['id']


def test_analysis_populates_list_title_and_clarification(mistake_client,analysis_data):
    from math_tutor import ProblemAnalysis
    client,app,_=mistake_client
    record=upload(client).json()
    worker(app,ProblemAnalysis.model_validate(analysis_data)).run_once(utc_now()+timedelta(seconds=1))
    assert client.get('/v1/mistakes').json()['items'][0]['problem_text']==analysis_data['problem_text']
    clarification=ProblemAnalysis(status='needs_clarification',problem_text='数字不清',core_knowledge_points=[],detailed_knowledge_points=[],steps=[],answer=None,clarifications=['请确认数字。'])
    other=upload(client,allow_duplicate='true').json()
    worker(app,clarification).run_once(utc_now()+timedelta(seconds=2))
    assert client.get('/v1/mistakes/'+other['id']).json()['analysis_status']=='needs_confirmation'


def test_retry_budget_exhausts_after_three_retries(mistake_client):
    client,app,_=mistake_client
    record=upload(client).json()
    w=worker(app,TutorError('网络错误',error_code='network'))
    now=utc_now()+timedelta(seconds=1)
    for delay in (0,2,12,42):
        assert w.run_once(now+timedelta(seconds=delay))
    assert client.get('/v1/mistakes/'+record['id']).json()['analysis_status']=='failed'
    assert not w.run_once(now+timedelta(seconds=100))
