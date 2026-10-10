import os

import pytest
from pydantic import ValidationError

from math_tutor import MathTutor, Settings
from math_tutor import cli
from test_tutor import backend  # noqa: F401


@pytest.fixture(autouse=True)
def clean_configuration(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.upper().startswith(('GOOGLE_', 'GEMINI_', 'TUTOR_')):
            monkeypatch.delenv(key)


def test_sources_and_secret_priority(monkeypatch, tmp_path):
    (tmp_path / '.env').write_text('GOOGLE_API_KEY=file-key\nGEMINI_MODEL=file-model\nTUTOR_GRADE=2\nUNRELATED=value\n')
    monkeypatch.setenv('GEMINI_API_KEY', 'environment-key')
    monkeypatch.setenv('GEMINI_MODEL', 'environment-model')
    settings = Settings(model='explicit-model')
    assert settings.model == 'explicit-model'
    assert settings.api_key.get_secret_value() == 'environment-key'
    assert settings.grade == 2
    assert 'environment-key' not in repr(settings)
    assert 'environment-key' not in settings.model_dump_json()
    assert 'GOOGLE_API_KEY' not in os.environ


def test_api_key_alias_and_explicit_override(monkeypatch):
    monkeypatch.setenv('GOOGLE_API_KEY', 'google-key')
    monkeypatch.setenv('GEMINI_API_KEY', 'gemini-key')
    assert Settings().api_key.get_secret_value() == 'google-key'
    assert Settings(api_key='explicit-key').api_key.get_secret_value() == 'explicit-key'


def test_custom_file_and_disable_dotenv(tmp_path):
    (tmp_path / '.env').write_text('GEMINI_MODEL=default-file\n')
    custom = tmp_path / 'custom.env'
    custom.write_text('GEMINI_MODEL=custom-file\nTUTOR_MAX_TURNS=5\n')
    assert Settings(_env_file=custom).model == 'custom-file'
    assert Settings(_env_file=custom).max_turns == 5
    assert Settings(_env_file=None).model == 'gemini-2.5-flash'


@pytest.mark.parametrize('values', [
    {'grade': 0}, {'grade': True}, {'max_turns': 0}, {'max_turns': 2.5},
    {'timeout_ms': -1}, {'temperature': 3}, {'max_output_tokens': 0},
    {'model': '  '}, {'api_key': '  '},
])
def test_invalid_values_fail(values):
    with pytest.raises(ValidationError):
        Settings(**values)


def test_settings_are_used_in_model_request_and_session(backend):
    client, requests, _ = backend
    settings = Settings(model='configured-model', grade=4, max_turns=1, temperature=0.4, max_output_tokens=1234)
    tutor = MathTutor(settings=settings, client=client, grade=3)
    tutor.chat('题目')
    assert tutor.model == 'configured-model'
    assert tutor.grade == 3 and settings.grade == 4
    assert tutor.max_turns == 1
    assert requests[0]['generationConfig']['temperature'] == 0.4
    assert requests[0]['generationConfig']['maxOutputTokens'] == 1234


def test_cli_overrides_file_without_mutating_environment(backend, monkeypatch, tmp_path):
    client, requests, _ = backend
    custom = tmp_path / 'custom.env'
    custom.write_text('GEMINI_MODEL=from-file\nTUTOR_GRADE=2\nTUTOR_TEMPERATURE=0.6\n')
    monkeypatch.setattr(cli, 'MathTutor', lambda **kw: MathTutor(client=client, **kw))
    assert cli.main(['题目', '--env-file', str(custom), '--model', 'from-cli', '--grade', '5']) == 0
    assert requests[0]['generationConfig']['temperature'] == 0.6
    assert '5' in requests[0]['systemInstruction']['parts'][0]['text']
    assert 'GEMINI_MODEL' not in os.environ
