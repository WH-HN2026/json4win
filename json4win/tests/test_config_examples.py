"""Tests for config_examples/ and JSON4WIN_CONFIG_DIRS (task X1).

Includes an opt-in live LLM end-to-end test (LLM_LIVE=1, OCR faked via pdftotext on a real
BZP notice PDF — never starts the local OCR model).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from json4win import config, decide, env, ocr, pipeline, prompts, validate
from tests.conftest import FAKTURA_YAML

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = env.APP_ROOT / "config_examples"
BZP_SAMPLE_PDF = REPO_ROOT / "dane" / "negatywne" / "2025_BZP 00143067_01.pdf"


def test_example_class_loads_and_renders_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    examples = config.load_classes(EXAMPLES_DIR)
    assert "ogloszenie_bzp" in examples
    c = examples["ogloszenie_bzp"]
    assert c.czytanie == config.Reading(
        max_stron=3, znacznik=r"(?i)SEKCJA\s+IV\b", stron_po_znaczniku=0
    )

    # Every example value in the YAML must pass its own normaliser/type/format/wartosci rule.
    for path, rule in c.pola.items():
        for ex in rule.przyklady:
            val, err = validate.check_field(rule, ex)
            assert err is None, f"{path}: example {ex!r} failed validation: {err}"
            assert val is not None

    # Loading via JSON4WIN_CONFIG_DIRS merges the example class after json4win/config/.
    monkeypatch.setenv("JSON4WIN_CONFIG_DIRS", str(EXAMPLES_DIR))
    combined = config.load_classes()
    assert "ogloszenie_bzp" in combined
    assert set(config.load_classes(config.CONFIG_DIR)).issubset(combined)

    # Decision and extraction prompts render with the new class, without any code change.
    dec = prompts.decision_prompt(combined)
    assert "`ogloszenie_bzp`: Ogłoszenie o zamówieniu (BZP)." in dec
    assert '"ogloszenie_bzp"' in dec
    assert "Biuletyn Zamówień Publicznych" in dec

    ext = prompts.extraction_prompt(c)
    assert "Ogłoszenie o zamówieniu (BZP)" in ext
    for leaf in config.leaf_paths(c.szablon):
        assert f"`{leaf}`" in ext
    assert '"roboty_budowlane"' in ext
    assert r"`^\d{8}-\d$`" in ext
    assert "Instrukcje dla tego rodzaju dokumentu:" in ext


def test_json4win_config_dirs_relative_and_multiple(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Relative path resolved against APP_ROOT (works regardless of cwd).
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JSON4WIN_CONFIG_DIRS", "config_examples")
    classes = config.load_classes()
    assert "ogloszenie_bzp" in classes

    # Multiple os.pathsep-separated directories, ignoring empty segments.
    extra = tmp_path / "more_classes"
    extra.mkdir()
    (extra / "faktura.yaml").write_text(FAKTURA_YAML, encoding="utf-8")
    monkeypatch.setenv(
        "JSON4WIN_CONFIG_DIRS", f"{EXAMPLES_DIR}{os.pathsep}{os.pathsep}{extra}{os.pathsep}"
    )
    both = config.load_classes()
    assert "ogloszenie_bzp" in both and "faktura" in both


def test_json4win_config_dirs_duplicate_id_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "base"
    extra = tmp_path / "extra"
    base.mkdir()
    extra.mkdir()
    (base / "faktura.yaml").write_text(FAKTURA_YAML, encoding="utf-8")
    (extra / "faktura.yaml").write_text(FAKTURA_YAML, encoding="utf-8")

    monkeypatch.setattr(config, "CONFIG_DIR", base)
    monkeypatch.setenv("JSON4WIN_CONFIG_DIRS", str(extra))
    with pytest.raises(config.ConfigError, match="duplicate class id 'faktura'"):
        config.load_classes()

    # Duplicate across two extra dirs also fails clearly.
    extra2 = tmp_path / "extra2"
    extra2.mkdir()
    other = yaml.safe_load(FAKTURA_YAML) | {"id": "rachunek"}
    (extra / "rachunek.yaml").write_text(yaml.safe_dump(other, allow_unicode=True), "utf-8")
    (extra2 / "rachunek.yaml").write_text(yaml.safe_dump(other, allow_unicode=True), "utf-8")
    (extra / "faktura.yaml").unlink()

    monkeypatch.setenv("JSON4WIN_CONFIG_DIRS", f"{extra}{os.pathsep}{extra2}")
    with pytest.raises(config.ConfigError, match="duplicate class id 'rachunek'"):
        config.load_classes()


def test_json4win_config_dirs_missing_dir_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "does_not_exist"
    monkeypatch.setenv("JSON4WIN_CONFIG_DIRS", str(missing))
    with pytest.raises(config.ConfigError, match="directory not found"):
        config.load_classes()


def test_example_class_reading_stops_at_sekcja_iv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = config.load_classes(EXAMPLES_DIR)["ogloszenie_bzp"]
    fake_pages = [
        "Ogłoszenie nr 2029/BZP 00412345\nSEKCJA I - ZAMAWIAJĄCY\nSEKCJA II",
        "SEKCJA III\nSEKCJA IV – PRZEDMIOT ZAMÓWIENIA\n4.2.6.) Główny kod CPV: 30200000-1",
        "SEKCJA V - KWALIFIKACJA WYKONAWCÓW",
    ]
    seen: list[int] = []
    monkeypatch.setattr(ocr, "page_count", lambda _pdf: len(fake_pages))
    monkeypatch.setattr(ocr, "ocr_page", lambda _pdf, idx: (seen.append(idx), fake_pages[idx])[1])

    pages = decide.read_pages(tmp_path / "dummy.pdf", c, fake_pages[0])
    assert len(pages) == 2
    assert seen == [1]  # page 0 already passed as first_page; page 2 never OCR'd


@pytest.mark.skipif(os.environ.get("LLM_LIVE") != "1", reason="set LLM_LIVE=1")
def test_live_new_class_pipeline_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt-in live run: real LLM + JSON4WIN_CONFIG_DIRS=config_examples, OCR faked by pdftotext."""
    if not BZP_SAMPLE_PDF.is_file():
        pytest.skip(f"sample PDF not found: {BZP_SAMPLE_PDF}")

    env.load_env()
    raw = subprocess.run(
        ["pdftotext", str(BZP_SAMPLE_PDF), "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    pdf_pages = [p.strip() for p in raw.split("\x0c") if p.strip()]
    assert len(pdf_pages) == 3

    read_indices: list[int] = []
    monkeypatch.setattr(ocr, "page_count", lambda _pdf: len(pdf_pages))
    monkeypatch.setattr(
        ocr, "ocr_page", lambda _pdf, idx: (read_indices.append(idx), pdf_pages[idx])[1]
    )
    monkeypatch.setenv("JSON4WIN_CONFIG_DIRS", str(EXAMPLES_DIR))
    pipeline.classes.cache_clear()
    try:
        result = pipeline.process_document(BZP_SAMPLE_PDF)
    finally:
        pipeline.classes.cache_clear()

    print(f"\npages_read={read_indices}")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    assert read_indices == [0, 1]  # stopped on SEKCJA IV (page 2 of 3)
    assert list(result) == ["ogloszenie_bzp"]
    bzp = result["ogloszenie_bzp"]
    assert bzp["numer_bzp"] == "2025/BZP 00143067"
    assert bzp["wersja"] == 1
    assert bzp["data_publikacji"] == "2025-03-12"
    assert bzp["rodzaj_zamowienia"] == "uslugi"
    assert bzp["numer_referencyjny"] == "ZP/7/2025"
    assert bzp["glowny_kod_cpv"] == "50800000-3"
    assert bzp["tytul"] and "Celestynów" in bzp["tytul"]
    zam = bzp["zamawiajacy"]
    assert zam["nazwa"] == "26 Wojskowy Oddział Gospodarczy"
    assert zam["regon"] == "142917040"
    assert zam["miejscowosc"] == "Zegrze"
    assert zam["kod_pocztowy"] == "05-131"
    assert zam["email"] == "jw4809.zp@ron.mil.pl"
