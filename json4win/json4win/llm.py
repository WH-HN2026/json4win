"""LLM client: OpenAI-compatible chat completions over stdlib urllib (architecture D11).

Settings (read at call time, see json4win/.env.example): MISTRAL_API_KEY, LLM_BASE_URL,
LLM_MAX_TOKENS, LLM_TIMEOUT, LLM_HTTP_RETRIES. Models are chosen by the caller
(LLM_MODEL_DECISION / LLM_MODEL_EXTRACT, see model()).

GLM-5.3-Flash is a reasoning model: `message.content` is a list of blocks (`thinking`, `text`) and
the reasoning tokens count against `max_tokens`, so the default budget is generous and any finish
reason other than "stop" is a failure. Errors never contain the key, the prompt or the answer text.
"""

import http.client
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from json4win import env

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.mistral.ai/v1"
DEFAULT_MODEL = "zai-glm-5-3-flash"


class LlmError(RuntimeError):
    """The LLM call failed or did not return a JSON object."""


def model(role: str) -> str:
    """Model name for a role: "decision" (LLM_MODEL_DECISION) or "extract" (LLM_MODEL_EXTRACT)."""
    return env.get(f"LLM_MODEL_{role.upper()}", DEFAULT_MODEL)


def _int_env(name: str, default: int) -> int:
    raw = env.get(name)
    try:
        return int(raw) if raw else default
    except ValueError as e:
        raise LlmError(f"{name} must be an integer, got {raw!r}") from e


def message_text(message: dict) -> str:
    """The answer text of a chat message: a plain string, or the `text` blocks of a block list."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text") or "" for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def parse_json_object(text: str) -> dict:
    """The JSON object in `text` (tolerates ```json fences and text around the object)."""
    text = text.strip()
    try:
        obj = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise LlmError("answer is not JSON") from None
        try:
            obj = json.loads(text[start : end + 1])
        except ValueError as e:
            raise LlmError(f"answer is not valid JSON: {e.msg} at {e.pos}") from None
    if not isinstance(obj, dict):
        raise LlmError(f"answer is JSON {type(obj).__name__}, expected an object")
    return obj


def _post(url: str, body: bytes, key: str, timeout: float) -> dict:
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def chat(model_name: str, messages: list[dict], *, max_tokens: int | None = None) -> str:
    """Send a chat completion in JSON mode at temperature 0; return the answer text.

    Retries with exponential backoff on 429, 5xx, timeouts and connection errors.
    """
    key = env.get("MISTRAL_API_KEY")
    if not key:
        raise LlmError("MISTRAL_API_KEY is not set (json4win/.env.local)")
    url = env.get("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
    timeout = _int_env("LLM_TIMEOUT", 180)
    retries = _int_env("LLM_HTTP_RETRIES", 4)
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens or _int_env("LLM_MAX_TOKENS", 16000),
        "response_format": {"type": "json_object"},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    for attempt in range(retries + 1):
        delay = min(2.0**attempt, 30.0)
        try:
            data = _post(url, body, key, timeout)
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                detail = e.read()[:300].decode("utf-8", "replace")
                raise LlmError(f"{model_name}: HTTP {e.code}: {detail}") from None
            retry_after = e.headers.get("Retry-After") if e.headers else None
            if retry_after and retry_after.isdigit():
                delay = min(float(retry_after), 60.0)
            reason = f"HTTP {e.code}"
        except (OSError, http.client.HTTPException) as e:  # timeouts, URLError, SSL, resets
            reason = type(e).__name__
        except ValueError:
            reason = "invalid JSON response"
        if attempt == retries:
            raise LlmError(f"{model_name}: {reason}, gave up after {retries + 1} attempts")
        log.warning(
            "llm %s: %s, retry %d/%d in %.0fs", model_name, reason, attempt + 1, retries, delay
        )
        time.sleep(delay)

    try:
        choice = data["choices"][0]
    except (KeyError, IndexError, TypeError):
        raise LlmError(f"{model_name}: response has no choices") from None
    finish = choice.get("finish_reason")
    if finish != "stop":
        raise LlmError(f"{model_name}: finish_reason={finish!r} (raise LLM_MAX_TOKENS?)")
    usage = data.get("usage") or {}
    log.debug(
        "llm %s: %s prompt + %s completion tokens",
        model_name,
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
    )
    return message_text(choice.get("message") or {})


def chat_json(model_name: str, messages: list[dict], *, max_tokens: int | None = None) -> dict:
    """chat(), with the answer parsed as a JSON object (LlmError if it isn't one)."""
    text = chat(model_name, messages, max_tokens=max_tokens)
    try:
        return parse_json_object(text)
    except LlmError as e:
        raise LlmError(f"{model_name}: {e}") from None


def answer_text(obj: Any) -> str:
    """A parsed answer as compact JSON, to put back into the conversation on a retry."""
    return json.dumps(obj, ensure_ascii=False)
