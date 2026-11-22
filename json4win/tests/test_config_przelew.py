"""Tests validating json4win/config/przelew.yaml against the config contract and training JSONs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "json4win" / "config" / "przelew.yaml"
DANE_DIR = REPO_ROOT / "dane"

ALLOWED_TOP_KEYS = {
    "id",
    "nazwa",
    "opis",
    "cechy",
    "nie_mylic_z",
    "czytanie",
    "szablon",
    "pola",
    "instrukcje",
}
REQUIRED_TOP_KEYS = {"id", "nazwa", "opis", "czytanie", "szablon", "pola"}
ALLOWED_CZYTANIE_KEYS = {"max_stron", "znacznik", "stron_po_znaczniku", "kompletny_gdy"}
ALLOWED_POLE_KEYS = {
    "opis",
    "typ",
    "normalizacja",
    "parametry",
    "format",
    "wartosci",
    "przyklady",
    "poprawki_ocr",
}
ALLOWED_TYPY = {"str", "int", "float"}
ALLOWED_NORMALIZACJE = {"text", "digits", "date", "amount", "int", "regex_sub"}


def _leaf_paths(obj: Any, prefix: str = "") -> list[str]:
    """Return all leaf paths in traversal order, marking list items with `[]`."""
    if isinstance(obj, dict):
        paths: list[str] = []
        for k, v in obj.items():
            sub = f"{prefix}.{k}" if prefix else k
            paths.extend(_leaf_paths(v, sub))
        return paths
    if isinstance(obj, list):
        if not obj:
            return [f"{prefix}[]"]
        seen: list[str] = []
        for item in obj:
            for p in _leaf_paths(item, f"{prefix}[]"):
                if p not in seen:
                    seen.append(p)
        return seen
    return [prefix]


def _extract_leaf_values(obj: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Return all (leaf_path, value) pairs from a JSON document."""
    if isinstance(obj, dict):
        out: list[tuple[str, Any]] = []
        for k, v in obj.items():
            sub = f"{prefix}.{k}" if prefix else k
            out.extend(_extract_leaf_values(v, sub))
        return out
    if isinstance(obj, list):
        out = []
        for item in obj:
            out.extend(_extract_leaf_values(item, f"{prefix}[]"))
        return out
    return [(prefix, obj)]


def _matches_typ(value: Any, typ: str) -> bool:
    if isinstance(value, bool):
        return False
    if typ == "str":
        return isinstance(value, str)
    if typ == "int":
        return isinstance(value, int)
    if typ == "float":
        return isinstance(value, (int, float))
    return False


@pytest.fixture(scope="module")
def config() -> dict[str, Any]:
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def training_docs() -> list[tuple[Path, dict[str, Any]]]:
    przyklady = sorted(DANE_DIR.glob("przyklad_*/przelew.json"))
    skany = sorted(DANE_DIR.glob("skany/potwierdzenia/*/*.json"))
    assert len(przyklady) >= 60, f"expected >= 60 przyklad przelew JSONs, got {len(przyklady)}"
    assert len(skany) >= 10, f"expected >= 10 skany przelew JSONs, got {len(skany)}"
    return [(p, json.loads(p.read_text(encoding="utf-8"))) for p in przyklady + skany]


