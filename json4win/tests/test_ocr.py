"""json4win.ocr without the model: rendering, cache keying, cache-only mode, text cleaning.

The real-model smoke test runs only with OCR_SMOKE=1 (loads ~7 GB, minutes on CPU).
"""

import json
import os
from pathlib import Path

import pypdfium2
import pytest

from json4win import ocr, ocr_engine

RAW = (
    "<PAGE><BLOCK>header[63, 70, 216, 105]<FORK>KRP\n"
    "<BLOCK>title<LEVEL2>[331, 240, 588, 255]<FORK>Asterion Budownictwo sp. k.\n"
    "<BLOCK>text[331, 256, 831, 438]<FORK>KRS: 9991022552, NIP: 999-295-65-50\n"
    "[reprezentowany przez pełnomocnika:](#)\n"
    "e-mail: [a.rybak@rybak-kancelaria.example](mailto:a.rybak@rybak-kancelaria.example)\n"
    "<BLOCK>text[336, 527, 877, 622]<FORK>nr ref.: [DA.ZP.242.50.2026](mailto:DA.ZP.242.50.2026)\n"
    "<BLOCK>text[92, 712, 890, 778]<FORK>Działając w imieniu Odwołującego – **Asterion sp. k.**"
)


@pytest.fixture
def pdf(tmp_path) -> Path:
    doc = pypdfium2.PdfDocument.new()
    doc.new_page(595, 842)
    doc.new_page(842, 595)
    path = tmp_path / "skan sprawy ąę.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def cache(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("JSON4WIN_CACHE_DIR", str(tmp_path / "cache"))
    for var in (
        "OCR_BACKEND",
        "OCR_CACHE_ONLY",
        "OCR_MODE",
        "OCR_MAX_TOKENS",
        "OCR_DTYPE",
        "OCR_FAST_DECODE",
        "OCR_TESSERACT_CMD",
        "OCR_TESSERACT_DPI",
        "OCR_TESSERACT_LANG",
        "OCR_TESSERACT_PSM",
        "OCR_TESSDATA_DIR",
    ):
        monkeypatch.delenv(var, raising=False)
    return tmp_path / "cache"


@pytest.fixture
def fake_model(monkeypatch) -> list:
    calls = []

    def run(image, s):
        calls.append((image.size, s))
        return {
            "raw": RAW,
            "seconds": 1.0,
            "prefill_seconds": 0.5,
            "tokens": 42,
            "prompt_tokens": 900,
            "finish": "stop",
        }

    monkeypatch.setattr(ocr_engine, "run", run)
    return calls


def test_page_count_and_render(pdf):
    assert ocr.page_count(pdf) == 2
    img = ocr.render_page(pdf, 1, dpi=72)
    assert img.mode == "RGB" and img.size == (842, 595)
    assert ocr.render_page(pdf, 0).size == (round(595 * 200 / 72), round(842 * 200 / 72))
    with pytest.raises(IndexError):
        ocr.render_page(pdf, 2)


def test_ocr_page_runs_model_once_then_hits_cache(pdf, cache, fake_model):
    text = ocr.ocr_page(pdf, 0)
    assert "NIP: 999-295-65-50" in text
    assert ocr.ocr_page(pdf, 0) == text
    assert len(fake_model) == 1  # second call was a cache hit
    entry_file = ocr.cache_path(pdf, 0)
    assert entry_file.is_relative_to(cache / "ocr")
    entry = json.loads(entry_file.read_text(encoding="utf-8"))
    assert entry["raw"] == RAW and entry["page"] == 0 and entry["pdf_sha256"] == ocr.pdf_sha256(pdf)
    settings = json.loads((entry_file.parent.parent / "settings.json").read_text(encoding="utf-8"))
    assert settings["revision"] == ocr_engine.MODEL_REVISION
    assert not list(entry_file.parent.glob(".tmp-*"))  # atomic write left no temp files


