"""Page OCR dispatcher over the shared cache (architecture D10, docs/ocr.md).

The pipeline never uses the PDF text layer: every page it reads comes from here. Pages are rendered
with pypdfium2 and passed to the backend selected by `OCR_BACKEND`:
- `local` (default): Unlimited-OCR-2 on CPU (`json4win.ocr_engine`);
- `tesseract`: Tesseract CLI via subprocess (`json4win.ocr_tesseract`);
- `lighton`: LightOnOCR-2-1B on CPU (`json4win.ocr_lighton`), benchmark-only: needs transformers 5
  (`.venv-lighton`); its cache can be read from any venv with OCR_CACHE_ONLY=1;
- `lighton_api`: LightOnOCR-2-1B through an EU/EEA OpenAI-compatible API (`json4win.ocr_api`,
  task P8); a page whose API call fails is read by OCR_API_FALLBACK (default `tesseract`);
- `hybrid`: the first OCR_HYBRID_FIRST_PAGES pages (default 1) by OCR_HYBRID_FIRST (default
  `lighton`), the rest by OCR_HYBRID_REST (default `tesseract`). Each page uses that backend's own
  settings and cache, so a hybrid run reads the entries written by single-backend runs (task P7).

The raw backend output is cached in `json4win.env.cache_dir()/ocr/<settings_id>/<sha256>/`
and cleaned to plain text on read. With `OCR_CACHE_ONLY=1` a cache miss raises `OcrCacheMiss`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import replace
from pathlib import Path

from json4win import env, ocr_api, ocr_engine, ocr_lighton, ocr_tesseract
from json4win.ocr_api import ApiSettings
from json4win.ocr_engine import InferSettings
from json4win.ocr_lighton import LightOnSettings
from json4win.ocr_tesseract import TesseractSettings

log = logging.getLogger(__name__)

RENDER_DPI = ocr_engine.RENDER_DPI
CACHE_FORMAT = ocr_engine.CACHE_FORMAT
BACKENDS = (ocr_engine.BACKEND, ocr_tesseract.BACKEND, ocr_lighton.BACKEND, ocr_api.BACKEND)
HYBRID = "hybrid"
HYBRID_DEFAULTS = {"first": ocr_lighton.BACKEND, "rest": ocr_tesseract.BACKEND, "first_pages": 1}

OcrSettings = InferSettings | TesseractSettings | LightOnSettings | ApiSettings
NO_FALLBACK = "none"


class OcrCacheMiss(RuntimeError):
    """OCR_CACHE_ONLY=1 and the page is not in the cache."""


def backend_name() -> str:
    """OCR_BACKEND: 'local' (default), 'tesseract', 'lighton', 'lighton_api' or 'hybrid'."""
    name = env.get("OCR_BACKEND", ocr_engine.BACKEND).strip().lower()
    if name not in (*BACKENDS, HYBRID):
        expected = ", ".join((*BACKENDS, HYBRID))
        raise ValueError(f"unknown OCR_BACKEND {name!r}; expected one of: {expected}")
    return name


def hybrid_plan() -> tuple[str, str, int]:
    """(first backend, rest backend, first pages) from OCR_HYBRID_FIRST/_REST/_FIRST_PAGES."""
    d = HYBRID_DEFAULTS
    first = env.get("OCR_HYBRID_FIRST", d["first"]).strip().lower()
    rest = env.get("OCR_HYBRID_REST", d["rest"]).strip().lower()
    for var, name in (("OCR_HYBRID_FIRST", first), ("OCR_HYBRID_REST", rest)):
        if name not in BACKENDS:
            raise ValueError(f"{var} must be one of {', '.join(BACKENDS)}, got {name!r}")
    raw = env.get("OCR_HYBRID_FIRST_PAGES", str(d["first_pages"]))
    try:
        n = int(raw)
    except ValueError as e:
        raise ValueError(f"OCR_HYBRID_FIRST_PAGES must be an integer, got {raw!r}") from e
    if n < 1:
        raise ValueError(f"OCR_HYBRID_FIRST_PAGES must be >= 1, got {n}")
    return first, rest, n


def page_backend(index: int) -> str:
    """The backend that reads page `index` (0-based); in hybrid mode it depends on the page."""
    name = backend_name()
    if name != HYBRID:
        return name
    first, rest, n = hybrid_plan()
    return first if index < n else rest


def fallback_name() -> str:
    """OCR_API_FALLBACK: the backend that reads a page when the OCR API fails, or 'none'."""
    name = env.get("OCR_API_FALLBACK", ocr_tesseract.BACKEND).strip().lower()
    allowed = tuple(b for b in BACKENDS if b != ocr_api.BACKEND)
    if name not in (*allowed, NO_FALLBACK):
        expected = ", ".join((*allowed, NO_FALLBACK))
        raise ValueError(f"OCR_API_FALLBACK must be one of {expected}, got {name!r}")
    return name


_used: dict[tuple[str, int], str] = {}


def used_backend(pdf: Path, index: int) -> str:
    """The backend that actually read page `index` of `pdf` in this process (the fallback, when
    the OCR API failed); page_backend(index) if the page was not read through ocr_page()."""
    return _used.get((str(pdf), index)) or page_backend(index)


def page_count(pdf: Path) -> int:
    """Number of pages in the PDF."""
    import pypdfium2

    doc = pypdfium2.PdfDocument(pdf)
    try:
        return len(doc)
    finally:
        doc.close()


def ocr_page(pdf: Path, index: int) -> str:
    """Plain text of page `index` (0-based) of `pdf`, read by OCR (cached), diacritics kept."""
    entry, s = _entry(pdf, index, active_settings(index))
    _used[(str(pdf), index)] = backend_of(s)
    if isinstance(s, TesseractSettings):
        return ocr_tesseract.clean_text(entry["raw"])
    if isinstance(s, LightOnSettings | ApiSettings):  # same model, same markdown output
        return ocr_lighton.clean_text(entry["raw"])
    return clean_text(entry["raw"])


# ---- settings and cache ------------------------------------------------------------------------


def infer_settings() -> InferSettings:
    """Local model settings from env (OCR_MODE, OCR_MAX_TOKENS, OCR_DTYPE, OCR_FAST_DECODE)."""
    return ocr_engine.settings_from_env()


def active_settings(index: int | None = None) -> OcrSettings:
    """Settings of the backend that reads page `index` (OCR_BACKEND=hybrid needs the index)."""
    if index is None:
        name = backend_name()
        if name == HYBRID:
            raise ValueError("OCR_BACKEND=hybrid: settings depend on the page, pass its index")
    else:
        name = page_backend(index)
    return _settings_of(name)


def _settings_of(name: str) -> OcrSettings:
    """Settings of one named (non-hybrid) backend from env."""
    if name == ocr_tesseract.BACKEND:
        return ocr_tesseract.settings_from_env()
    if name == ocr_lighton.BACKEND:
        return ocr_lighton.settings_from_env()
    if name == ocr_api.BACKEND:
        return ocr_api.settings_from_env()
    return ocr_engine.settings_from_env()


def backend_of(s: OcrSettings) -> str:
    """The backend name of a settings object."""
    if isinstance(s, TesseractSettings):
        return ocr_tesseract.BACKEND
    if isinstance(s, LightOnSettings):
        return ocr_lighton.BACKEND
    if isinstance(s, ApiSettings):
        return ocr_api.BACKEND
    return ocr_engine.BACKEND


def _render_dpi(s: OcrSettings) -> int:
    if isinstance(s, TesseractSettings):
        return s.dpi
    if isinstance(s, LightOnSettings):
        return ocr_lighton.RENDER_DPI
    if isinstance(s, ApiSettings):
        return ocr_api.RENDER_DPI
    return RENDER_DPI


def settings_key(s: OcrSettings | None = None, dpi: int | None = None) -> dict:
    s = active_settings() if s is None else s
    if isinstance(s, InferSettings):
        return ocr_engine.cache_key(s, dpi=RENDER_DPI if dpi is None else dpi)
    if isinstance(s, TesseractSettings):
        if dpi is not None and dpi != s.dpi:
            s = replace(s, dpi=dpi)
        return ocr_tesseract.cache_key(s)
    if isinstance(s, LightOnSettings):
        return ocr_lighton.cache_key(s)
    if isinstance(s, ApiSettings):
        return ocr_api.cache_key(s)
    raise TypeError(f"unsupported OCR settings type: {type(s).__name__}")


def settings_id(s: OcrSettings | None = None, dpi: int | None = None) -> str:
    blob = json.dumps(settings_key(s, dpi), sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


_sha_memo: dict[tuple, str] = {}


def pdf_sha256(pdf: Path) -> str:
    st = pdf.stat()
    memo_key = (str(pdf.resolve()), st.st_size, st.st_mtime_ns)
    if memo_key not in _sha_memo:
        _sha_memo[memo_key] = hashlib.sha256(pdf.read_bytes()).hexdigest()
    return _sha_memo[memo_key]


def cache_path(pdf: Path, index: int, s: OcrSettings | None = None) -> Path:
    s = active_settings(index) if s is None else s
    return env.cache_dir() / "ocr" / settings_id(s) / pdf_sha256(pdf) / f"{index:04d}.json"


def is_cached(pdf: Path, index: int, s: OcrSettings | None = None) -> bool:
    return cache_path(pdf, index, s).is_file()


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _write_settings_file(s: OcrSettings) -> None:
    f = env.cache_dir() / "ocr" / settings_id(s) / "settings.json"
    if not f.is_file():
        _write_atomic(f, settings_key(s))


def render_page(pdf: Path, index: int, dpi: int = RENDER_DPI):
    """Page `index` of `pdf` as an RGB PIL image."""
    import pypdfium2

    doc = pypdfium2.PdfDocument(pdf)
    try:
        if not 0 <= index < len(doc):
            raise IndexError(f"{pdf.name}: page {index} out of range (0..{len(doc) - 1})")
        page = doc[index]
        try:
            return page.render(scale=dpi / 72).to_pil().convert("RGB")
        finally:
            page.close()
    finally:
        doc.close()


def ocr_page_entry(pdf: Path, index: int, s: OcrSettings | None = None) -> dict:
    """The cache entry of one page (raw text + stats), running the backend on a miss."""
    return _entry(pdf, index, active_settings(index) if s is None else s)[0]


def _entry(pdf: Path, index: int, s: OcrSettings) -> tuple[dict, OcrSettings]:
    """(cache entry, settings of the backend that produced it). An OCR API failure falls back to
    OCR_API_FALLBACK for that page: the fallback reads it with its own settings and cache, so no
    fallback text is ever stored under the API's settings id (the next run tries the API again)."""
    path = cache_path(pdf, index, s)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8")), s
    if env.get("OCR_CACHE_ONLY") == "1":
        raise OcrCacheMiss(f"{pdf.name} page {index + 1}: not in the OCR cache ({path})")

    fallback = fallback_name() if isinstance(s, ApiSettings) else NO_FALLBACK  # config errors raise
    if isinstance(s, ApiSettings) and ocr_api.breaker_open():
        if fallback == NO_FALLBACK:
            raise RuntimeError(
                f"OCR {pdf.name} page {index + 1}: OCR API disabled after "
                f"{ocr_api.BREAKER_FAILURES} consecutive failures (OCR_API_FALLBACK=none)"
            )
        log.info("OCR [%s] %s page %d: API off, reading it with %s", ocr_api.BACKEND,
                 pdf.name, index + 1, fallback)  # fmt: skip
        return _entry(pdf, index, _settings_of(fallback))
    image = render_page(pdf, index, dpi=_render_dpi(s))
    if isinstance(s, TesseractSettings):
        log.info("OCR [tesseract] %s page %d ...", pdf.name, index + 1)
        try:
            result = ocr_tesseract.run(image, s)
        except Exception as e:
            raise RuntimeError(f"OCR {pdf.name} page {index + 1}: {e}") from e
        log.info(
            "OCR [tesseract] %s page %d: %.2fs, %d chars",
            pdf.name,
            index + 1,
            result["seconds"],
            len(result["raw"]),
        )
    else:
        engine = {LightOnSettings: ocr_lighton, ApiSettings: ocr_api}.get(type(s), ocr_engine)
        tag = "OCR" if engine is ocr_engine else f"OCR [{backend_of(s)}]"
        log.info("%s %s page %d ...", tag, pdf.name, index + 1)
        try:
            result = engine.run(image, s)
        except ocr_api.OcrApiError as e:
            ocr_api.record_result(ok=False)
            if fallback == NO_FALLBACK:
                raise RuntimeError(f"OCR {pdf.name} page {index + 1}: {e}") from e
            log.warning(
                "OCR [%s] %s page %d failed (%s); reading it with %s",
                ocr_api.BACKEND,
                pdf.name,
                index + 1,
                e,
                fallback,
            )
            return _entry(pdf, index, _settings_of(fallback))
        except Exception as e:
            raise RuntimeError(f"OCR {pdf.name} page {index + 1}: {e}") from e
        if engine is ocr_api:
            ocr_api.record_result(ok=True)
        if result["finish"] != "stop":
            log.warning(
                "OCR %s page %d: output cut at %d tokens", pdf.name, index + 1, s.max_tokens
            )
        log.info(
            "%s %s page %d: %.1fs, %s tokens",
            tag,
            pdf.name,
            index + 1,
            result["seconds"],
            result["tokens"],
        )

    entry = {"pdf_sha256": pdf_sha256(pdf), "page": index, "image_size": list(image.size), **result}
    _write_settings_file(s)
    _write_atomic(path, entry)
    return entry, s


