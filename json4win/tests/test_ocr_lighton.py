"""LightOnOCR-2-1B backend and OCR_BACKEND=lighton dispatch (model faked, never loaded; task P5)."""

import importlib.metadata
import json
import sys
from pathlib import Path

import pypdfium2
import pytest
from PIL import Image

from json4win import ocr, ocr_engine, ocr_lighton, ocr_tesseract

RAW = "## Potwierdzenie\n\n**Kwota**  \n7 500,00 PLN\n"


@pytest.fixture
def pdf(tmp_path) -> Path:
    doc = pypdfium2.PdfDocument.new()
    doc.new_page(595, 842)
    path = tmp_path / "skan ąę.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def cache(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("JSON4WIN_CACHE_DIR", str(tmp_path / "cache"))
    for var in ("OCR_BACKEND", "OCR_CACHE_ONLY", "OCR_LIGHTON_DTYPE", "OCR_LIGHTON_MAX_TOKENS"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path / "cache"


@pytest.fixture
def fake_lighton(monkeypatch) -> list:
    """ocr_lighton.run replaced by a fake; the other engines must not be called."""
    calls = []

    def run(image, s):
        calls.append((image.size, s))
        return {"raw": RAW, "seconds": 0.1, "tokens": 9, "prompt_tokens": 5, "finish": "stop",
                "backend": "lighton"}  # fmt: skip

    def forbid(*a, **k):
        raise AssertionError("only the lighton engine may run when OCR_BACKEND=lighton")

    monkeypatch.setattr(ocr_lighton, "run", run)
    monkeypatch.setattr(ocr_engine, "run", forbid)
    monkeypatch.setattr(ocr_engine, "load", forbid)
    monkeypatch.setattr(ocr_tesseract, "run", forbid)
    return calls


def test_dispatcher_selects_lighton(pdf, cache, fake_lighton, monkeypatch):
    monkeypatch.setenv("OCR_BACKEND", "LightOn")
    assert ocr.backend_name() == "lighton"
    assert ocr.active_settings() == ocr_lighton.LightOnSettings()
    assert ocr.ocr_page(pdf, 0) == "Potwierdzenie\nKwota\n7 500,00 PLN"
    assert ocr.ocr_page(pdf, 0)  # second read hits the cache
    assert len(fake_lighton) == 1
    size, s = fake_lighton[0]
    assert size == (round(595 * 200 / 72), round(842 * 200 / 72))  # rendered at 200 dpi
    assert s == ocr_lighton.LightOnSettings()
    entry = json.loads(ocr.cache_path(pdf, 0).read_text(encoding="utf-8"))
    assert entry["backend"] == "lighton" and entry["raw"] == RAW
    settings = ocr.cache_path(pdf, 0).parent.parent / "settings.json"
    assert json.loads(settings.read_text(encoding="utf-8"))["backend"] == "lighton"


def test_settings_from_env(cache, monkeypatch):
    monkeypatch.setenv("OCR_LIGHTON_DTYPE", "FP32")
    monkeypatch.setenv("OCR_LIGHTON_MAX_TOKENS", "2000")
    assert ocr_lighton.settings_from_env() == ocr_lighton.LightOnSettings("fp32", 2000)
    monkeypatch.setenv("OCR_LIGHTON_DTYPE", "int4")
    with pytest.raises(ValueError, match="OCR_LIGHTON_DTYPE"):
        ocr_lighton.settings_from_env()
    monkeypatch.setenv("OCR_LIGHTON_DTYPE", "bf16")
    monkeypatch.setenv("OCR_LIGHTON_MAX_TOKENS", "lots")
    with pytest.raises(ValueError, match="OCR_LIGHTON_MAX_TOKENS"):
        ocr_lighton.settings_from_env()


def test_cache_keys_separate_and_local_tesseract_unchanged(pdf, cache, monkeypatch):
    # golden ids computed with the code before P5: existing caches must stay valid
    monkeypatch.setitem(ocr_tesseract._version_cache, "tesseract", "tesseract 5.5.4")
    local_s = ocr_engine.InferSettings()
    tess_s = ocr_tesseract.TesseractSettings()
    assert ocr.settings_id(local_s) == "0fe4b22967e4791d"
    assert ocr.settings_id(tess_s) == "e6b00a2b8114c7d6"
    assert ocr.settings_id(ocr_tesseract.TesseractSettings(psm=6, dpi=200)) == "4cdb8a33296b3ddb"

    light = ocr_lighton.LightOnSettings()
    ids = {ocr.settings_id(s) for s in (local_s, tess_s, light)}
    assert len(ids) == 3
    key = ocr.settings_key(light)
    assert key["backend"] == "lighton"
    assert key["model"] == ocr_lighton.MODEL_ID and key["revision"] == ocr_lighton.MODEL_REVISION
    assert (key["dpi"], key["longest_side"]) == (200, 1540)
    assert ocr.settings_id(ocr_lighton.LightOnSettings(dtype="fp32")) != ocr.settings_id(light)
    assert ocr.settings_id(ocr_lighton.LightOnSettings(max_tokens=100)) != ocr.settings_id(light)


def test_cache_key_needs_no_transformers(cache, monkeypatch):
    """The main .venv (transformers 4) computes the key and reads the cache without importing it."""
    monkeypatch.setitem(sys.modules, "transformers", None)  # any import would fail
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setenv("OCR_BACKEND", "lighton")
    assert len(ocr.settings_id()) == 16


def test_cache_only_miss(pdf, cache, fake_lighton, monkeypatch):
    monkeypatch.setenv("OCR_BACKEND", "lighton")
    monkeypatch.setenv("OCR_CACHE_ONLY", "1")
    with pytest.raises(ocr.OcrCacheMiss, match="page 1"):
        ocr.ocr_page(pdf, 0)
    assert fake_lighton == []


@pytest.mark.parametrize("version", ["4.52.1", "4.57.6"])
def test_clear_error_on_old_transformers(version, monkeypatch):
    monkeypatch.setattr(importlib.metadata, "version", lambda name: version)
    with pytest.raises(RuntimeError, match=r"transformers>=5 .*\.venv-lighton, see docs/ocr\.md"):
        ocr_lighton.check_transformers()
    # the error surfaces before torch/transformers are imported
    ocr_lighton._loaded.clear()
    monkeypatch.setitem(sys.modules, "transformers", None)
    with pytest.raises(RuntimeError, match="transformers>=5"):
        ocr_lighton.load("bf16")


def test_transformers_5_passes_check(monkeypatch):
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "5.24.0")
    ocr_lighton.check_transformers()


