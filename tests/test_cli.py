import builtins

import pytest

from math_tutor import MathTutor
from math_tutor import cli

# Exercise the real tutor/SDK; only the external HTTP transport is replaced.
from test_tutor import backend  # noqa: F401


def test_cli_one_shot(backend, monkeypatch, capsys):
    client, requests, _ = backend
    monkeypatch.setattr(cli, "MathTutor", lambda **kw: MathTutor(client=client, **kw))
    assert cli.main(["24÷6", "--mode", "solve", "--env-file", "/nonexistent/test.env"]) == 0
    assert "先想一想" in capsys.readouterr().out
    assert len(requests) == 1


def test_cli_reset_and_followup(backend, monkeypatch, capsys):
    client, requests, _ = backend
    monkeypatch.setattr(cli, "MathTutor", lambda **kw: MathTutor(client=client, **kw))
    lines = iter(["第一题", "/reset", "第二题", "/quit"])
    monkeypatch.setattr(builtins, "input", lambda _: next(lines))
    assert cli.main(["--chat", "--env-file", "/nonexistent/test.env"]) == 0
    assert len(requests[-1]["contents"]) == 1
    assert "已清除" in capsys.readouterr().out


def test_cli_bad_input_exits_before_model_call():
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2
