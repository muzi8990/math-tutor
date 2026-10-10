import json

import pytest
from fastapi.testclient import TestClient

from math_tutor import MathTutor, Settings, TutorError
from math_tutor.api import create_app
from math_tutor.logging import logger, configure_logging, remove_handlers
from test_tutor import backend  # noqa: F401


@pytest.fixture
def records():
    records = []
    handler = logger.add(lambda message: records.append(message.record), level='DEBUG', format='{message}', diagnose=False)
    yield records
    logger.remove(handler)


def test_api_error_logs_actual_reason_and_redacts_secret(backend, records):
    client, _, responses = backend
    responses[:] = [{'error': {'code': 400, 'status': 'INVALID_ARGUMENT', 'message': 'Invalid response_schema for key private-key; student: 我的私密题目'}}]
    tutor = MathTutor(client=client, settings=Settings(_env_file=None, api_key='private-key'))
    with pytest.raises(TutorError):
        tutor.chat('我的私密题目')
    error = next(r for r in records if r['extra'].get('event') == 'model.error')
    rendered = str(error['extra']) + error['message']
    assert 'response_schema' in rendered
    assert error['extra']['status_code'] == 400
    assert 'private-key' not in rendered
    assert '我的私密题目' not in rendered


def test_http_request_and_model_logs_share_id_without_query_or_input(backend, records, tmp_path):
    client, _, _ = backend
    with TestClient(create_app(Settings(_env_file=None, log_file=None), tutor_factory=lambda s: MathTutor(settings=s, client=client))) as http:
        response = http.post('/v1/analyze?key=private-query', json={'text': '私密学生输入'})
    request_id = response.headers['x-request-id']
    matching = [r for r in records if r['extra'].get('request_id') == request_id]
    assert any(r['extra'].get('event') == 'model.success' for r in matching)
    completed = next(r for r in matching if r['extra'].get('event') == 'http.complete')
    assert completed['extra']['status_code'] == 502
    assert completed['extra']['duration_ms'] >= 0
    assert 'private-query' not in str(matching)
    assert '私密学生输入' not in str(matching)


def test_file_logs_are_json_and_configuration_can_be_removed(tmp_path):
    path = tmp_path / 'nested/tutor.log'
    settings = Settings(_env_file=None, log_file=path)
    handlers = configure_logging(settings)
    try:
        logger.bind(event='test.event').info('test message')
    finally:
        remove_handlers(handlers)
    data = json.loads(path.read_text().strip())
    assert data['record']['extra']['event'] == 'test.event'


def test_upload_limit_is_logged_with_request_id(records):
    with TestClient(create_app(Settings(_env_file=None, log_file=None))) as http:
        response = http.post('/v1/analyze', content=b'x' * (14 * 1024 * 1024 + 1))
    assert response.status_code == 413
    assert any(r['extra'].get('status_code') == 413 and r['extra'].get('request_id') == response.headers['x-request-id'] for r in records)
