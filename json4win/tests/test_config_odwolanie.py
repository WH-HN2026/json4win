"""Dev-only checks of json4win/config/odwolanie.yaml against the training ground truth (task E3).

Reads dane/ (allowed in tests, never at runtime). Independent of the C1 config loader.
"""

import json
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "json4win" / "config" / "odwolanie.yaml"
TRAINING = sorted(REPO.glob("dane/przyklad_*/odwolanie.json")) + sorted(
    REPO.glob("dane/skany/odwolania/*/*.json")
)
TYPES = {"str": str, "int": int, "float": float}
CLOSED = ("czynnosc_powod_id", "czynnosc_opis", "przez-pelnomocnika", "prowadzacy_postepowanie")


@pytest.fixture(scope="module")
def cfg() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def truth() -> list[dict]:
    assert len(TRAINING) >= 60, "training JSONs not found"
    return [json.loads(p.read_text(encoding="utf-8")) for p in TRAINING]


def leaves(obj, path: str = ""):
    """(path, value) of every leaf; list items are marked `[]` ("Odwolujacy[].nip")."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from leaves(value, f"{path}.{key}" if path else key)
    elif isinstance(obj, list):
        for item in obj:
            yield from leaves(item, path + "[]")
    else:
        yield path, obj


def leaf_paths(obj) -> list[str]:
    return list(dict.fromkeys(p for p, _ in leaves(obj)))


def values(truth: list[dict], field: str) -> list:
    return [v for doc in truth for p, v in leaves(doc) if p == field and v is not None]


def test_required_keys_and_id(cfg):
    for key in ("id", "nazwa", "opis", "czytanie", "szablon", "pola"):
        assert cfg.get(key), key
    assert cfg["id"] == CONFIG.stem
    czytanie = cfg["czytanie"]
    assert isinstance(czytanie["max_stron"], int) and czytanie["max_stron"] >= 1
    re.compile(czytanie["znacznik"])


def test_szablon_lists_hold_one_item_and_leaves_are_null(cfg):
    def walk(obj):
        if isinstance(obj, dict):
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            assert len(obj) == 1
            walk(obj[0])
        else:
            assert obj is None

    walk(cfg["szablon"])


def test_szablon_matches_every_training_json(cfg, truth):
    expected = leaf_paths(cfg["szablon"])
    for path, doc in zip(TRAINING, truth, strict=True):
        assert leaf_paths(doc) == expected, path
        for key, value in cfg["szablon"].items():
            assert type(doc[key]) is type(value), (path, key)


def test_pola_keys_are_exactly_the_leaves(cfg):
    assert list(cfg["pola"]) == leaf_paths(cfg["szablon"])


def test_pola_entries(cfg):
    kinds = {"text", "digits", "date", "amount", "int", "regex_sub"}
    for field, rule in cfg["pola"].items():
        assert rule.get("opis"), field
        assert rule.get("typ", "str") in TYPES, field
        if "normalizacja" in rule:
            assert rule["normalizacja"] in kinds, field
        if rule.get("normalizacja") == "regex_sub":
            re.compile(rule["parametry"]["pattern"])
            assert "repl" in rule["parametry"], field
        if "format" in rule:
            re.compile(rule["format"])
        typ = TYPES[rule.get("typ", "str")]
        for key in rule.get("wartosci", {}):
            assert type(key) is typ, (field, key)


def test_types_match_training(cfg, truth):
    for field, rule in cfg["pola"].items():
        typ = TYPES[rule.get("typ", "str")]
        for value in values(truth, field):
            assert type(value) is typ, (field, value)


def test_formats_accept_every_training_value(cfg, truth):
    for field, rule in cfg["pola"].items():
        if "format" not in rule:
            continue
        vals = values(truth, field)
        assert vals, field
        bad = [v for v in vals if not re.fullmatch(rule["format"], str(v))]
        assert not bad, (field, bad)


def test_wartosci_cover_every_training_value(cfg, truth):
    for field, rule in cfg["pola"].items():
        if "wartosci" not in rule:
            continue
        missing = set(values(truth, field)) - set(rule["wartosci"])
        assert not missing, (field, missing)


def test_reason_dictionary_is_consistent(cfg, truth):
    ids = cfg["pola"]["OdwolanieKIO.czynnosc_powod_id"]["wartosci"]
    opis = cfg["pola"]["OdwolanieKIO.czynnosc_opis"]["wartosci"]
    assert sorted(ids) == list(range(1, 13))
    by_id = {int(re.search(r"= (\d+)", meaning).group(1)): text for text, meaning in opis.items()}
    assert sorted(by_id) == list(range(1, 13))
    for i, text in by_id.items():
        assert ids[i].startswith(text + " — "), i
    # The organisers' dictionary (dev-time source) says the same.
    src = (REPO / "oczekiwane-json" / "czynnosc_powod_id_dict.md").read_text(encoding="utf-8")
    organisers = {int(k): v.strip() for k, v in re.findall(r"(\d+)=(.+)", src)}
    assert organisers == by_id
    for doc in truth:
        kio = doc["OdwolanieKIO"]
        assert by_id[kio["czynnosc_powod_id"]] == kio["czynnosc_opis"]


def test_regex_sub_keeps_canonical_values(cfg, truth):
    for field, rule in cfg["pola"].items():
        if rule.get("normalizacja") != "regex_sub":
            continue
        p = rule["parametry"]
        for value in values(truth, field):
            assert re.sub(p["pattern"], p["repl"], value) == value, (field, value)


@pytest.mark.parametrize(
    ("field", "raw", "canonical"),
    [
        ("ZamowieniePubliczne.numer_ted", "2027/S 086-123456", "123456-2027"),
        ("ZamowieniePubliczne.numer_ted", "2027/S086-123456", "123456-2027"),
        ("ZamowieniePubliczne.numer_ted", "2027/S\n142-654321", "654321-2027"),
        ("ZamowieniePubliczne.numer_ted", "TED: 123456-2027", "123456-2027"),
        ("ZamowieniePubliczne.numer_bzp", "2027/BZP 00123456", "2027/BZP00123456"),
        ("ZamowieniePubliczne.numer_bzp", "2027/BZP 00123456/01", "2027/BZP00123456/01"),
        ("Odwolujacy[].pelnomocnik.mail", "biuro@kancelaria. example", "biuro@kancelaria.example"),
    ],
)
def test_regex_sub_canonicalises_document_forms(cfg, field, raw, canonical):
    rule = cfg["pola"][field]
    p = rule["parametry"]
    out = re.sub(p["pattern"], p["repl"], raw)
    assert out == canonical
    assert re.fullmatch(rule["format"], out)


def test_przyklady_are_invented_and_well_formed(cfg, truth):
    for field, rule in cfg["pola"].items():
        if field.rsplit(".", 1)[-1] in CLOSED:
            continue
        seen = {str(v) for v in values(truth, field)}
        for example in rule.get("przyklady", []):
            assert str(example) not in seen, (field, example)
            if "format" in rule:
                assert re.fullmatch(rule["format"], str(example)), (field, example)
