"""LLM client: OpenAI-compatible chat completions over stdlib urllib (architecture D11).

Settings (read at call time, see json4win/.env.example): MISTRAL_API_KEY, LLM_BASE_URL,
LLM_MAX_TOKENS, LLM_MAX_TOKENS_CAP, LLM_TIMEOUT, LLM_HTTP_RETRIES, LLM_ANSWER_RETRIES,
LLM_REASONING_EFFORT (+ _DECISION / _EXTRACT), LLM_RETRY_REASONING_EFFORT, LLM_SEED. Models are
chosen by the caller (LLM_MODEL_DECISION / LLM_MODEL_EXTRACT, see model()).

GLM-5.3-Flash is a reasoning model: `message.content` is a list of blocks (`thinking`, `text`) and
the reasoning tokens count against `max_tokens`. It sometimes thinks through the whole budget
(finish_reason="length"), non-deterministically; chat_json() then retries with a lower
`reasoning_effort` (the Mistral API accepts low/high/max for it) and a larger budget. Mistral's
`random_seed` is always sent, but did not make the model's answers reproducible in a live test.
Errors, logs and the trace never contain the key, the prompt or the answer text.
"""

import http.client
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from json4win import env, trace

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.mistral.ai/v1"  # delivery: api.eu.mistral.ai (task D1)
DEFAULT_MODEL = "zai-glm-5-3-flash"
# Low reasoning effort: same F1 on the checked case, LLM time 2-3 s instead of 4-16 s per document.
DEFAULT_REASONING_EFFORT = "low"
# Appended to the system prompt on a retry when the model does not accept `reasoning_effort`.
BRIEF_REASONING = "Rozumuj krótko i od razu podaj odpowiedź: sam obiekt JSON."


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


