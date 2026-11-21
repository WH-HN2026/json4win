"""Tesseract OCR backend and OCR_BACKEND dispatcher (subprocess mocked; task P4)."""

import json
import subprocess
from pathlib import Path

import pypdfium2
import pytest

from json4win import ocr, ocr_engine, ocr_tesseract

TESSERACT_VERSION = "tesseract 5.5.4\n leptonica-1.87.0\n"
SAMPLE_TEXT = "Odwołanie do KIO\r\nNIP: 999-295-65-50   \r\n\r\n\r\nZażalenie żółć\x0c"


@pytest.fixture
def pdf(tmp_path) -> Path:
    doc = pypdfium2.PdfDocument.new()
    doc.new_page(595, 842)
    path = tmp_path / "skan ąę.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def tess_env(tmp_path, monkeypatch) -> Path:
    cache = tmp_path / "cache"
    monkeypatch.setenv("JSON4WIN_CACHE_DIR", str(cache))
    for var in (
        "OCR_BACKEND",
        "OCR_CACHE_ONLY",
        "OCR_TESSERACT_CMD",
        "OCR_TESSERACT_DPI",
        "OCR_TESSERACT_LANG",
        "OCR_TESSERACT_PSM",
        "OCR_TESSDATA_DIR",
    ):
        monkeypatch.delenv(var, raising=False)
    ocr_tesseract._version_cache.clear()
    ocr_tesseract._tessdata_sha_memo.clear()
    return cache


@pytest.fixture
def fake_subprocess(monkeypatch) -> list[dict]:
    """Fake subprocess.run handling `--version` and `stdin stdout` OCR calls."""
    calls: list[dict] = []

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": list(cmd), **kwargs})
        if cmd[1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=TESSERACT_VERSION, stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout=SAMPLE_TEXT.encode("utf-8"), stderr=b"")

    monkeypatch.setattr(ocr_tesseract.subprocess, "run", fake_run)
    return calls


def test_backend_dispatcher_selection_and_unknown_error(tess_env, monkeypatch):
    assert ocr.backend_name() == "local"
    assert isinstance(ocr.active_settings(), ocr_engine.InferSettings)

    monkeypatch.setenv("OCR_BACKEND", "tesseract")
    assert ocr.backend_name() == "tesseract"
    assert isinstance(ocr.active_settings(), ocr_tesseract.TesseractSettings)

    monkeypatch.setenv("OCR_BACKEND", "TESSERACT")
    assert ocr.backend_name() == "tesseract"

    monkeypatch.setenv("OCR_BACKEND", "mystery")
    with pytest.raises(ValueError, match="unknown OCR_BACKEND 'mystery'"):
        ocr.backend_name()


def test_tesseract_command_line_shape_and_output_cleaning(
    pdf, tess_env, fake_subprocess, monkeypatch
):
    monkeypatch.setenv("OCR_BACKEND", "tesseract")
    monkeypatch.setenv("OCR_TESSERACT_PSM", "6")
    monkeypatch.setenv("OCR_TESSERACT_DPI", "300")
    monkeypatch.setenv("OCR_TESSERACT_LANG", "pol")

    text = ocr.ocr_page(pdf, 0)
    assert text == "Odwołanie do KIO\nNIP: 999-295-65-50\n\nZażalenie żółć"

    ocr_calls = [c for c in fake_subprocess if c["cmd"][1:] != ["--version"]]
    assert len(ocr_calls) == 1
    call = ocr_calls[0]
    assert call.get("shell") is None  # no shell=True
    assert call["cmd"] == [
        "tesseract",
        "stdin",
        "stdout",
        "--tessdata-dir",
        str(tess_env / "tessdata"),
        "-l",
        "pol",
        "--dpi",
        "300",
        "--psm",
        "6",
    ]
    assert call["input"].startswith(b"\x89PNG\r\n\x1a\n")

    # Second call hits cache without invoking tesseract again
    assert ocr.ocr_page(pdf, 0) == text
    assert len([c for c in fake_subprocess if c["cmd"][1:] != ["--version"]]) == 1

    # Cache entry & settings.json are written properly
    entry_file = ocr.cache_path(pdf, 0)
    entry = json.loads(entry_file.read_text(encoding="utf-8"))
    assert entry["backend"] == "tesseract"
    assert entry["image_size"] == list(ocr.render_page(pdf, 0, dpi=300).size)
    assert entry["image_size"][0] > 2400  # rendered at 300 dpi, not 200 dpi
    settings_json = json.loads(
        (entry_file.parent.parent / "settings.json").read_text(encoding="utf-8")
    )
    assert settings_json["backend"] == "tesseract"
    assert settings_json["version"] == "tesseract 5.5.4"
    assert settings_json["lang"] == "pol"
    assert settings_json["dpi"] == 300
    assert settings_json["psm"] == 6


def test_tesseract_default_command_omits_psm(tess_env, monkeypatch):
    s = ocr_tesseract.settings_from_env()
    assert s.psm is None
    cmd = ocr_tesseract.build_command(s)
    assert "--psm" not in cmd
    assert cmd == [
        "tesseract",
        "stdin",
        "stdout",
        "--tessdata-dir",
        str(tess_env / "tessdata"),
        "-l",
        "pol",
        "--dpi",
        "300",
    ]


