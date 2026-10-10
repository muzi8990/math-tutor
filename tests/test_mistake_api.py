import io
from uuid import uuid4

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from math_tutor.api import create_app
from math_tutor.settings import Settings
from math_tutor.mistakes.identity import get_student
from math_tutor.mistakes.models import StudentContext


@pytest.fixture
def mistake_client(tmp_path):
    student = StudentContext(uuid4())
    config = Settings(_env_file=None, database_path=tmp_path/'db.sqlite3', asset_dir=tmp_path/'assets', log_file=None)
    app = create_app(config)
    app.dependency_overrides[get_student] = lambda: student
    with TestClient(app) as client:
        yield client, app, student


def png():
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), 'white').save(buf, format='PNG')
    return buf.getvalue()


def upload(client, **data):
    return client.post('/v1/mistakes', files={'image': ('题目.png', png(), 'image/png')}, data=data)


def test_upload_restart_detail_and_scope(mistake_client):
    client, app, student = mistake_client
    response = upload(client)
    assert response.status_code == 201, response.text
    record = response.json()
    assert record['analysis_status'] == 'pending'
    detail = client.get('/v1/mistakes/'+record['id']).json()
    assert detail['grade'] is None
    assert detail['analysis'] is None
    asset = detail['assets'][0]
    assert 'storage_key' not in asset
    assert client.get(asset['url']).content == png()
    assert len(client.get('/v1/mistakes').json()['items']) == 1
    app.dependency_overrides[get_student] = lambda: StudentContext(uuid4())
    assert client.get('/v1/mistakes/'+record['id']).status_code == 404
    assert client.get(asset['url']).status_code == 404
    assert client.get('/v1/mistakes').json()['items'] == []


def test_duplicate_requires_explicit_continue(mistake_client):
    client, _, _ = mistake_client
    assert upload(client).status_code == 201
    assert upload(client).status_code == 409
    assert upload(client, allow_duplicate='true').status_code == 201


def test_auth_required(tmp_path):
    with TestClient(create_app(Settings(_env_file=None, database_path=tmp_path/'db', asset_dir=tmp_path/'assets',log_file=None))) as client:
        assert client.get('/v1/mistakes').status_code == 401


def test_pagination_and_bad_upload(mistake_client):
    client, _, _ = mistake_client
    for _ in range(3):
        assert upload(client, allow_duplicate='true').status_code == 201
    page = client.get('/v1/mistakes?limit=2').json()
    assert len(page['items']) == 2
    assert len(client.get('/v1/mistakes', params={'cursor': page['next_cursor']}).json()['items']) == 1
    assert client.get('/v1/mistakes?cursor=invalid').status_code == 422
    assert client.post('/v1/mistakes', files={'image': ('x.png', b'bad', 'image/png')}).status_code == 422
    assert client.post('/v1/mistakes', files={'image': ('x.txt', b'bad', 'text/plain')}).status_code == 415