def test_engine_error_has_context(pdf, cache, monkeypatch):
    def boom(image, s):
        raise RuntimeError("LightOnOCR needs transformers>=5 (found 4.52.1)")

    monkeypatch.setattr(ocr_lighton, "run", boom)
    monkeypatch.setenv("OCR_BACKEND", "lighton")
    with pytest.raises(RuntimeError, match=r"skan ąę\.pdf page 1: LightOnOCR needs"):
        ocr.ocr_page(pdf, 0)
    assert not ocr.is_cached(pdf, 0)


def test_resize_longest_side():
    img = ocr_lighton.resize(Image.new("RGB", (1654, 2339), "white"))
    assert img.size == (1089, 1540)
    small = Image.new("RGB", (800, 600), "white")
    assert ocr_lighton.resize(small).size == (800, 600)  # never upscaled


MARKDOWN = """\
![Logo banku](image_1.png)

# Bank Nadwiślański

**Nazwa firmy:** ASTERION BUDOWNICTWO SP. K.<sp>
*Niniejsze potwierdzenie przelewu nie wymaga podpisu.*

---

| Pole | Wartość |
|------|:-------:|
| **Z rachunku** | PL62 2170 0008 9152 5017 5661 7062 |
| Kwota | 7 500,00 PLN |

<table><tr><th>Nadawca</th><th>NIP</th></tr>
<tr><td>Kowalski_Jan sp. z o.o.</td><td>999\\-295\\-65\\-50</td></tr></table>

**Nazwa banku**<sp>
*(blank)*

E-mail: [biuro@kancelaria.example](mailto:biuro@kancelaria.example), j_nowak@kancelaria.example

<div style="display: flex;">
  <div>Dokument wygenerowany w dniu 11.09.2026 18:53</div>
</div>
""".replace("<sp>", "  ")

CLEAN = """\
Bank Nadwiślański
Nazwa firmy: ASTERION BUDOWNICTWO SP. K.
Niniejsze potwierdzenie przelewu nie wymaga podpisu.
Pole | Wartość
Z rachunku | PL62 2170 0008 9152 5017 5661 7062
Kwota | 7 500,00 PLN
Nadawca | NIP
Kowalski_Jan sp. z o.o. | 999-295-65-50
Nazwa banku
E-mail: biuro@kancelaria.example, j_nowak@kancelaria.example
Dokument wygenerowany w dniu 11.09.2026 18:53"""


def test_clean_text_markdown():
    assert ocr_lighton.clean_text(MARKDOWN) == CLEAN


def test_ocr_page_uses_lighton_cleaner(pdf, cache, monkeypatch):
    def run(image, s):
        return {"raw": MARKDOWN, "seconds": 0.1, "tokens": 1, "finish": "stop"}

    monkeypatch.setattr(ocr_lighton, "run", run)
    monkeypatch.setenv("OCR_BACKEND", "lighton")
    assert ocr.ocr_page(pdf, 0) == CLEAN
