"""LightOnOCR-2-1B through an EU/EEA OpenAI-compatible API (`OCR_BACKEND=lighton_api`, task P8).

The same open-weights model as `json4win.ocr_lighton`, but served remotely: IONOS AI Model Hub
(default, Germany) or EUrouter (Netherlands, routed to IONOS); docs/ocr.md. Stdlib only: the HTTP
POST is `json4win.llm._post` (urllib), with its own short retry loop here (429, 5xx, timeouts,
connection errors; Retry-After honoured).

The page is rendered at 200 dpi (json4win.ocr) and downscaled to a longest side of 1540 px with
`ocr_lighton.resize()` (the size the model was trained on), sent as a PNG base64 data URI. The
message content is only the image, as in the IONOS example and the model's chat template. The
answer is markdown, cleaned by `ocr_lighton.clean_text()`.

Settings (see json4win/.env.example): OCR_API_BASE_URL, OCR_API_MODEL, OCR_API_KEY,
OCR_API_TIMEOUT, OCR_API_RETRIES, OCR_API_MAX_TOKENS, OCR_API_TEMPERATURE, OCR_API_TOP_P,
OCR_API_EXTRA_BODY (JSON object merged into every request body, e.g. EUrouter's `provider`).
The key is read at call time only: it is not part of the settings, the cache key, logs or errors.
"""

from __future__ import annotations

import base64
import email.utils
import http.client
import io
import json
import logging
import math
import threading
import time
import urllib.error
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime

from json4win import env, ocr_lighton

log = logging.getLogger(__name__)

BACKEND = "lighton_api"
DEFAULT_BASE_URL = "https://openai.inference.de-txl.ionos.com/v1"  # IONOS AI Model Hub, Berlin
DEFAULT_MODEL = "lightonai/LightOnOCR-2-1B"
RENDER_DPI = ocr_lighton.RENDER_DPI
LONGEST_SIDE = ocr_lighton.LONGEST_SIDE
RESIZE = ocr_lighton.RESIZE
IMAGE_FORMAT = "png"
PROMPT = None  # the message is the image only
CACHE_FORMAT = 1  # bump when the cached raw output would change for the same settings
MAX_IMAGE_BYTES = 12 * 1024 * 1024  # IONOS: one inline image <= 12 MiB
MAX_RETRY_DELAY = 5.0  # cap on any wait between attempts (Retry-After or backoff), seconds
BREAKER_FAILURES = 3  # consecutive failed pages after which the API is not called again


class OcrApiError(RuntimeError):
    """The OCR API call failed (no key, HTTP error, timeouts, unusable response)."""


@dataclass(frozen=True)
class ApiSettings:
    """API OCR settings. Everything but timeout/retries is part of the OCR cache key."""

    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    max_tokens: int = 4096  # per page (model card value); a dense A4 page needs ~1500
    temperature: float = 0.0  # greedy, like the local backend (IONOS example: 0.2 / top_p 0.9)
    top_p: float = 1.0
    extra_body: str = ""  # OCR_API_EXTRA_BODY as canonical JSON (sorted keys), "" = none
    timeout: float = 20.0  # seconds per request (one page is expected to take seconds, unmeasured)
    retries: int = 1  # extra attempts after the first one


def worst_case_seconds(s: ApiSettings) -> float:
    """Longest a page can spend in the API before it fails over: every attempt times out and
    every wait is capped. Defaults: 2 x 20 s + 5 s = 45 s. (The timeout is urllib's per socket
    operation; a server trickling bytes slower than that could exceed it.)"""
    return (s.retries + 1) * s.timeout + s.retries * MAX_RETRY_DELAY


def _number(name: str, default: float, *, integer: bool = False) -> float:
    raw = env.get(name)
    if not raw:
        return default
    try:
        value = int(raw) if integer else float(raw)
    except ValueError as e:
        kind = "an integer" if integer else "a number"
        raise ValueError(f"{name} must be {kind}, got {raw!r}") from e
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be >= 0, got {raw!r}")
    return value


