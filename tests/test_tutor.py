import base64
import io
import json

import httpx
import pytest
from google import genai
from google.genai import types
from PIL import Image

from math_tutor import MathTutor, TutorError
from math_tutor.images import load_image


@pytest.fixture
def picture(tmp_path):
    path = tmp_path / "题目.png"
    Image.new("RGB", (4, 4), "white").save(path)
    return path


@pytest.fixture
def backend():
    requests = []
    responses = ["先想一想平均分成几份。"]

    def handler(request):
        requests.append(json.loads(request.content))
        answer = responses.pop(0) if responses else "请继续。"
        if isinstance(answer, int):
            return httpx.Response(answer, json={"error": {"code": answer, "message": "provider failure"}})
        if isinstance(answer, dict):
            return httpx.Response(answer.get("error", {}).get("code", 200), json=answer)
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": answer}]}, "finishReason": "STOP"}]})

    client = genai.Client(api_key="offline-test-key", http_options=types.HttpOptions(
        client_args={"transport": httpx.MockTransport(handler)},
        retry_options=types.HttpRetryOptions(attempts=1),
    ))
    yield client, requests, responses
    client.close()


def test_photo_is_sent_and_retained_for_followup(backend, picture):
    client, requests, _ = backend
    tutor = MathTutor(client=client, model="test-model")
    assert tutor.chat("帮我理解这道题", image=picture) == "先想一想平均分成几份。"
    tutor.chat("分成六份")
    content = requests[1]["contents"]
    assert [entry["role"] for entry in content] == ["user", "model", "user"]
    assert types.Blob.model_validate(content[0]["parts"][1]["inlineData"]).mime_type == "image/png"
    assert base64.b64decode(content[0]["parts"][1]["inlineData"]["data"]).startswith(b"\x89PNG")
    assert content[-1]["parts"][0]["text"] == "分成六份"


def test_new_image_can_be_added_to_later_turn(backend, picture):
    client, requests, _ = backend
    tutor = MathTutor(client=client)
    tutor.chat("24平均分成6份")
    tutor.chat("这是我的步骤", image=picture, mode="check")
    assert "inlineData" in requests[-1]["contents"][-1]["parts"][1]


@pytest.mark.parametrize("bad_answer", ["", "   ", 503])
def test_failed_response_does_not_pollute_history(backend, bad_answer):
    client, requests, responses = backend
    tutor = MathTutor(client=client)
    responses[:] = [bad_answer, "重试成功"]
    with pytest.raises(TutorError):
        tutor.chat("第一次尝试")
    assert tutor.turn_count == 0
    assert tutor.chat("重试") == "重试成功"
    assert len(requests[-1]["contents"]) == 1


def test_reset_clears_history(backend):
    client, requests, _ = backend
    tutor = MathTutor(client=client)
    tutor.chat("第一题")
    tutor.reset()
    tutor.chat("第二题")
    assert len(requests[-1]["contents"]) == 1
    assert tutor.turn_count == 1


def test_analysis_does_not_enter_tutoring_history(backend, picture):
    client, requests, _ = backend
    tutor = MathTutor(client=client)
    tutor.analyze_image(picture)
    assert tutor.turn_count == 0
    tutor.chat("新的问题")
    assert len(requests[-1]["contents"]) == 1


def test_limit_preserves_old_context_instead_of_silently_dropping_it(backend):
    client, requests, _ = backend
    tutor = MathTutor(client=client, max_turns=1)
    tutor.chat("第一题")
    with pytest.raises(TutorError, match="reset"):
        tutor.chat("继续")
    assert len(requests) == 1


@pytest.mark.parametrize("kwargs", [{"text": " "}, {"text": "题目", "mode": "invalid"}])
def test_bad_request_is_rejected_before_model_call(backend, kwargs):
    client, requests, _ = backend
    tutor = MathTutor(client=client)
    with pytest.raises(ValueError):
        tutor.chat(**kwargs)
    assert requests == []


def test_mode_and_grade_are_sent_as_system_configuration(backend):
    client, requests, _ = backend
    tutor = MathTutor(client=client, grade=3)
    tutor.chat("24÷6", mode="solve")
    system = requests[0]["systemInstruction"]["parts"][0]["text"]
    assert "三" in system or "3" in system
    assert "完整" in system
    assert requests[0]["contents"][0]["parts"][0]["text"] == "24÷6"


def test_api_key_required(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="API_KEY"):
        MathTutor()


def test_data_url_and_path_produce_valid_images(picture):
    url = "data:image/png;base64," + base64.b64encode(picture.read_bytes()).decode()
    for source in (picture, url):
        data, mime = load_image(source)
        assert mime == "image/png"
        assert Image.open(io.BytesIO(data)).size == (4, 4)


@pytest.mark.parametrize("source", ["data:image/png;base64,%%%", "data:image/svg+xml;base64,PHN2Zz4=", "data:image/png;base64,aGVsbG8="])
def test_invalid_images_are_rejected(source):
    with pytest.raises(ValueError):
        load_image(source)


def test_image_limit_is_checked(picture):
    with pytest.raises(ValueError):
        load_image(picture, max_bytes=4)


def test_grade_range_is_checked(backend):
    client, _, _ = backend
    with pytest.raises(ValueError):
        MathTutor(client=client, grade=0)


@pytest.mark.parametrize("reason", ["MAX_TOKENS", "SAFETY"])
def test_incomplete_answer_is_not_saved(backend, reason):
    client, _, responses = backend
    responses[:] = [{"candidates": [{"content": {"role": "model", "parts": [{"text": "部分解答"}]}, "finishReason": reason}]}]
    tutor = MathTutor(client=client)
    with pytest.raises(TutorError):
        tutor.chat("这道题怎么做？")
    assert tutor.turn_count == 0


def test_prompt_block_is_not_saved(backend):
    client, _, responses = backend
    responses[:] = [{"promptFeedback": {"blockReason": "SAFETY"}}]
    tutor = MathTutor(client=client)
    with pytest.raises(TutorError):
        tutor.chat("题目")
    assert tutor.turn_count == 0


def test_closed_tutor_does_not_send_requests(backend):
    client, requests, _ = backend
    tutor = MathTutor(client=client)
    tutor.close()
    with pytest.raises(TutorError):
        tutor.chat("题目")
    assert requests == []