def ocr_page_raw(pdf: Path, index: int) -> str:
    """Raw backend output of one page, cached."""
    return ocr_page_entry(pdf, index)["raw"]


# ---- raw local-model output -> plain text ------------------------------------------------------

# <BLOCK>text[92, 712, 890, 778]<FORK>  /  <BLOCK>title<LEVEL2>[186, 241, 300, 257]<FORK>
_BLOCK = re.compile(r"<BLOCK>[^<\[\n]*(?:<LEVEL\d+>)?(?:\[[\d,\s]*\])?<FORK>")
_LINK = re.compile(r"!?\[([^\]\n]*)\]\([^)\n]*\)")  # [label](mailto:x) -> label; ![](img) -> ""
_HTML_CELL = re.compile(r"</t[dh]>\s*<t[dh][^>]*>", re.IGNORECASE)
_HTML_ROW = re.compile(r"</?(?:tr|table|thead|tbody)[^>]*>", re.IGNORECASE)
_HTML_TAG = re.compile(r"</?(?:td|th|br|p|div|span|b|i|u|sup|sub)\b[^>]*>", re.IGNORECASE)
_SPECIAL = re.compile(r"<(?:PAGE|FORK|BLOCK|LEVEL\d+|\|[^>]*\|)>")


def clean_text(raw: str) -> str:
    """Plain text from the local model's layout markup: one block per line, link labels kept."""
    t = _BLOCK.sub("\n", raw)
    t = _SPECIAL.sub("\n", t)
    t = _LINK.sub(r"\1", t)
    t = _HTML_CELL.sub(" | ", t)
    t = _HTML_ROW.sub("\n", t)
    t = _HTML_TAG.sub(" ", t)
    t = t.replace("**", "").replace("__", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in t.splitlines()]
    return re.sub(r"\n{2,}", "\n", "\n".join(lines)).strip()
