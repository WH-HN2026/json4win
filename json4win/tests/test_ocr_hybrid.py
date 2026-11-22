"""OCR_BACKEND=hybrid: first page(s) by one backend, the rest by another (faked engines, P7)."""

import json
from pathlib import Path

import pypdfium2
import pytest

from json4win import ocr, ocr_engine, ocr_lighton, ocr_tesseract, trace

LIGHTON_RAW = "## Odwołanie\n\n**Odwołujący:** Żółw sp. z o.o.\n"
TESS_RAW = "Uzasadnienie\r\nstrona dalsza\x0c"
LOCAL_RAW = "<BLOCK>text[1, 2, 3, 4]<FORK>Strona lokalna"
HYBRID_VARS = ("OCR_HYBRID_FIRST", "OCR_HYBRID_REST", "OCR_HYBRID_FIRST_PAGES")


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
    for var in ("OCR_BACKEND", "OCR_CACHE_ONLY", *HYBRID_VARS):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(ocr_tesseract, "tesseract_version", lambda cmd="": "tesseract 5.5.4")
    return tmp_path / "cache"


@pytest.fixture
def engines(monkeypatch) -> list[tuple[str, int]]:
    """Fake run() of all three engines; records (backend, image width) per call."""
    calls: list[tuple[str, int]] = []

    def fake(name: str, raw: str):
        def run(image, s):
            calls.append((name, image.size[0]))
            return {"raw": raw, "seconds": 0.1, "tokens": 5, "prompt_tokens": 1,
                    "finish": "stop", "backend": name}  # fmt: skip

        return run

    monkeypatch.setattr(ocr_lighton, "run", fake("lighton", LIGHTON_RAW))
    monkeypatch.setattr(ocr_tesseract, "run", fake("tesseract", TESS_RAW))
    monkeypatch.setattr(ocr_engine, "run", fake("local", LOCAL_RAW))
    return calls


def _settings_dirs(cache: Path) -> list[str]:
    return sorted(p.name for p in (cache / "ocr").iterdir()) if (cache / "ocr").is_dir() else []


@pytest.mark.parametrize("backend", [None, "local", "tesseract", "lighton"])
def test_non_hybrid_calls_only_the_configured_backend(backend, pdf, cache, engines, monkeypatch):
    """Default path unchanged: OCR_HYBRID_* are ignored (even invalid) unless OCR_BACKEND=hybrid."""
    if backend:
        monkeypatch.setenv("OCR_BACKEND", backend)
    for var in HYBRID_VARS:
        monkeypatch.setenv(var, "garbage")
    want = backend or "local"
    for i in range(3):
        ocr.ocr_page(pdf, i)
        assert ocr.page_backend(i) == want
    assert {name for name, _ in engines} == {want}
    assert len(engines) == 3
    assert _settings_dirs(cache) == [ocr.settings_id(ocr.active_settings())]


def test_frozen_settings_ids_unchanged(cache):
    assert ocr.settings_id(ocr_engine.InferSettings()) == "0fe4b22967e4791d"
    assert ocr.settings_id(ocr_lighton.LightOnSettings()) == "13f6697c5daa30bf"


def test_hybrid_reads_first_page_with_lighton_rest_with_tesseract(pdf, cache, engines, monkeypatch):
    monkeypatch.setenv("OCR_BACKEND", "Hybrid")
    assert ocr.backend_name() == "hybrid"
    texts = [ocr.ocr_page(pdf, i) for i in range(3)]
    assert texts[0] == "Odwołanie\nOdwołujący: Żółw sp. z o.o."  # ocr_lighton.clean_text
    assert texts[1] == texts[2] == "Uzasadnienie\nstrona dalsza"  # ocr_tesseract.clean_text
    # each backend renders at its own dpi: lighton 200, tesseract 300
    w200, w300 = (ocr.render_page(pdf, 0, dpi=d).size[0] for d in (200, 300))
    assert engines == [("lighton", w200), ("tesseract", w300), ("tesseract", w300)]
    assert [ocr.page_backend(i) for i in range(3)] == ["lighton", "tesseract", "tesseract"]
    with pytest.raises(ValueError, match="pass its index"):
        ocr.active_settings()


