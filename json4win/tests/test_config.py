from pathlib import Path

import pytest
import yaml

from json4win import config
from tests.conftest import FAKTURA_YAML


def test_loads_fixture(config_dir: Path) -> None:
    classes = config.load_classes(config_dir)
    assert list(classes) == ["faktura"]  # README.md and prompt_*.md are ignored
    c = classes["faktura"]
    assert c.czytanie == config.Reading(
        max_stron=3, znacznik="(?i)do zapłaty", stron_po_znaczniku=1
    )
    assert list(c.pola) == [
        "Faktura.numer",
        "Faktura.data",
        "Faktura.kwota",
        "Faktura.pozycje",
        "Nabywcy[].nazwa",
        "Nabywcy[].nip",
        "Nabywcy[].typ",
    ]
    assert c.pola["Faktura.kwota"].typ == "float"
    assert c.pola["Faktura.pozycje"].wartosci == {1: "jedna pozycja", 2: "dwie pozycje"}
    assert c.cechy and c.nie_mylic_z and c.instrukcje


def _broken(edit) -> dict:
    raw = yaml.safe_load(FAKTURA_YAML)
    edit(raw)
    return raw


def _set(path: str, value):
    def edit(raw):
        *parents, last = path.split("/")
        d = raw
        for p in parents:
            d = d[p]
        if value is _DEL:
            del d[last]
        else:
            d[last] = value

    return edit


_DEL = object()


@pytest.mark.parametrize(
    "edit, message",
    [
        (_set("id", _DEL), "id: required key missing"),
        (_set("id", "rachunek"), "must equal the file name"),
        (_set("nazwa", _DEL), "nazwa: required key missing"),
        (_set("opis", _DEL), "opis: required key missing"),
        (_set("czytanie", _DEL), "czytanie: required mapping missing"),
        (_set("czytanie/max_stron", _DEL), "czytanie.max_stron: must be an integer >= 1"),
        (_set("czytanie/max_stron", 0), "czytanie.max_stron: must be an integer >= 1"),
        (_set("czytanie/stron_po_znaczniku", -1), "czytanie.stron_po_znaczniku"),
        (_set("czytanie/znacznik", "(?i)do (zapłaty"), "czytanie.znacznik: regex does not compile"),
        (_set("szablon", _DEL), "szablon: required key missing"),
        (_set("szablon/Nabywcy", [{"nazwa": None}, {"nazwa": None}]), "exactly one item"),
        (_set("szablon/Faktura/numer", "x"), "template leaves must be null"),
        (_set("pola", _DEL), "pola: required mapping missing"),
        (_set("pola/Faktura.numer", _DEL), "no entry for template leaves ['Faktura.numer']"),
        (_set("pola/Faktura.vat", {"opis": "x"}), "keys are not template leaves: ['Faktura.vat']"),
        (_set("pola/Faktura.numer/opis", _DEL), "pola.Faktura.numer.opis: required key missing"),
        (_set("pola/Faktura.kwota/typ", "decimal"), "pola.Faktura.kwota.typ: unknown type"),
        (_set("pola/Faktura.kwota/normalizacja", "money"), "normalizacja: unknown kind"),
        (_set("pola/Faktura.numer/format", "^FV/(\\d+$"), "pola.Faktura.numer.format: regex does"),
        (
            _set("pola/Faktura.numer/normalizacja", "regex_sub"),
            "regex_sub needs `pattern` and `repl`",
        ),
        (
            _set("pola/Faktura.numer/parametry", {"pattern": "(", "repl": ""}),
            "parametry.pattern: regex does not compile",
        ),
        (_set("pola/Faktura.pozycje/wartosci", {"1": "x"}), "key '1' does not match typ int"),
        (_set("pola/Nabywcy[].typ/wartosci", {1: "x"}), "key 1 does not match typ str"),
    ],
)
def test_rejects_broken_rule(tmp_path: Path, edit, message: str) -> None:
    f = tmp_path / "faktura.yaml"
    f.write_text(yaml.safe_dump(_broken(edit), allow_unicode=True), encoding="utf-8")
    with pytest.raises(config.ConfigError) as e:
        config.load_classes(tmp_path)
    assert str(e.value).startswith("faktura.yaml: ")
    assert message in str(e.value)


def test_rejects_invalid_yaml_and_reserved_id(tmp_path: Path) -> None:
    (tmp_path / "x.yaml").write_text("id: [unclosed", encoding="utf-8")
    with pytest.raises(config.ConfigError, match="x.yaml: not valid YAML"):
        config.load_classes(tmp_path)
    (tmp_path / "x.yaml").unlink()
    raw = yaml.safe_load(FAKTURA_YAML) | {"id": "inne"}
    (tmp_path / "inne.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(config.ConfigError, match="reserved"):
        config.load_classes(tmp_path)


def test_leaf_paths() -> None:
    t = {"a": {"b": None, "c": [{"d": None, "e": [{"f": None}]}]}, "g": None}
    assert config.leaf_paths(t) == ["a.b", "a.c[].d", "a.c[].e[].f", "g"]


def test_real_class_files_load() -> None:
    if not any(config.CONFIG_DIR.glob("*.yaml")):
        pytest.skip("no class files in json4win/config yet (tasks E1-E3)")
    classes = config.load_classes()
    assert classes and all(c.pola for c in classes.values())