class _RequestRejected(LlmError):
    """HTTP 4xx other than 429: the request itself is wrong, resending it won't help."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def _request(url: str, payload: dict, key: str, timeout: float) -> dict:
    """POST `payload`; retries with exponential backoff on 429, 5xx, timeouts, connection errors."""
    model_name = payload["model"]
    retries = _int_env("LLM_HTTP_RETRIES", 4)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(retries + 1):
        delay = min(2.0**attempt, 30.0)
        try:
            return _post(url, body, key, timeout)
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                detail = e.read()[:300].decode("utf-8", "replace")
                raise _RequestRejected(f"{model_name}: HTTP {e.code}: {detail}", e.code) from None
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
    raise AssertionError("unreachable")


def _with_brief_note(messages: list[dict]) -> list[dict]:
    """`messages` with BRIEF_REASONING added to the system prompt (or as a new one)."""
    if messages and messages[0].get("role") == "system":
        first = dict(messages[0])
        first["content"] = f"{first.get('content') or ''}\n\n{BRIEF_REASONING}"
        return [first, *messages[1:]]
    return [{"role": "system", "content": BRIEF_REASONING}, *messages]


def reasoning_effort(role: str | None) -> str | None:
    """First-attempt reasoning_effort for a role: LLM_REASONING_EFFORT_<ROLE>, else
    LLM_REASONING_EFFORT, else DEFAULT_REASONING_EFFORT; "off" = not sent (the model's default)."""
    raw = (role and env.get(f"LLM_REASONING_EFFORT_{role.upper()}")) or env.get(
        "LLM_REASONING_EFFORT", DEFAULT_REASONING_EFFORT
    )
    return None if raw in ("", "off") else raw


def _plan(
    base: int, cap: int, retries: int, first: str | None, retry: str | None
) -> list[tuple[int, str | None]]:
    """(max_tokens, reasoning_effort) per attempt: `first` at the base budget, then `retry` (or
    `first` if retry is unset/"off") at the same budget, then the budget doubled per attempt up to
    `cap`. If `first` already is the retry effort, the same-budget step is skipped."""
    retry = first if retry in (None, "", "off") else retry
    skip = 1 if first and retry == first else 0
    plan = [(base, first)]
    for i in range(1 + skip, retries + 1 + skip):
        plan.append((max(base, min(base * 2 ** (i - 1), cap)), retry))
    return plan


def chat_json(
    model_name: str,
    messages: list[dict],
    *,
    max_tokens: int | None = None,
    role: str | None = None,
) -> dict:
    """Send a chat completion in JSON mode at temperature 0; return the answer as a JSON object.

    The first attempt sends reasoning_effort(role) if one is configured (LLM_REASONING_EFFORT*).

    HTTP failures are retried in _request(). An unusable answer (finish_reason other than "stop",
    no text, or text that is not a JSON object) is retried LLM_ANSWER_RETRIES times: first with
    the same budget and a lower reasoning effort (LLM_RETRY_REASONING_EFFORT), then with the budget
    doubled per attempt up to LLM_MAX_TOKENS_CAP. If the model rejects `reasoning_effort`, the
    retry asks for brief reasoning in the system prompt instead. If the first attempt already used
    the retry effort, the retries go straight to the larger budgets. Raises LlmError when all fail.
    """
    key = env.get("MISTRAL_API_KEY")
    if not key:
        raise LlmError("MISTRAL_API_KEY is not set (json4win/.env.local)")
    url = env.get("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
    timeout = _int_env("LLM_TIMEOUT", 180)
    base = max_tokens or _int_env("LLM_MAX_TOKENS", 16000)
    cap = _int_env("LLM_MAX_TOKENS_CAP", 64000)
    retries = max(0, _int_env("LLM_ANSWER_RETRIES", 2))
    retry_effort = env.get("LLM_RETRY_REASONING_EFFORT", "low")
    plan = _plan(base, cap, retries, reasoning_effort(role), retry_effort)
    seed = _int_env("LLM_SEED", 42)

    record: dict[str, Any] = {"model": model_name, "role": role, "attempts": []}
    t_call = time.perf_counter()
    brief = False  # the model rejected reasoning_effort: ask in the prompt instead
    reason = ""
    try:
        for n, (budget, effort) in enumerate(plan, 1):
            payload: dict[str, Any] = {
                "model": model_name,
                "messages": _with_brief_note(messages) if brief else messages,
                "temperature": 0,
                "max_tokens": budget,
                "random_seed": seed,
                "response_format": {"type": "json_object"},
            }
            if effort and effort != "off" and not brief:
                payload["reasoning_effort"] = effort
            t0 = time.perf_counter()
            try:
                data = _request(url, payload, key, timeout * budget / base)
            except _RequestRejected as e:
                if "reasoning_effort" not in payload or e.code not in (400, 422):
                    raise
                log.warning(
                    "llm %s: reasoning_effort rejected, asking for brief reasoning", model_name
                )
                brief = True
                payload["messages"] = _with_brief_note(messages)
                del payload["reasoning_effort"]
                data = _request(url, payload, key, timeout * budget / base)
            answer, reason, finish, usage = _read(data)
            record["attempts"].append(
                {
                    "max_tokens": budget,
                    "reasoning_effort": payload.get("reasoning_effort"),
                    "brief_note": brief,
                    "finish_reason": finish,
                    "outcome": reason or "ok",
                    **usage,
                    "seconds": round(time.perf_counter() - t0, 3),
                }
            )
            if answer is not None:
                log.debug("llm %s: attempt %d ok, tokens %s", model_name, n, usage)
                return answer
            log.warning(
                "llm %s: attempt %d/%d failed: %s (max_tokens=%d, reasoning_effort=%s, tokens %s)",
                model_name,
                n,
                len(plan),
                reason,
                budget,
                payload.get("reasoning_effort") or "default",
                usage,
            )
        budgets = "/".join(str(b) for b, _ in plan)
        raise LlmError(f"{model_name}: {reason} after {len(plan)} attempts (max_tokens {budgets})")
    except LlmError as e:
        record["error"] = str(e)
        raise
    finally:
        record["seconds"] = round(time.perf_counter() - t_call, 3)
        trace.add("llm", record)


def _read(data: dict) -> tuple[dict | None, str, Any, dict]:
    """(answer object or None, why it is unusable, finish_reason, token usage) of a response."""
    usage = data.get("usage") if isinstance(data, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get("completion_tokens_details") or {}
    tokens = {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens") if isinstance(details, dict) else None,
    }
    try:
        choice = data["choices"][0]
        finish = choice.get("finish_reason")
    except (KeyError, IndexError, TypeError, AttributeError):
        return None, "response has no choices", None, tokens
    if finish != "stop":
        return None, f"finish_reason={finish!r}", finish, tokens
    text = message_text(choice.get("message") or {})
    if not text.strip():
        return None, "empty answer", finish, tokens
    try:
        return parse_json_object(text), "", finish, tokens
    except LlmError as e:
        return None, str(e), finish, tokens


def answer_text(obj: Any) -> str:
    """A parsed answer as compact JSON, to put back into the conversation on a retry."""
    return json.dumps(obj, ensure_ascii=False)
