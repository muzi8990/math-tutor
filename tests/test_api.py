import json

import pytest
from fastapi.testclient import TestClient

from math_tutor import MathTutor, Settings
from math_tutor.api import create_app
from test_tutor import backend, picture  # noqa: F401
from test_analysis import analysis_data  # noqa: F401


@pytest.fixture
def service(backend):
    client, requests, responses = backend
    settings = Settings(_env_file=None)
    with TestClient(create_app(settings, tutor_factory=lambda s: MathTutor(settings=s, client=client))) as http:
        yield http, requests, responses


def test_text_analysis_and_schema(service, analysis_data):
    http, requests, responses = service
    responses[:] = [json.dumps(analysis_data)]
    result = http.post('/v1/analyze', json={'text': '24块分6份', 'grade': 3})
    assert result.status_code == 200
    assert result.json()['steps'][0]['knowledge_point_ids'] == ['K1', 'K1.1']
    assert '/v1/analyze/image' in http.get('/openapi.json').json()['paths']
    assert http.get('/health').json() == {'status': 'ok'}


def test_uploaded_image_analysis(service, picture, analysis_data):
    http, requests, responses = service
    responses[:] = [json.dumps(analysis_data)]
    result = http.post('/v1/analyze/image', data={'grade': '3'}, files={'image': ('题目.png', picture.read_bytes(), 'image/png')})
    assert result.status_code == 200
    assert 'inlineData' in requests[0]['contents'][0]['parts'][1]


def test_session_history_reset_and_delete(service, picture):
    http, requests, _ = service
    first = http.post('/v1/sessions', json={'grade': 3}).json()['session_id']
    second = http.post('/v1/sessions', json={}).json()['session_id']
    r = http.post(f'/v1/sessions/{first}/messages/image', data={'text': '题目'}, files={'image': ('q.png', picture.read_bytes(), 'image/png')})
    assert r.status_code == 200 and r.json()['turn_count'] == 1
    http.post(f'/v1/sessions/{first}/messages', json={'text': '继续'})
    assert len(requests[-1]['contents']) == 3
    http.post(f'/v1/sessions/{second}/messages', json={'text': '另一题'})
    assert len(requests[-1]['contents']) == 1
    assert http.post(f'/v1/sessions/{first}/reset').json()['turn_count'] == 0
    assert http.delete(f'/v1/sessions/{first}').status_code == 204
    assert http.post(f'/v1/sessions/{first}/messages', json={'text': '继续'}).status_code == 404


@pytest.mark.parametrize('body', [{}, {'text': ' '}, {'text': '题目', 'grade': 13}, {'text': '题目', 'image': '/etc/passwd'}])
def test_bad_analysis_input_never_calls_model(service, body):
    http, requests, _ = service
    assert http.post('/v1/analyze', json=body).status_code == 422
    assert requests == []


def test_bad_image_and_model_error(service):
    http, requests, responses = service
    assert http.post('/v1/analyze/image', files={'image': ('bad.png', b'not an image', 'image/png')}).status_code == 422
    assert requests == []
    responses[:] = [503]
    assert http.post('/v1/analyze', json={'text': '题目'}).status_code == 502


def test_session_capacity_and_release(backend):
    client, _, _ = backend
    with TestClient(create_app(Settings(_env_file=None, service_max_sessions=1), tutor_factory=lambda s: MathTutor(settings=s, client=client))) as http:
        session = http.post('/v1/sessions', json={}).json()['session_id']
        assert http.post('/v1/sessions', json={}).status_code == 503
        http.delete(f'/v1/sessions/{session}')
        assert http.post('/v1/sessions', json={}).status_code == 201


def test_missing_configuration_is_503(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    with TestClient(create_app(Settings(_env_file=None))) as http:
        assert http.get('/health').status_code == 200
        assert http.post('/v1/analyze', json={'text': '题目'}).status_code == 503


def test_body_size_limit(service):
    http, requests, _ = service
    assert http.post('/v1/analyze', content=b'x' * (14 * 1024 * 1024 + 1)).status_code == 413
    assert requests == []


def test_session_limit_is_409_without_extra_model_request(backend):
    client, requests, _ = backend
    with TestClient(create_app(Settings(_env_file=None, max_turns=1), tutor_factory=lambda s: MathTutor(settings=s, client=client))) as http:
        session = http.post('/v1/sessions', json={}).json()['session_id']
        assert http.post(f'/v1/sessions/{session}/messages', json={'text': '题目'}).status_code == 200
        assert http.post(f'/v1/sessions/{session}/messages', json={'text': '继续'}).status_code == 409
        assert len(requests) == 1


def test_unsupported_upload_type(service):
    http, requests, _ = service
    response = http.post('/v1/analyze/image', files={'image': ('file.svg', b'<svg/>', 'image/svg+xml')})
    assert response.status_code == 415
    assert requests == []