def test_schema_structure_and_keys(config: dict[str, Any]) -> None:
    assert REQUIRED_TOP_KEYS.issubset(config.keys())
    assert set(config.keys()).issubset(ALLOWED_TOP_KEYS)
    assert config["id"] == CONFIG_PATH.stem
    assert isinstance(config["nazwa"], str) and config["nazwa"].strip()
    assert isinstance(config["opis"], str) and config["opis"].strip()

    czytanie = config["czytanie"]
    assert isinstance(czytanie, dict)
    assert set(czytanie.keys()).issubset(ALLOWED_CZYTANIE_KEYS)
    assert isinstance(czytanie["max_stron"], int) and czytanie["max_stron"] >= 1
    if "znacznik" in czytanie:
        re.compile(czytanie["znacznik"])

    pola = config["pola"]
    assert isinstance(pola, dict) and pola
    for path, spec in pola.items():
        assert isinstance(spec, dict), f"{path}: spec must be a mapping"
        assert set(spec.keys()).issubset(ALLOWED_POLE_KEYS), f"{path}: unknown keys"
        assert isinstance(spec.get("opis"), str) and spec["opis"].strip(), f"{path}: missing opis"
        typ = spec.get("typ", "str")
        assert typ in ALLOWED_TYPY, f"{path}: unknown typ {typ!r}"
        if "normalizacja" in spec:
            assert spec["normalizacja"] in ALLOWED_NORMALIZACJE, f"{path}: unknown normalizacja"
        if "format" in spec:
            re.compile(spec["format"])
        if "wartosci" in spec:
            assert isinstance(spec["wartosci"], dict) and spec["wartosci"]
            for k in spec["wartosci"]:
                assert _matches_typ(k, typ), f"{path}: wartosci key {k!r} does not match typ {typ}"


def test_szablon_leaves_match_pola_and_training_jsons(
    config: dict[str, Any],
    training_docs: list[tuple[Path, dict[str, Any]]],
) -> None:
    szablon_entries = _extract_leaf_values(config["szablon"])
    szablon_leaves = [p for p, _ in szablon_entries]
    assert all(v is None for _, v in szablon_entries), "all szablon leaves must be null"
    assert len(szablon_leaves) == len(set(szablon_leaves)), "duplicate leaf paths in szablon"
    assert set(config["pola"].keys()) == set(szablon_leaves)

    for path, doc in training_docs:
        doc_leaves = _leaf_paths(doc)
        assert doc_leaves == szablon_leaves, (
            f"{path.relative_to(REPO_ROOT)}: leaf paths/order {doc_leaves} != {szablon_leaves}"
        )


def test_formats_types_and_wartosci_match_all_training_values(
    config: dict[str, Any],
    training_docs: list[tuple[Path, dict[str, Any]]],
) -> None:
    pola = config["pola"]
    for path, doc in training_docs:
        rel = path.relative_to(REPO_ROOT)
        for field_path, val in _extract_leaf_values(doc):
            if val is None:
                continue
            spec = pola[field_path]
            typ = spec.get("typ", "str")
            assert _matches_typ(val, typ), (
                f"{rel} {field_path}: value {val!r} ({type(val).__name__}) != typ {typ}"
            )
            if "format" in spec:
                pat = spec["format"]
                assert re.fullmatch(pat, str(val)), (
                    f"{rel} {field_path}: {val!r} failed format {pat!r}"
                )
            if "wartosci" in spec:
                assert val in spec["wartosci"], (
                    f"{rel} {field_path}: {val!r} not in wartosci {list(spec['wartosci'])}"
                )


def test_examples_are_valid_and_not_copied_from_training(
    config: dict[str, Any],
    training_docs: list[tuple[Path, dict[str, Any]]],
) -> None:
    training_values: dict[str, set[str]] = {}
    for _, doc in training_docs:
        for field_path, val in _extract_leaf_values(doc):
            if val is not None:
                training_values.setdefault(field_path, set()).add(str(val))

    for field_path, spec in config["pola"].items():
        typ = spec.get("typ", "str")
        examples = spec.get("przyklady") or []
        for ex in examples:
            assert _matches_typ(ex, typ), f"{field_path}: example {ex!r} != typ {typ}"
            if "format" in spec:
                assert re.fullmatch(spec["format"], str(ex)), (
                    f"{field_path}: example {ex!r} failed format {spec['format']!r}"
                )
            assert str(ex) not in training_values.get(field_path, set()), (
                f"{field_path}: example {ex!r} appears verbatim in training data (D9)"
            )
