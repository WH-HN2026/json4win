import http.client
import io
import json
import urllib.error

import pytest

from json4win import llm


@pytest.mark.parametrize(
    "message, want",
    [
        ({"content": '{"a": 1}'}, '{"a": 1}'),
        (
            {
                "content": [
                    {"type": "thinking", "thinking": "hmm"},
                    {"type": "text", "text": '{"a": 1}'},
                ]
            },
            '{"a": 1}',
        ),
        (
            {"content": [{"type": "text", "text": '{"a"'}, {"type": "text", "text": ": 1}"}]},
            '{"a": 1}',
        ),
        ({"content": None}, ""),
    ],
)
def test_message_text(message, want) -> None:
    assert llm.message_text(message) == want


@pytest.mark.parametrize(
    "text, want",
    [
        ('{"klasa": "inne"}', {"klasa": "inne"}),
        ('```json\n{"klasa": "inne"}\n```', {"klasa": "inne"}),
        ('Odpowiedź: {"a": {"b": null}} koniec', {"a": {"b": None}}),
    ],
)
def test_parse_json_object(text, want) -> None:
    assert llm.parse_json_object(text) == want


@pytest.mark.parametrize("text", ["", "brak", "[1, 2]", '{"a": '])
def test_parse_json_object_rejects(text) -> None:
    with pytest.raises(llm.LlmError):
        llm.parse_json_object(text)


def _response(content, finish="stop") -> dict:
    return {"choices": [{"message": {"content": content}, "finish_reason": finish}], "usage": {}}


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(b'{"message": "bad"}'))


@pytest.fixture
def post(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1/")
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    calls = []

    def install(*results):
        results = list(results)

        def fake(url, body, key, timeout):
            calls.append((url, json.loads(body), key, timeout))
            r = results.pop(0)
            if isinstance(r, BaseException):
                raise r
            return r

        monkeypatch.setattr(llm, "_post", fake)
        return calls

    return install


def test_chat_json_request_and_retries(post) -> None:
    calls = post(
        _http_error(429),
        TimeoutError(),
        http.client.IncompleteRead(b""),
        _http_error(503),
        _response('{"ok": true}'),
    )
    assert llm.chat_json("m", [{"role": "user", "content": "x"}]) == {"ok": True}
    assert len(calls) == 5
    url, body, key, _ = calls[0]
    assert url == "https://llm.example/v1/chat/completions" and key == "test-key"
    assert body["temperature"] == 0 and body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] >= 8000 and body["model"] == "m"


@pytest.mark.parametrize(
    "results, message",
    [
        ([_http_error(400)], "HTTP 400"),
        ([_response('{"a": 1}', finish="length")], "finish_reason='length'"),
        ([_response("not json")], "not JSON"),
        ([_http_error(500)] * 5, "gave up after 5 attempts"),
    ],
)
def test_chat_json_failures(post, results, message) -> None:
    calls = post(*results)
    with pytest.raises(llm.LlmError, match=message) as e:
        llm.chat_json("m", [])
    assert "test-key" not in str(e.value)
    assert len(calls) == len(results)


def test_missing_key(monkeypatch) -> None:
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(llm.LlmError, match="MISTRAL_API_KEY"):
        llm.chat("m", [])


def test_model_roles(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL_DECISION", "small")
    monkeypatch.delenv("LLM_MODEL_EXTRACT", raising=False)
    assert llm.model("decision") == "small"
    assert llm.model("extract") == llm.DEFAULT_MODEL
