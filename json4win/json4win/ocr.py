"""Page OCR with the local Unlimited-OCR-2 model on CPU (architecture D10, docs/ocr.md).

The pipeline never uses the PDF text layer: every page it reads comes from here. Pages are rendered
with pypdfium2 and read by the model (json4win.ocr_engine). The raw model output is cached in
json4win.env.cache_dir()/ocr, keyed by the PDF's sha256, the page index, the model revision and the
render/infer settings; it is cleaned to plain text on read, so changing the cleaner never needs a
re-OCR. With OCR_CACHE_ONLY=1 a cache miss raises OcrCacheMiss instead of running the model.
"""

import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import asdict
from pathlib import Path

from json4win import env
from json4win.ocr_engine import MODEL_ID, MODEL_REVISION, PROMPT, InferSettings

log = logging.getLogger(__name__)

RENDER_DPI = 200  # the model resizes to 640px tiles / a 1024px view; 200 dpi A4 is above both
CACHE_FORMAT = 1  # bump when the cached raw output would change for the same settings


class OcrCacheMiss(RuntimeError):
    """OCR_CACHE_ONLY=1 and the page is not in the cache."""


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
    return clean_text(ocr_page_raw(pdf, index))


# ---- settings and cache ------------------------------------------------------------------------


def infer_settings() -> InferSettings:
    """Inference settings from env (OCR_MODE, OCR_MAX_TOKENS, OCR_DTYPE, OCR_FAST_DECODE)."""
    d = InferSettings()
    return InferSettings(
        mode=env.get("OCR_MODE", d.mode),
        max_tokens=int(env.get("OCR_MAX_TOKENS", str(d.max_tokens))),
        dtype=env.get("OCR_DTYPE", d.dtype),
        fast_decode=int(env.get("OCR_FAST_DECODE", str(d.fast_decode))),
        ngram=d.ngram,
        ngram_window=d.ngram_window,
    )


def settings_key(s: InferSettings, dpi: int = RENDER_DPI) -> dict:
    return {
        "model": MODEL_ID,
        "revision": MODEL_REVISION,
        "prompt": PROMPT,
        "dpi": dpi,
        "format": CACHE_FORMAT,
        **asdict(s),
    }


def settings_id(s: InferSettings, dpi: int = RENDER_DPI) -> str:
    blob = json.dumps(settings_key(s, dpi), sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


_sha_memo: dict[tuple, str] = {}


def pdf_sha256(pdf: Path) -> str:
    st = pdf.stat()
    memo_key = (str(pdf.resolve()), st.st_size, st.st_mtime_ns)
    if memo_key not in _sha_memo:
        _sha_memo[memo_key] = hashlib.sha256(pdf.read_bytes()).hexdigest()
    return _sha_memo[memo_key]


def cache_path(pdf: Path, index: int, s: InferSettings | None = None) -> Path:
    s = s or infer_settings()
    return env.cache_dir() / "ocr" / settings_id(s) / pdf_sha256(pdf) / f"{index:04d}.json"


def is_cached(pdf: Path, index: int, s: InferSettings | None = None) -> bool:
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


def _write_settings_file(s: InferSettings) -> None:
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


def ocr_page_entry(pdf: Path, index: int, s: InferSettings | None = None) -> dict:
    """The cache entry of one page (raw text + stats), running the model on a miss."""
    s = s or infer_settings()
    path = cache_path(pdf, index, s)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    if env.get("OCR_CACHE_ONLY") == "1":
        raise OcrCacheMiss(f"{pdf.name} page {index + 1}: not in the OCR cache ({path})")

    from json4win import ocr_engine

    image = render_page(pdf, index)
    log.info("OCR %s page %d ...", pdf.name, index + 1)
    try:
        result = ocr_engine.run(image, s)
    except Exception as e:
        raise RuntimeError(f"OCR {pdf.name} page {index + 1}: {e}") from e
    if result["finish"] != "stop":
        log.warning("OCR %s page %d: output cut at %d tokens", pdf.name, index + 1, s.max_tokens)
    log.info(
        "OCR %s page %d: %.1fs, %d tokens", pdf.name, index + 1, result["seconds"], result["tokens"]
    )
    entry = {"pdf_sha256": pdf_sha256(pdf), "page": index, "image_size": list(image.size), **result}
    _write_settings_file(s)
    _write_atomic(path, entry)
    return entry


def ocr_page_raw(pdf: Path, index: int) -> str:
    """Raw model output of one page (layout tags included), cached."""
    return ocr_page_entry(pdf, index)["raw"]


# ---- raw model output -> plain text ------------------------------------------------------------

# <BLOCK>text[92, 712, 890, 778]<FORK>  /  <BLOCK>title<LEVEL2>[186, 241, 300, 257]<FORK>
_BLOCK = re.compile(r"<BLOCK>[^<\[\n]*(?:<LEVEL\d+>)?(?:\[[\d,\s]*\])?<FORK>")
_LINK = re.compile(r"!?\[([^\]\n]*)\]\([^)\n]*\)")  # [label](mailto:x) -> label; ![](img) -> ""
_HTML_CELL = re.compile(r"</t[dh]>\s*<t[dh][^>]*>", re.IGNORECASE)
_HTML_ROW = re.compile(r"</?(?:tr|table|thead|tbody)[^>]*>", re.IGNORECASE)
_HTML_TAG = re.compile(r"</?(?:td|th|br|p|div|span|b|i|u|sup|sub)\b[^>]*>", re.IGNORECASE)
_SPECIAL = re.compile(r"<(?:PAGE|FORK|BLOCK|LEVEL\d+|\|[^>]*\|)>")


def clean_text(raw: str) -> str:
    """Plain text from the model's layout markup: one block per paragraph, link labels kept."""
    t = _BLOCK.sub("\n", raw)
    t = _SPECIAL.sub("\n", t)
    t = _LINK.sub(r"\1", t)
    t = _HTML_CELL.sub(" | ", t)
    t = _HTML_ROW.sub("\n", t)
    t = _HTML_TAG.sub(" ", t)
    t = t.replace("**", "").replace("__", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in t.splitlines()]
    return re.sub(r"\n{2,}", "\n", "\n".join(lines)).strip()
