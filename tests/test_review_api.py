from datetime import datetime,timezone,timedelta
from test_mistake_attempts import ready,submit
from test_mistake_api import mistake_client
from test_analysis import analysis_data


def test_reviews_due_only_and_stats(ready):
    client,app,record=ready
    service=app.state.mistake_service
    now=datetime(2026,10,10,1,tzinfo=timezone.utc)
    service.clock=lambda:now
    assert client.get('/v1/mistakes/stats').status_code==200
    assert client.get('/v1/mistakes/stats').json()['independent_accuracy'] is None
    practice=client.post('/v1/mistakes/'+record['id']+'/practice-sessions').json()
    submit(client,record,practice_id=practice['id'])
    assert client.get('/v1/reviews/today').json()['items']==[]
    service.clock=lambda:now+timedelta(days=2)
    reviews=client.get('/v1/reviews/today').json()
    assert len(reviews['items'])==1
    assert 'analysis' not in reviews['items'][0]
    stats=client.get('/v1/mistakes/stats').json()
    assert stats['independent_accuracy']==1.0
    assert stats['due_review_count']==1
    assert stats['learning_counts']['reviewing']==1


def test_unknown_and_assisted_excluded_from_accuracy(ready):
    from math_tutor.mistakes.diagnosis import Judgment
    client,app,record=ready
    submit(client,record)  # no trusted practice: assisted
    class Unknown:
        def judge(self,*args): return Judgment(status='undetermined',evidence='看不清作答')
    app.state.mistake_service.judge=Unknown()
    practice=client.post('/v1/mistakes/'+record['id']+'/practice-sessions').json()
    submit(client,record,key='unknown',practice_id=practice['id'])
    stats=client.get('/v1/mistakes/stats').json()
    assert stats['independent_accuracy'] is None
    assert stats['determined_independent_attempts']==0
