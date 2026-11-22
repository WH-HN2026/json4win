"""OCR_BACKEND=lighton_api: LightOnOCR-2-1B over an OpenAI-compatible API (fake HTTP only, P8)."""

import base64
import email.message
import io
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path

import pypdfium2
import pytest
from PIL import Image

from json4win import env, llm, ocr, ocr_api, ocr_engine, ocr_lighton, ocr_tesseract, trace

KEY = "sk-SENTINEL-ocr-key-0123456789"
RAW = "## Odwołanie\n\n**Odwołujący:** Żółw sp. z o.o.\n"
TESS_RAW = "Uzasadnienie\r\nstrona dalsza\x0c"
API_VARS = (
    "OCR_API_BASE_URL",
    "OCR_API_MODEL",
    "OCR_API_TIMEOUT",
    "OCR_API_RETRIES",
    "OCR_API_MAX_TOKENS",
    "OCR_API_TEMPERATURE",
    "OCR_API_TOP_P",
    "OCR_API_EXTRA_BODY",
    "OCR_API_FALLBACK",
)
EUROUTER_LINE = (
    'OCR_API_EXTRA_BODY={"provider": {"only": ["ionos"], "allow_fallbacks": false, '
    '"zdr": true, "max_retention_days": 0}}'
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No live call can leave a test, even with a real key in .env.local."""

    def forbid(*a, **k):
        raise AssertionError("live HTTP in a unit test")

    monkeypatch.setattr(urllib.request, "urlopen", forbid)


@pytest.fixture(autouse=True)
def breaker():
    """Each test starts (and leaves) with the circuit breaker closed."""
    ocr_api.reset_breaker()
    yield
    ocr_api.reset_breaker()


@pytest.fixture
def pdf(tmp_path) -> Path:
    doc = pypdfium2.PdfDocument.new()
    for _ in range(3):
        doc.new_page(595, 842)
    path = tmp_path / "skan ąę.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def cache(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("JSON4WIN_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("OCR_TESSDATA_DIR", str(tmp_path / "no-tessdata"))
    monkeypatch.setenv("OCR_API_KEY", KEY)
    hybrid = ("OCR_HYBRID_FIRST", "OCR_HYBRID_REST", "OCR_HYBRID_FIRST_PAGES")
    for var in ("OCR_BACKEND", "OCR_CACHE_ONLY", *API_VARS, *hybrid):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(ocr_tesseract, "tesseract_version", lambda cmd="": "tesseract 5.5.4")
    monkeypatch.setattr(ocr_api.time, "sleep", lambda s: None)
    return tmp_path / "cache"


def _ok(text: str = RAW, finish: str = "stop") -> dict:
    return {
        "choices": [{"message": {"content": text}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 340},
    }


def _http_error(code: int, retry_after: str | None = None, body: bytes = b"{}"):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("u", code, "err", headers, io.BytesIO(body))


class FakeApi:
    """llm._post replaced: answers from a script, records each request."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests: list[dict] = []

    def __call__(self, url, body, key, timeout):
        self.requests.append({"url": url, "body": json.loads(body), "key": key, "timeout": timeout})
        a = self.answers.pop(0) if self.answers else _ok()
        if isinstance(a, BaseException):
            raise a
        return a


@pytest.fixture
def api(monkeypatch) -> FakeApi:
    fake = FakeApi()
    monkeypatch.setattr(llm, "_post", fake)
    return fake


@pytest.fixture
def tess(monkeypatch) -> list:
    """Fake Tesseract (records image widths); the local engines must not run."""
    calls = []

    def run(image, s):
        calls.append(image.size[0])
        return {"raw": TESS_RAW, "seconds": 0.1, "backend": "tesseract"}

    def forbid(*a, **k):
        raise AssertionError("local OCR engine called")

    monkeypatch.setattr(ocr_tesseract, "run", run)
    monkeypatch.setattr(ocr_engine, "run", forbid)
    monkeypatch.setattr(ocr_lighton, "run", forbid)
    return calls


def _settings_dirs(cache: Path) -> list[str]:
    return sorted(p.name for p in (cache / "ocr").iterdir()) if (cache / "ocr").is_dir() else []


def test_default_backend_unchanged(cache, monkeypatch):
    assert ocr.backend_name() == "local"
    assert isinstance(ocr.active_settings(), ocr_engine.InferSettings)
    assert ocr.settings_id(ocr_engine.InferSettings()) == "0fe4b22967e4791d"
    assert ocr.settings_id(ocr_lighton.LightOnSettings()) == "13f6697c5daa30bf"


def test_request_shape(pdf, cache, api, tess, monkeypatch):
    monkeypatch.setenv("OCR_BACKEND", "LightOn_API")
    assert ocr.ocr_page(pdf, 0) == "Odwołanie\nOdwołujący: Żółw sp. z o.o."
    assert ocr.ocr_page(pdf, 0)  # cached: no second request
    assert len(api.requests) == 1 and tess == []
    r = api.requests[0]
    assert r["url"] == "https://openai.inference.de-txl.ionos.com/v1/chat/completions"
    assert r["key"] == KEY and r["timeout"] == 20.0
    body = r["body"]
    assert body["model"] == "lightonai/LightOnOCR-2-1B"
    assert body["max_tokens"] == 4096
    assert (body["temperature"], body["top_p"]) == (0.0, 1.0)
    (msg,) = body["messages"]
    assert msg["role"] == "user"
    (part,) = msg["content"]  # the image only, no text instruction
    assert part["type"] == "image_url"
    uri = part["image_url"]["url"]
    prefix = "data:image/png;base64,"
    assert uri.startswith(prefix)
    image = Image.open(io.BytesIO(base64.b64decode(uri[len(prefix) :])))
    assert image.format == "PNG" and max(image.size) == ocr_lighton.LONGEST_SIDE
    entry = json.loads(ocr.cache_path(pdf, 0).read_text(encoding="utf-8"))
    assert entry["backend"] == "lighton_api"
    assert (entry["tokens"], entry["prompt_tokens"], entry["attempts"]) == (340, 1200, 1)
    assert "seconds" in entry and entry["image_bytes"] > 0


def test_real_post_sends_bearer_json(pdf, cache, monkeypatch):
    """Through the real llm._post: POST, URL, bearer header, JSON body, timeout (urlopen faked)."""
    seen = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(req, timeout):
        seen.append((req, timeout))
        return Response(json.dumps(_ok()).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("OCR_BACKEND", "lighton_api")
    assert ocr.ocr_page(pdf, 0).startswith("Odwołanie")
    ((req, timeout),) = seen
    assert req.get_method() == "POST" and timeout == 20.0
    assert req.full_url == "https://openai.inference.de-txl.ionos.com/v1/chat/completions"
    assert req.get_header("Authorization") == f"Bearer {KEY}"
    assert req.get_header("Content-type") == "application/json"
    assert json.loads(req.data)["model"] == "lightonai/LightOnOCR-2-1B"


def test_env_overrides_and_extra_body(pdf, cache, api, tess, monkeypatch, tmp_path):
    """The documented EUrouter .env line survives env.load_env and is merged into the body."""
    dotenv = tmp_path / ".env.local"
    dotenv.write_text(EUROUTER_LINE + "\n", encoding="utf-8")
    env.load_env(dotenv)
    monkeypatch.setenv("OCR_BACKEND", "lighton_api")
    monkeypatch.setenv("OCR_API_BASE_URL", "https://api.eurouter.ai/api/v1/")
    monkeypatch.setenv("OCR_API_MODEL", "lightonocr-2-1b")
    monkeypatch.setenv("OCR_API_MAX_TOKENS", "2048")
    monkeypatch.setenv("OCR_API_TEMPERATURE", "0.2")
    monkeypatch.setenv("OCR_API_TOP_P", "0.9")
    monkeypatch.setenv("OCR_API_TIMEOUT", "30")
    ocr.ocr_page(pdf, 0)
    r = api.requests[0]
    assert r["url"] == "https://api.eurouter.ai/api/v1/chat/completions"
    assert r["timeout"] == 30.0
    b = r["body"]
    assert (b["model"], b["max_tokens"], b["temperature"], b["top_p"]) == (
        "lightonocr-2-1b",
        2048,
        0.2,
        0.9,
    )
    assert b["provider"] == {
        "only": ["ionos"],
        "allow_fallbacks": False,
        "zdr": True,
        "max_retention_days": 0,
    }


def test_extra_body_does_not_leak(cache):
    """Runs after test_env_overrides_and_extra_body: load_env's value is gone."""
    assert "OCR_API_EXTRA_BODY" not in os.environ


@pytest.mark.parametrize(
    ("var", "value", "message"),
    [
        ("OCR_API_EXTRA_BODY", "{provider: 1}", "not valid JSON"),
        ("OCR_API_EXTRA_BODY", "[1, 2]", "must be a JSON object"),
        ("OCR_API_MAX_TOKENS", "many", "must be an integer"),
        ("OCR_API_MAX_TOKENS", "0", "must be > 0"),
        ("OCR_API_TEMPERATURE", "warm", "must be a number"),
        ("OCR_API_BASE_URL", "ionos.de/v1", "http\\(s\\) URL"),
        ("OCR_API_FALLBACK", "lighton_api", "OCR_API_FALLBACK must be one of"),
        ("OCR_API_FALLBACK", "easyocr", "OCR_API_FALLBACK must be one of"),
    ],
)
def test_bad_config_fails_fast_without_fallback(var, value, message, pdf, cache, api, tess,
                                                monkeypatch):  # fmt: skip
    monkeypatch.setenv("OCR_BACKEND", "lighton_api")
    monkeypatch.setenv(var, value)
    with pytest.raises(ValueError, match=message):
        ocr.ocr_page(pdf, 0)
    assert api.requests == [] and tess == []


def test_retry_after_is_honoured(pdf, cache, api, tess, monkeypatch):
    sleeps = []
    monkeypatch.setattr(ocr_api.time, "sleep", sleeps.append)
    monkeypatch.setenv("OCR_BACKEND", "lighton_api")
    api.answers = [_http_error(502), _http_error(503, "3"), _http_error(429, "120"), _ok()]
    monkeypatch.setenv("OCR_API_RETRIES", "3")
    assert ocr.ocr_page(pdf, 0).startswith("Odwołanie")
    # no header: backoff 2 s; Retry-After 3 s; Retry-After 120 s capped at MAX_RETRY_DELAY (5 s)
    assert sleeps == [2.0, 3.0, 5.0]
    assert len(api.requests) == 4 and tess == []
    assert json.loads(ocr.cache_path(pdf, 0).read_text(encoding="utf-8"))["attempts"] == 4


@pytest.mark.parametrize(
    ("value", "want"),
    [("3", 3.0), (" 1.5 ", 1.5), ("-4", 0.0), ("Wed, 21 Oct 2015 07:28:00 GMT", 0.0),
     ("soon", None), ("", None), (None, None)],
)  # fmt: skip
def test_retry_after_parsing(value, want):
    assert ocr_api.retry_after(value) == want


@pytest.mark.parametrize(
    "failure",
    [
        [_http_error(503)] * 2,  # retries exhausted (default 1 retry = 2 attempts)
        [TimeoutError("timed out")] * 2,
        [_http_error(400, body=f"bad key {KEY}".encode())],  # 4xx: no retry
        [{"error": "no choices"}],
        [_ok("")],  # an empty 200 answer is a failure, not an empty page
        [_ok(" \n\t ", finish="length")],
    ],
    ids=["503", "timeout", "400", "no-choices", "empty", "whitespace"],
)
def test_api_failure_falls_back_to_tesseract(failure, pdf, cache, api, tess, monkeypatch, caplog):
    monkeypatch.setenv("OCR_BACKEND", "lighton_api")
    api.answers = list(failure)
    with caplog.at_level(logging.INFO):
        assert ocr.ocr_page(pdf, 0) == "Uzasadnienie\nstrona dalsza"
    assert len(api.requests) == len(failure)
    assert tess == [ocr.render_page(pdf, 0, dpi=300).size[0]]  # tesseract renders at its own dpi
    assert ocr.used_backend(pdf, 0) == "tesseract" and ocr.page_backend(0) == "lighton_api"
    assert "reading it with tesseract" in caplog.text
    assert KEY not in caplog.text
    # the fallback text is cached under tesseract's settings id, never under the API's
    assert not ocr.is_cached(pdf, 0)
    tess_settings = ocr_tesseract.settings_from_env()
    assert ocr.is_cached(pdf, 0, tess_settings)
    assert _settings_dirs(cache) == [ocr.settings_id(tess_settings)]


def test_missing_key_falls_back(pdf, cache, api, tess, monkeypatch, caplog):
    monkeypatch.setenv("OCR_BACKEND", "lighton_api")
    monkeypatch.delenv("OCR_API_KEY")
    assert ocr.ocr_page(pdf, 0) == "Uzasadnienie\nstrona dalsza"
    assert api.requests == []
    assert "OCR_API_KEY is not set" in caplog.text


def test_fallback_none_raises(pdf, cache, api, tess, monkeypatch):
    monkeypatch.setenv("OCR_BACKEND", "lighton_api")
    monkeypatch.setenv("OCR_API_FALLBACK", "none")
    api.answers = [_http_error(401, body=f"invalid {KEY}".encode())]
    with pytest.raises(RuntimeError, match="HTTP 401") as e:
        ocr.ocr_page(pdf, 0)
    assert KEY not in str(e.value)
    assert tess == []


def test_cache_only_miss_does_not_fall_back(pdf, cache, api, tess, monkeypatch):
    monkeypatch.setenv("OCR_BACKEND", "lighton_api")
    monkeypatch.setenv("OCR_CACHE_ONLY", "1")
    with pytest.raises(ocr.OcrCacheMiss, match=ocr.settings_id(ocr_api.settings_from_env())):
        ocr.ocr_page(pdf, 0)
    assert api.requests == [] and tess == []


def test_cache_key_separation(cache, monkeypatch):
    base = ocr_api.ApiSettings()
    ids = {
        ocr.settings_id(s)
        for s in (
            base,
            ocr_api.ApiSettings(base_url="https://api.eurouter.ai/api/v1"),
            ocr_api.ApiSettings(model="lightonocr-2-1b"),
            ocr_api.ApiSettings(max_tokens=2048),
            ocr_api.ApiSettings(temperature=0.2),
            ocr_api.ApiSettings(top_p=0.9),
            ocr_api.ApiSettings(extra_body=ocr_api.parse_extra_body('{"provider": {"zdr": true}}')),
            ocr_lighton.LightOnSettings(),
            ocr_tesseract.settings_from_env(),
            ocr_engine.InferSettings(),
        )
    }
    assert len(ids) == 10
    # timeout and retries don't change the output: same cache
    same = ocr_api.ApiSettings(timeout=5, retries=0)
    assert ocr.settings_id(same) == ocr.settings_id(base)
    # extra body: key order does not matter
    a = ocr_api.parse_extra_body('{"a": 1, "b": {"y": 2, "x": 1}}')
    b = ocr_api.parse_extra_body('{"b": {"x": 1, "y": 2}, "a": 1}')
    assert a == b
    key = ocr.settings_key(base)
    assert key["host"] == "openai.inference.de-txl.ionos.com"
    assert KEY not in json.dumps(key)


def test_hybrid_api_first_page_tesseract_rest(pdf, cache, api, tess, monkeypatch, tmp_path):
    monkeypatch.setenv("OCR_BACKEND", "hybrid")
    monkeypatch.setenv("OCR_HYBRID_FIRST", "lighton_api")
    tpath = tmp_path / "traces" / "skan.trace.json"
    with trace.document(pdf, tpath, "sprawa/skan.pdf"):
        texts = [trace.ocr_page(pdf, i) for i in range(3)]
    assert texts[0].startswith("Odwołanie")
    assert texts[1] == texts[2] == "Uzasadnienie\nstrona dalsza"
    assert len(api.requests) == 1 and len(tess) == 2
    pages = json.loads(tpath.read_text(encoding="utf-8"))["ocr_pages"]
    assert [(p["page"], p["backend"]) for p in pages] == [
        (1, "lighton_api"),
        (2, "tesseract"),
        (3, "tesseract"),
    ]
    assert all("fallback_from" not in p for p in pages)


def test_hybrid_fallback_recorded_in_trace(pdf, cache, api, tess, monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("OCR_BACKEND", "hybrid")
    monkeypatch.setenv("OCR_HYBRID_FIRST", "lighton_api")
    api.answers = [_http_error(500)] * 2
    tpath = tmp_path / "traces" / "skan.trace.json"
    with caplog.at_level(logging.DEBUG), trace.document(pdf, tpath, "sprawa/skan.pdf"):
        for i in range(2):
            trace.ocr_page(pdf, i)
    pages = json.loads(tpath.read_text(encoding="utf-8"))["ocr_pages"]
    assert pages[0]["backend"] == "tesseract" and pages[0]["fallback_from"] == "lighton_api"
    assert pages[1]["backend"] == "tesseract" and "fallback_from" not in pages[1]
    md = tpath.with_name("skan.trace.md").read_text(encoding="utf-8")
    assert "tesseract zamiast lighton_api" in md
    blobs = [tpath.read_text(encoding="utf-8"), md, caplog.text]
    for path in (cache / "ocr").rglob("*.json"):
        blobs.append(path.read_text(encoding="utf-8"))
    assert all(KEY not in b for b in blobs)


def test_key_never_in_cache_or_logs(pdf, cache, api, tess, monkeypatch, caplog):
    monkeypatch.setenv("OCR_BACKEND", "lighton_api")
    api.answers = [_http_error(503, "1"), _ok()]
    with caplog.at_level(logging.DEBUG):
        ocr.ocr_page(pdf, 0)
    assert KEY not in caplog.text
    for path in (cache / "ocr").rglob("*.json"):
        assert KEY not in path.read_text(encoding="utf-8")


def _pdfs(tmp_path, n: int, start: int = 0) -> list[Path]:
    out = []
    for i in range(start, start + n):
        doc = pypdfium2.PdfDocument.new()
        doc.new_page(595 + i, 842)  # different bytes: a different cache entry per PDF
        path = tmp_path / f"dok {i}.pdf"
        doc.save(path)
        doc.close()
        out.append(path)
    return out


def test_circuit_breaker_opens_after_three_failed_pages(cache, api, tess, monkeypatch, caplog,
                                                        tmp_path):  # fmt: skip
    monkeypatch.setenv("OCR_BACKEND", "lighton_api")
    pdfs = _pdfs(tmp_path, 6)
    # page 1 fails, page 2 succeeds (resets the count), pages 3-5 fail -> open; page 6 skips the API
    api.answers = (
        [_http_error(503)] * 2
        + [_ok()]
        + [_http_error(503)] * 2
        + [TimeoutError("t")] * 2
        + [_ok("")]
    )
    with caplog.at_level(logging.INFO):
        texts = [ocr.ocr_page(p, 0) for p in pdfs]
    assert [ocr.used_backend(p, 0) for p in pdfs] == ["tesseract", "lighton_api"] + [
        "tesseract"
    ] * 4
    assert texts[1].startswith("Odwołanie") and texts[5] == "Uzasadnienie\nstrona dalsza"
    assert len(api.requests) == 2 + 1 + 2 + 2 + 1  # nothing for page 6
    assert ocr_api.breaker_open()
    opened = [r for r in caplog.records if "not calling it again" in r.getMessage()]
    assert len(opened) == 1 and opened[0].levelno == logging.WARNING
    assert "API off, reading it with tesseract" in caplog.text
    # a later page of any PDF goes straight to the fallback, even a fresh one
    (extra,) = _pdfs(tmp_path, 1, start=6)
    ocr.ocr_page(extra, 0)
    assert len(api.requests) == 8 and len(opened) == 1


def test_open_breaker_with_fallback_none_raises_without_calling(pdf, cache, api, tess,
                                                                 monkeypatch):  # fmt: skip
    monkeypatch.setenv("OCR_BACKEND", "lighton_api")
    monkeypatch.setenv("OCR_API_FALLBACK", "none")
    for _ in range(ocr_api.BREAKER_FAILURES):
        ocr_api.record_result(ok=False)
    with pytest.raises(RuntimeError, match="disabled after 3 consecutive failures"):
        ocr.ocr_page(pdf, 0)
    assert api.requests == [] and tess == []


def test_hanging_endpoint_bounded_per_page(pdf, cache, tess, monkeypatch):
    """Every request hangs until its timeout: the page fails over within ~45 s (fake clock)."""
    clock = [0.0]
    timeouts = []

    def urlopen(req, timeout):
        timeouts.append(timeout)
        clock[0] += timeout
        raise TimeoutError("timed out")

    def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(ocr_api.time, "sleep", sleep)
    monkeypatch.setenv("OCR_BACKEND", "lighton_api")
    assert ocr.ocr_page(pdf, 0) == "Uzasadnienie\nstrona dalsza"
    assert timeouts == [20.0, 20.0]
    assert clock[0] <= ocr_api.worst_case_seconds(ocr_api.ApiSettings()) == 45.0

    # 503 with a long Retry-After right after a slow (near-timeout) answer: still <= 45 s
    clock[0] = 0.0

    def slow_503(req, timeout):
        clock[0] += timeout
        raise _http_error(503, "600")

    monkeypatch.setattr(urllib.request, "urlopen", slow_503)
    ocr.ocr_page(pdf, 1)
    assert clock[0] <= 45.0