def parse_extra_body(raw: str) -> str:
    """OCR_API_EXTRA_BODY as canonical JSON ("" if empty); ValueError unless a JSON object."""
    if not raw.strip():
        return ""
    try:
        obj = json.loads(raw)
    except ValueError as e:
        raise ValueError(f"OCR_API_EXTRA_BODY is not valid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise ValueError(f"OCR_API_EXTRA_BODY must be a JSON object, got {type(obj).__name__}")
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def settings_from_env() -> ApiSettings:
    """Settings from env (OCR_API_*); invalid values raise ValueError (config, no fallback)."""
    d = ApiSettings()
    base_url = env.get("OCR_API_BASE_URL", d.base_url).strip().rstrip("/")
    if urllib.parse.urlsplit(base_url).scheme not in ("http", "https"):
        raise ValueError(f"OCR_API_BASE_URL must be an http(s) URL, got {base_url!r}")
    max_tokens = int(_number("OCR_API_MAX_TOKENS", d.max_tokens, integer=True))
    if max_tokens <= 0:
        raise ValueError(f"OCR_API_MAX_TOKENS must be > 0, got {max_tokens}")
    timeout = _number("OCR_API_TIMEOUT", d.timeout)
    if timeout <= 0:
        raise ValueError(f"OCR_API_TIMEOUT must be > 0, got {timeout}")
    return ApiSettings(
        base_url=base_url,
        model=env.get("OCR_API_MODEL", d.model).strip(),
        max_tokens=max_tokens,
        temperature=_number("OCR_API_TEMPERATURE", d.temperature),
        top_p=_number("OCR_API_TOP_P", d.top_p),
        extra_body=parse_extra_body(env.get("OCR_API_EXTRA_BODY")),
        timeout=timeout,
        retries=int(_number("OCR_API_RETRIES", d.retries, integer=True)),
    )


def cache_key(s: ApiSettings) -> dict:
    """Cache key dict: what changes the output (host, model, image, sampling, extra body)."""
    return {
        "backend": BACKEND,
        "host": urllib.parse.urlsplit(s.base_url).netloc.lower(),
        "model": s.model,
        "dpi": RENDER_DPI,
        "longest_side": LONGEST_SIDE,
        "resize": RESIZE,
        "image_format": IMAGE_FORMAT,
        "prompt": PROMPT,
        "max_tokens": s.max_tokens,
        "temperature": s.temperature,
        "top_p": s.top_p,
        "extra_body": json.loads(s.extra_body) if s.extra_body else None,
        "format": CACHE_FORMAT,
    }


def data_uri(image) -> tuple[str, int]:
    """The (already resized) PIL image as a PNG base64 data URI, and the PNG size in bytes."""
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    png = buf.getvalue()
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii"), len(png)


def payload(uri: str, s: ApiSettings) -> dict:
    """The chat completions request body for one page image (OCR_API_EXTRA_BODY merged last)."""
    body = {
        "model": s.model,
        "messages": [
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": uri}}]}
        ],
        "max_tokens": s.max_tokens,
        "temperature": s.temperature,
        "top_p": s.top_p,
    }
    if s.extra_body:
        body.update(json.loads(s.extra_body))
    return body


def retry_after(value: str | None) -> float | None:
    """Seconds from a Retry-After header (delta-seconds or an HTTP date), None if absent/invalid."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _redact(text: str, key: str) -> str:
    return text.replace(key, "***") if key else text


def _request(url: str, body: bytes, key: str, s: ApiSettings) -> tuple[dict, int]:
    """POST with retries on 429, 5xx, timeouts and connection errors. (response, attempts)."""
    from json4win import llm  # lazy: llm -> trace -> ocr -> ocr_api would be an import cycle

    for attempt in range(s.retries + 1):
        delay = min(2.0 ** (attempt + 1), MAX_RETRY_DELAY)
        try:
            return llm._post(url, body, key, s.timeout), attempt + 1
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                detail = _redact(e.read()[:300].decode("utf-8", "replace"), key)
                raise OcrApiError(f"{s.model}: HTTP {e.code}: {detail}") from None
            wait = retry_after(e.headers.get("Retry-After") if e.headers else None)
            if wait is not None:
                delay = min(wait, MAX_RETRY_DELAY)
            reason = f"HTTP {e.code}"
        except (OSError, http.client.HTTPException) as e:  # timeouts, URLError, SSL, resets
            reason = type(e).__name__
        except ValueError:
            reason = "invalid JSON response"
        if attempt == s.retries:
            raise OcrApiError(f"{s.model}: {reason}, gave up after {attempt + 1} attempts")
        log.warning(
            "ocr api %s: %s, retry %d/%d in %.0fs", s.model, reason, attempt + 1, s.retries, delay
        )
        time.sleep(delay)
    raise AssertionError("unreachable")


# ---- circuit breaker: after BREAKER_FAILURES consecutive failed pages the API is skipped -------

_breaker_lock = threading.Lock()
_breaker = {"failures": 0, "open": False}


def breaker_open() -> bool:
    """True once BREAKER_FAILURES pages in a row failed in this process: skip the API."""
    with _breaker_lock:
        return _breaker["open"]


def record_result(ok: bool) -> None:
    """Count a page's API outcome; a success resets the count. Logs one WARNING on opening."""
    with _breaker_lock:
        if ok:
            _breaker["failures"] = 0
            return
        _breaker["failures"] += 1
        if _breaker["failures"] >= BREAKER_FAILURES and not _breaker["open"]:
            _breaker["open"] = True
            log.warning(
                "OCR API: %d pages in a row failed, not calling it again in this run; "
                "every further page goes to OCR_API_FALLBACK",
                BREAKER_FAILURES,
            )


def reset_breaker() -> None:
    """Close the breaker (tests; a new process starts closed)."""
    with _breaker_lock:
        _breaker.update(failures=0, open=False)


def run(image, s: ApiSettings) -> dict:
    """OCR one page image (PIL, rendered at RENDER_DPI) via the API. Raises OcrApiError."""
    key = env.get("OCR_API_KEY")
    if not key:
        raise OcrApiError("OCR_API_KEY is not set (json4win/.env.local)")
    image = ocr_lighton.resize(image)
    uri, png_bytes = data_uri(image)
    if png_bytes > MAX_IMAGE_BYTES:
        raise OcrApiError(f"page image is {png_bytes} bytes, the API limit is {MAX_IMAGE_BYTES}")
    body = json.dumps(payload(uri, s), ensure_ascii=False).encode("utf-8")
    t0 = time.perf_counter()
    data, attempts = _request(s.base_url + "/chat/completions", body, key, s)
    seconds = time.perf_counter() - t0
    from json4win import llm

    try:
        choice = data["choices"][0]
        message = choice.get("message") or {}
    except (KeyError, IndexError, TypeError, AttributeError):
        raise OcrApiError(f"{s.model}: response has no choices") from None
    raw = llm.message_text(message)
    if not raw.strip():
        raise OcrApiError(
            f"{s.model}: empty answer (finish_reason={choice.get('finish_reason')!r})"
        )
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    finish = choice.get("finish_reason")
    return {
        "raw": raw,
        "seconds": round(seconds, 2),
        "tokens": usage.get("completion_tokens"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "model_image_size": list(image.size),
        "image_bytes": png_bytes,
        "attempts": attempts,
        "finish": "stop" if finish in ("stop", "eos") else finish,
        "backend": BACKEND,
    }