def test_cache_key_depends_on_content_page_and_settings(pdf, tmp_path, cache):
    s = ocr_engine.InferSettings()
    assert ocr.settings_id(s) == "0fe4b22967e4791d"  # frozen local default cache key
    base = ocr.cache_path(pdf, 0, s)
    assert ocr.cache_path(pdf, 1, s) != base
    assert ocr.cache_path(pdf, 0, ocr_engine.InferSettings(mode="base")) != base
    assert ocr.cache_path(pdf, 0, ocr_engine.InferSettings(max_tokens=10)) != base
    assert ocr.cache_path(pdf, 0, ocr_engine.InferSettings(fast_decode=2)) != base
    assert ocr.settings_id(s, dpi=300) != ocr.settings_id(s)
    copy = tmp_path / "renamed copy.pdf"  # same bytes, other name -> same entry
    copy.write_bytes(pdf.read_bytes())
    assert ocr.cache_path(copy, 0, s) == base
    other = tmp_path / "other.pdf"
    other.write_bytes(pdf.read_bytes() + b"\n% changed\n")
    assert ocr.cache_path(other, 0, s) != base


def test_settings_from_env(cache, monkeypatch):
    monkeypatch.setenv("OCR_MODE", "base")
    monkeypatch.setenv("OCR_MAX_TOKENS", "1234")
    monkeypatch.setenv("OCR_FAST_DECODE", "2")
    s = ocr.infer_settings()
    assert (s.mode, s.max_tokens, s.dtype, s.fast_decode) == ("base", 1234, "mixed", 2)


def test_cache_only_miss_raises(pdf, cache, fake_model, monkeypatch):
    monkeypatch.setenv("OCR_CACHE_ONLY", "1")
    with pytest.raises(ocr.OcrCacheMiss, match="page 2"):
        ocr.ocr_page(pdf, 1)
    assert fake_model == []
    monkeypatch.setenv("OCR_CACHE_ONLY", "0")
    ocr.ocr_page(pdf, 1)
    monkeypatch.setenv("OCR_CACHE_ONLY", "1")
    assert "Asterion" in ocr.ocr_page(pdf, 1)  # cached now


def test_model_error_has_context_and_is_not_cached(pdf, cache, monkeypatch):
    def boom(image, s):
        raise MemoryError("oom")

    monkeypatch.setattr(ocr_engine, "run", boom)
    with pytest.raises(RuntimeError, match="page 1: oom"):
        ocr.ocr_page(pdf, 0)
    assert not ocr.is_cached(pdf, 0)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            RAW,
            "KRP\nAsterion Budownictwo sp. k.\nKRS: 9991022552, NIP: 999-295-65-50\n"
            "reprezentowany przez pełnomocnika:\n"
            "e-mail: a.rybak@rybak-kancelaria.example\n"
            "nr ref.: DA.ZP.242.50.2026\n"
            "Działając w imieniu Odwołującego – Asterion sp. k.",
        ),
        (
            "<BLOCK>footer[539, 926, 745, 969]<FORK>WPŁYNĘŁO\ndnia 20.09.2026",
            "WPŁYNĘŁO\ndnia 20.09.2026",
        ),
        (
            "<BLOCK>image[1, 2, 3, 4]<FORK>![](images/p_0.jpg)\n<BLOCK>text[1, 2, 3, 4]<FORK>Tak",
            "Tak",
        ),
        (
            "<table><tr><td>Kwota</td><td>7 500,00 PLN</td></tr>"
            "<tr><td>Data</td><td>11.09.2026</td></tr></table>",
            "Kwota | 7 500,00 PLN\nData | 11.09.2026",
        ),
        ("", ""),
    ],
)
def test_clean_text(raw, expected):
    assert ocr.clean_text(raw) == expected


@pytest.mark.skipif(os.environ.get("OCR_SMOKE") != "1", reason="real model: set OCR_SMOKE=1")
def test_smoke_real_model(tmp_path, monkeypatch):
    """One real page through the model (the cache dir is the real one, so reruns are instant)."""
    root = Path(__file__).resolve().parents[2]
    pdf = root / "dane" / "skany" / "potwierdzenia" / "0001" / "0001.pdf"
    monkeypatch.delenv("OCR_CACHE_ONLY", raising=False)
    text = ocr.ocr_page(pdf, 0)
    assert "7 500,00" in text or "7500,00" in text