def test_tesseract_custom_cmd_and_tessdata_dir(tess_env, monkeypatch):
    monkeypatch.setenv("OCR_TESSERACT_CMD", "/opt/bin/tesseract-custom")
    monkeypatch.setenv("OCR_TESSDATA_DIR", "/tmp/my tessdata ąę")
    monkeypatch.setenv("OCR_TESSERACT_LANG", "pol+eng")
    monkeypatch.setenv("OCR_TESSERACT_DPI", "150")
    s = ocr_tesseract.settings_from_env()
    assert ocr_tesseract.build_command(s) == [
        "/opt/bin/tesseract-custom",
        "stdin",
        "stdout",
        "--tessdata-dir",
        "/tmp/my tessdata ąę",
        "-l",
        "pol+eng",
        "--dpi",
        "150",
    ]


def test_missing_binary_raises_clear_error(pdf, tess_env, monkeypatch):
    def not_found(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", cmd[0])

    monkeypatch.setattr(ocr_tesseract.subprocess, "run", not_found)
    monkeypatch.setenv("OCR_BACKEND", "tesseract")
    monkeypatch.setenv("OCR_TESSERACT_CMD", "no-such-tesseract-bin")

    with pytest.raises(RuntimeError, match="no-such-tesseract-bin.*not found.*OCR_TESSERACT_CMD"):
        ocr_tesseract.tesseract_version("no-such-tesseract-bin")

    # Also when running OCR directly (bypassing version cache)
    s = ocr_tesseract.TesseractSettings(cmd="no-such-tesseract-bin", tessdata_dir=str(tess_env))
    img = ocr.render_page(pdf, 0, dpi=72)
    with pytest.raises(RuntimeError, match="no-such-tesseract-bin.*not found"):
        ocr_tesseract.run(img, s)


def test_nonzero_exit_mentions_tessdata_hint(pdf, tess_env, monkeypatch):
    def fail_run(cmd, **kwargs):
        if cmd[1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=TESSERACT_VERSION, stderr="")
        return subprocess.CompletedProcess(
            cmd, 1, stdout=b"", stderr=b"Error opening data file /tmp/pol.traineddata\n"
        )

    monkeypatch.setattr(ocr_tesseract.subprocess, "run", fail_run)
    monkeypatch.setenv("OCR_BACKEND", "tesseract")

    with pytest.raises(RuntimeError, match="OCR_TESSDATA_DIR"):
        ocr.ocr_page(pdf, 0)
    assert not ocr.is_cached(pdf, 0)


def test_cache_key_separation_local_vs_tesseract_and_settings(
    pdf, tess_env, fake_subprocess, tmp_path
):
    local_s = ocr_engine.InferSettings()
    tess_default = ocr_tesseract.TesseractSettings(tessdata_dir=str(tess_env / "tessdata"))

    assert ocr.settings_id(local_s) != ocr.settings_id(tess_default)
    assert ocr.cache_path(pdf, 0, local_s) != ocr.cache_path(pdf, 0, tess_default)

    # Different Tesseract settings produce distinct cache ids
    base_id = ocr.settings_id(tess_default)
    assert ocr.settings_id(ocr_tesseract.TesseractSettings(lang="pol+eng")) != base_id
    assert ocr.settings_id(ocr_tesseract.TesseractSettings(dpi=200)) != base_id
    assert ocr.settings_id(ocr_tesseract.TesseractSettings(psm=6)) != base_id

    # Different tesseract version produces a distinct cache id
    ocr_tesseract._version_cache["tesseract"] = "tesseract 5.4.0"
    assert ocr.settings_id(tess_default) != base_id
    ocr_tesseract._version_cache["tesseract"] = "tesseract 5.5.4"

    # Different traineddata file contents (e.g. tessdata_best vs tessdata_fast) separate caches
    td_best = tmp_path / "td_best"
    td_fast = tmp_path / "td_fast"
    td_best.mkdir()
    td_fast.mkdir()
    (td_best / "pol.traineddata").write_bytes(b"best-model-bytes")
    (td_fast / "pol.traineddata").write_bytes(b"fast-model-bytes")
    id_best = ocr.settings_id(ocr_tesseract.TesseractSettings(tessdata_dir=str(td_best)))
    id_fast = ocr.settings_id(ocr_tesseract.TesseractSettings(tessdata_dir=str(td_fast)))
    assert id_best != id_fast
    assert id_best != base_id


def test_cache_only_mode_with_tesseract(pdf, tess_env, fake_subprocess, monkeypatch):
    monkeypatch.setenv("OCR_BACKEND", "tesseract")
    monkeypatch.setenv("OCR_CACHE_ONLY", "1")
    with pytest.raises(ocr.OcrCacheMiss, match="page 1"):
        ocr.ocr_page(pdf, 0)
    # Only --version may have been called to compute cache key; OCR itself was not run
    assert [c for c in fake_subprocess if c["cmd"][1:] != ["--version"]] == []


def test_dispatcher_never_calls_local_engine_when_tesseract_active(
    pdf, tess_env, fake_subprocess, monkeypatch
):
    def forbid_local(*args, **kwargs):
        raise AssertionError("local ocr_engine must not be called when OCR_BACKEND=tesseract")

    monkeypatch.setattr(ocr_engine, "run", forbid_local)
    monkeypatch.setattr(ocr_engine, "load", forbid_local)
    monkeypatch.setenv("OCR_BACKEND", "tesseract")
    text = ocr.ocr_page(pdf, 0)
    assert "Odwołanie do KIO" in text
