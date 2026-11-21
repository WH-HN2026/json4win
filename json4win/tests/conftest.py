"""Shared fixtures: an invented class file (not a real class) using every config rule."""

from pathlib import Path

import pytest

from json4win import config

FAKTURA_YAML = r"""
id: faktura
nazwa: Faktura VAT
opis: >-
  Faktura sprzedaży z numerem, datą wystawienia, sprzedawcą i nabywcami.
cechy:
  - "nagłówek 'Faktura VAT nr'"
nie_mylic_z:
  - "paragon, nota księgowa"
czytanie:
  max_stron: 3
  znacznik: '(?i)do zapłaty'
  stron_po_znaczniku: 1
szablon:
  Faktura:
    numer: null
    data: null
    kwota: null
    pozycje: null
  Nabywcy:
    - nazwa: null
      nip: null
      typ: null
pola:
  Faktura.numer:
    opis: Numer faktury z nagłówka.
    format: '^FV/\d+/\d{4}$'
    przyklady: ["FV/12/2031"]
    poprawki_ocr: W cyfrach O→0.
  Faktura.data:
    opis: Data wystawienia.
    normalizacja: date
    format: '^\d{4}-\d{2}-\d{2}$'
  Faktura.kwota:
    opis: Kwota do zapłaty.
    typ: float
    normalizacja: amount
  Faktura.pozycje:
    opis: Liczba pozycji.
    typ: int
    wartosci:
      1: jedna pozycja
      2: dwie pozycje
  Nabywcy[].nazwa:
    opis: Nazwa nabywcy.
  Nabywcy[].nip:
    opis: NIP nabywcy, 10 cyfr.
    normalizacja: digits
    format: '^\d{10}$'
  Nabywcy[].typ:
    opis: Rodzaj nabywcy.
    wartosci:
      firma: "spółka, przedsiębiorca"
      osoba: "człowiek"
instrukcje: >-
  Nabywców wypisz w kolejności z dokumentu.
"""


@pytest.fixture(autouse=True)
def _trace_dir(tmp_path: Path, monkeypatch) -> Path:
    """CLI runs in tests write their traces under tmp_path, never into json4win/traces/."""
    d = tmp_path / "traces"
    monkeypatch.setenv("JSON4WIN_TRACE_DIR", str(d))
    return d


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    (d / "faktura.yaml").write_text(FAKTURA_YAML, encoding="utf-8")
    (d / "README.md").write_text("# not a class", encoding="utf-8")
    real = config.CONFIG_DIR
    for p in real.glob("prompt_*.md"):
        (d / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    return d


@pytest.fixture
def faktura(config_dir: Path) -> config.DocClass:
    return config.load_classes(config_dir)["faktura"]
