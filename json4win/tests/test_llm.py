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


def _thinking(text: str = "", finish: str = "stop") -> dict:
    """A reasoning-model response: a thinking block, then the answer text (if any)."""
    blocks = [{"type": "thinking", "thinking": "..."}] + (
        [{"type": "text", "text": text}] * bool(text)
    )
    r = _response(blocks, finish)
    r["usage"] = {
        "prompt_tokens": 50,
        "completion_tokens": 900,
        "completion_tokens_details": {"reasoning_tokens": 890},
    }
    return r


LENGTH = _thinking(finish="length")


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(b'{"message": "bad"}'))


@pytest.fixture
def post(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1/")
    for name in (
        "LLM_MAX_TOKENS",
        "LLM_MAX_TOKENS_CAP",
        "LLM_TIMEOUT",
        "LLM_HTTP_RETRIES",
        "LLM_ANSWER_RETRIES",
        "LLM_RETRY_REASONING_EFFORT",
        "LLM_SEED",
        "LLM_REASONING_EFFORT",
        "LLM_REASONING_EFFORT_DECISION",
        "LLM_REASONING_EFFORT_EXTRACT",
    ):
        monkeypatch.delenv(name, raising=False)
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
        ([_response('{"a": 1}', finish="length")] * 3, "finish_reason='length' after 3 attempts"),
        ([_response("not json")] * 3, "not JSON after 3 attempts"),
        ([_thinking()] * 3, "empty answer after 3 attempts"),
        ([{"choices": []}] * 3, "no choices"),
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
        llm.chat_json("m", [])


def test_model_roles(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL_DECISION", "small")
    monkeypatch.delenv("LLM_MODEL_EXTRACT", raising=False)
    assert llm.model("decision") == "small"
    assert llm.model("extract") == llm.DEFAULT_MODEL


def _sent(calls, key):
    return [body.get(key) for _, body, _, _ in calls]


def test_length_then_success(post) -> None:
    calls = post(LENGTH, _thinking('{"ok": 1}'))
    assert llm.chat_json("m", [{"role": "user", "content": "x"}]) == {"ok": 1}
    # the retry keeps the budget and lowers the reasoning effort; the seed is always sent
    assert _sent(calls, "max_tokens") == [16000, 16000]
    assert _sent(calls, "reasoning_effort") == [None, "low"]
    assert _sent(calls, "random_seed") == [42, 42]
    assert "reasoning_effort" not in calls[0][1]


def test_length_twice_uses_larger_budget_capped(post, monkeypatch) -> None:
    monkeypatch.setenv("LLM_MAX_TOKENS", "1000")
    monkeypatch.setenv("LLM_MAX_TOKENS_CAP", "3000")
    monkeypatch.setenv("LLM_ANSWER_RETRIES", "3")
    monkeypatch.setenv("LLM_TIMEOUT", "10")
    calls = post(LENGTH, LENGTH, LENGTH, _thinking('{"ok": 1}'))
    assert llm.chat_json("m", []) == {"ok": 1}
    assert _sent(calls, "max_tokens") == [1000, 1000, 2000, 3000]
    assert [timeout for *_, timeout in calls] == [10, 10, 20, 30]  # scaled with the budget


def test_still_failing_raises(post, caplog) -> None:
    calls = post(LENGTH, LENGTH, LENGTH)
    with pytest.raises(llm.LlmError, match=r"after 3 attempts \(max_tokens 16000/16000/32000\)"):
        llm.chat_json("m", [])
    assert len(calls) == 3
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 3 and "attempt 1/3" in warnings[0] and "890" in warnings[0]


def test_empty_text_and_bad_json_are_retried(post) -> None:
    calls = post(_thinking(), _thinking("chwila..."), _thinking('{"ok": 1}'))
    assert llm.chat_json("m", []) == {"ok": 1}
    assert len(calls) == 3


def test_configured_seed_effort_and_retries(post, monkeypatch) -> None:
    monkeypatch.setenv("LLM_SEED", "7")
    monkeypatch.setenv("LLM_RETRY_REASONING_EFFORT", "high")
    monkeypatch.setenv("LLM_ANSWER_RETRIES", "1")
    calls = post(LENGTH, LENGTH)
    with pytest.raises(llm.LlmError, match="after 2 attempts"):
        llm.chat_json("m", [])
    assert _sent(calls, "random_seed") == [7, 7]
    assert _sent(calls, "reasoning_effort") == [None, "high"]


def test_effort_off_and_no_retries(post, monkeypatch) -> None:
    monkeypatch.setenv("LLM_RETRY_REASONING_EFFORT", "off")
    calls = post(LENGTH, _thinking('{"ok": 1}'))
    assert llm.chat_json("m", []) == {"ok": 1}
    assert _sent(calls, "reasoning_effort") == [None, None]
    monkeypatch.setenv("LLM_ANSWER_RETRIES", "0")
    post(LENGTH)
    with pytest.raises(llm.LlmError, match="after 1 attempts"):
        llm.chat_json("m", [])


def test_rejected_effort_falls_back_to_brief_note(post) -> None:
    messages = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "x"}]
    calls = post(LENGTH, _http_error(422), _thinking('{"ok": 1}'))
    assert llm.chat_json("m", messages) == {"ok": 1}
    assert _sent(calls, "reasoning_effort") == [None, "low", None]
    assert calls[2][1]["messages"][0]["content"] == f"SYS\n\n{llm.BRIEF_REASONING}"
    assert calls[2][1]["messages"][1] == messages[1]
    assert messages[0]["content"] == "SYS"  # the caller's messages are not modified