def test_hybrid_reuses_single_backend_caches(pdf, cache, engines, monkeypatch):
    """Entries written by OCR_BACKEND=lighton / tesseract runs are hit; no new cache namespace."""
    monkeypatch.setenv("OCR_BACKEND", "lighton")
    lighton_path = ocr.cache_path(pdf, 0)
    ocr.ocr_page(pdf, 0)
    monkeypatch.setenv("OCR_BACKEND", "tesseract")
    tess_paths = [ocr.cache_path(pdf, i) for i in (1, 2)]
    for i in (1, 2):
        ocr.ocr_page(pdf, i)
    before = _settings_dirs(cache)
    assert len(before) == 2
    engines.clear()

    monkeypatch.setenv("OCR_BACKEND", "hybrid")
    monkeypatch.setenv("OCR_CACHE_ONLY", "1")
    assert ocr.cache_path(pdf, 0) == lighton_path
    assert [ocr.cache_path(pdf, i) for i in (1, 2)] == tess_paths
    assert all(ocr.is_cached(pdf, i) for i in range(3))
    assert ocr.ocr_page(pdf, 0).startswith("Odwołanie")
    assert ocr.ocr_page(pdf, 2) == "Uzasadnienie\nstrona dalsza"
    assert engines == []
    assert _settings_dirs(cache) == before


def test_hybrid_cache_miss_names_the_page_backend(pdf, cache, engines, monkeypatch):
    monkeypatch.setenv("OCR_BACKEND", "lighton")
    ocr.ocr_page(pdf, 0)
    monkeypatch.setenv("OCR_BACKEND", "hybrid")
    monkeypatch.setenv("OCR_CACHE_ONLY", "1")
    tess_id = ocr.settings_id(ocr_tesseract.settings_from_env())
    assert ocr.ocr_page(pdf, 0)
    with pytest.raises(ocr.OcrCacheMiss, match=tess_id):
        ocr.ocr_page(pdf, 1)


def test_hybrid_plan_from_env(pdf, cache, engines, monkeypatch):
    monkeypatch.setenv("OCR_BACKEND", "hybrid")
    assert ocr.hybrid_plan() == ("lighton", "tesseract", 1)
    monkeypatch.setenv("OCR_HYBRID_FIRST", "LOCAL")
    monkeypatch.setenv("OCR_HYBRID_REST", "lighton")
    monkeypatch.setenv("OCR_HYBRID_FIRST_PAGES", "2")
    assert [ocr.page_backend(i) for i in range(3)] == ["local", "local", "lighton"]
    ocr.ocr_page(pdf, 1)
    ocr.ocr_page(pdf, 2)
    assert [name for name, _ in engines] == ["local", "lighton"]


@pytest.mark.parametrize(
    ("var", "value", "message"),
    [
        ("OCR_HYBRID_FIRST", "hybrid", "OCR_HYBRID_FIRST must be one of"),
        ("OCR_HYBRID_FIRST", "mistral", "OCR_HYBRID_FIRST must be one of"),
        ("OCR_HYBRID_REST", "easyocr", "OCR_HYBRID_REST must be one of"),
        ("OCR_HYBRID_FIRST_PAGES", "one", "must be an integer"),
        ("OCR_HYBRID_FIRST_PAGES", "0", "must be >= 1"),
    ],
)
def test_hybrid_bad_env_fails_fast(var, value, message, pdf, cache, engines, monkeypatch):
    monkeypatch.setenv("OCR_BACKEND", "hybrid")
    monkeypatch.setenv(var, value)
    with pytest.raises(ValueError, match=message):
        ocr.ocr_page(pdf, 0)
    assert engines == []


def test_unknown_backend_lists_hybrid(cache, monkeypatch):
    monkeypatch.setenv("OCR_BACKEND", "mystery")
    with pytest.raises(ValueError, match="unknown OCR_BACKEND 'mystery'.*hybrid"):
        ocr.backend_name()


def test_trace_records_backend_per_page(pdf, cache, engines, monkeypatch, tmp_path):
    monkeypatch.setenv("OCR_BACKEND", "hybrid")
    tpath = tmp_path / "traces" / "skan.trace.json"
    with trace.document(pdf, tpath, "sprawa/skan.pdf"):
        for i in range(3):
            trace.ocr_page(pdf, i)
    pages = json.loads(tpath.read_text(encoding="utf-8"))["ocr_pages"]
    assert [(p["page"], p["backend"]) for p in pages] == [
        (1, "lighton"),
        (2, "tesseract"),
        (3, "tesseract"),
    ]
