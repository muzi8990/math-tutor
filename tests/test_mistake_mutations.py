from datetime import timedelta
from math_tutor import ProblemAnalysis
from math_tutor.mistakes.models import utc_now
from test_mistake_api import mistake_client, upload
from test_analysis import analysis_data
from test_analysis_worker import worker


def test_edit_invalidates_inflight_analysis(mistake_client, analysis_data):
    client,app,_=mistake_client
    record=upload(client).json()
    w=worker(app,None)
    now=utc_now()+timedelta(seconds=1)
    job=w.claim(now)
    result=client.patch('/v1/mistakes/'+record['id'],json={'text':'修改后的题干'})
    assert result.status_code==200
    assert result.json()['content_version']==2
    assert not w.finish(job,ProblemAnalysis.model_validate(analysis_data),now)
    assert w.claim(now)['content_version']==2


def test_note_grade_and_delete(mistake_client, analysis_data):
    client,app,_=mistake_client
    record=upload(client).json()
    worker(app,ProblemAnalysis.model_validate(analysis_data)).run_once(utc_now()+timedelta(seconds=1))
    detail=client.patch('/v1/mistakes/'+record['id'],json={'note':'复习','grade':3}).json()
    assert detail['content_version']==1
    assert detail['analysis_status']=='ready'
    assets=detail['assets']
    assert client.delete('/v1/mistakes/'+record['id']).status_code==204
    assert client.get('/v1/mistakes/'+record['id']).status_code==404
    assert client.get(assets[0]['url']).status_code==404
    w=worker(app,None)
    assert w.cleanup_once()
    assert not list(app.state.mistake_service.storage.root.rglob('*/*'))


def test_failed_file_delete_can_retry(mistake_client, monkeypatch):
    client,app,_=mistake_client
    record=upload(client).json()
    client.delete('/v1/mistakes/'+record['id'])
    w=worker(app,None)
    storage=app.state.mistake_service.storage
    original=storage.delete
    def fail(key): raise OSError('private path')
    monkeypatch.setattr(storage,'delete',fail)
    assert not w.cleanup_once()
    monkeypatch.setattr(storage,'delete',original)
    assert w.cleanup_once()
