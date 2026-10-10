from datetime import datetime,timezone,timedelta
from test_mistake_attempts import ready,submit
from test_mistake_api import mistake_client
from test_analysis import analysis_data


def test_attempt_transaction_updates_unique_schedule(ready):
    client,app,record=ready
    service=app.state.mistake_service
    now=datetime(2026,10,10,1,tzinfo=timezone.utc)
    service.clock=lambda:now
    practice_url='/v1/mistakes/'+record['id']+'/practice-sessions'
    practice=client.post(practice_url).json()
    assert submit(client,record,practice_id=practice['id']).status_code==201
    detail=client.get('/v1/mistakes/'+record['id']).json()
    assert detail['learning_status']=='reviewing'
    assert detail['review']['next_review_at']==(now+timedelta(days=1)).isoformat()
    service.clock=lambda:now+timedelta(days=1)
    second=client.post(practice_url).json()
    assert submit(client,record,key='two',practice_id=second['id']).status_code==201
    detail=client.get('/v1/mistakes/'+record['id']).json()
    assert detail['learning_status']=='mastered'
    with service.database.connect() as conn:
        assert conn.execute('SELECT count(*) FROM review_schedules').fetchone()[0]==1