def test_attempts_recorded_in_trace(post, tmp_path) -> None:
    from json4win import trace

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    post(LENGTH, _thinking('{"ok": 1}'), LENGTH, LENGTH, LENGTH)
    with pytest.raises(llm.LlmError), trace.document(pdf, tmp_path / "a.trace.json") as t:
        llm.chat_json("m", [])
        llm.chat_json("m", [])
    first, second = t.data["llm"]
    assert [a["outcome"] for a in first["attempts"]] == ["finish_reason='length'", "ok"]
    assert first["attempts"][0] | {"seconds": 0} == {
        "max_tokens": 16000,
        "reasoning_effort": None,
        "brief_note": False,
        "finish_reason": "length",
        "outcome": "finish_reason='length'",
        "prompt_tokens": 50,
        "completion_tokens": 900,
        "reasoning_tokens": 890,
        "seconds": 0,
    }
    assert "error" not in first and "after 3 attempts" in second["error"]
    assert t.data["llm_s"] >= 0 and t.data["error"]["type"] == "LlmError"
    md = (tmp_path / "a.trace.md").read_text(encoding="utf-8")
    assert "ponowienia `m`" in md and "max_tokens 32000" in md


def test_first_attempt_effort_then_retry_plan(post, monkeypatch) -> None:
    monkeypatch.setenv("LLM_REASONING_EFFORT", "high")
    calls = post(LENGTH, LENGTH, _thinking('{"ok": 1}'))
    assert llm.chat_json("m", []) == {"ok": 1}
    assert _sent(calls, "reasoning_effort") == ["high", "low", "low"]
    assert _sent(calls, "max_tokens") == [16000, 16000, 32000]


def test_first_attempt_already_low_goes_straight_to_bigger_budget(post, monkeypatch) -> None:
    monkeypatch.setenv("LLM_REASONING_EFFORT", "low")
    monkeypatch.setenv("LLM_MAX_TOKENS_CAP", "50000")
    calls = post(LENGTH, LENGTH, LENGTH)
    with pytest.raises(llm.LlmError, match="max_tokens 16000/32000/50000"):
        llm.chat_json("m", [])
    assert _sent(calls, "reasoning_effort") == ["low", "low", "low"]


@pytest.mark.parametrize(
    "general, decision, role, want",
    [
        ("", "", "decision", None),
        ("off", "", "extract", None),
        ("high", "", "decision", "high"),
        ("high", "low", "decision", "low"),
        ("high", "low", "extract", "high"),
        ("high", "low", None, "high"),
        ("", "low", "extract", None),
    ],
)
def test_reasoning_effort_per_role(post, monkeypatch, general, decision, role, want) -> None:
    monkeypatch.setenv("LLM_REASONING_EFFORT", general)
    monkeypatch.setenv("LLM_REASONING_EFFORT_DECISION", decision)
    assert llm.reasoning_effort(role) == want
    calls = post(_thinking('{"ok": 1}'))
    llm.chat_json("m", [], role=role)
    assert _sent(calls, "reasoning_effort") == [want]
    assert ("reasoning_effort" in calls[0][1]) == (want is not None)
