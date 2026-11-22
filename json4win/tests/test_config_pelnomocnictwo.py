"""Dev-only validation tests for json4win/config/pelnomocnictwo.yaml against training JSONs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "json4win" / "config" / "pelnomocnictwo.yaml"
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
ALLOWED_FIELD_KEYS = {
    "opis",
    "typ",
    "normalizacja",
    "parametry",
    "format",
    "wartosci",
    "przyklady",
    "poprawki_ocr",
}
KNOWN_TYPES = {"str": str, "int": int, "float": float}
KNOWN_NORMALIZERS = {"text", "digits", "date", "amount", "int", "regex_sub"}


def _load_config() -> dict[str, Any]:
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "config root must be a YAML mapping"
    return data


def _training_json_paths() -> list[Path]:
    przyklady = sorted(DANE_DIR.glob("przyklad_*/pelnomocnictwo.json"))
    skany = sorted(DANE_DIR.glob("skany/pelnomocnictwa/*/*.json"))
    return przyklady + skany


def _extract_leaf_paths(obj: Any, prefix: str = "") -> set[str]:
    """Collect leaf paths using the `a.b[].c` convention from config/README.md."""
    if isinstance(obj, dict):
        leaves: set[str] = set()
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            leaves.update(_extract_leaf_paths(value, path))
        return leaves
    if isinstance(obj, list):
        assert len(obj) > 0, f"unexpected empty list at {prefix}"
        leaves = set()
        for item in obj:
            leaves.update(_extract_leaf_paths(item, f"{prefix}[]"))
        return leaves
    return {prefix}


def _collect_leaf_values(obj: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Collect (leaf_path, value) pairs from an instance JSON."""
    if isinstance(obj, dict):
        out: list[tuple[str, Any]] = []
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            out.extend(_collect_leaf_values(value, path))
        return out
    if isinstance(obj, list):
        out = []
        for item in obj:
            out.extend(_collect_leaf_values(item, f"{prefix}[]"))
        return out
    return [(prefix, obj)]


def _assert_template_shape(template: Any, path: str = "") -> None:
    """Enforce config/README.md rules on `szablon`: leaves are None, lists hold 1 item."""
    if isinstance(template, dict):
        assert template, f"empty object in szablon at {path or '<root>'}"
        for k, v in template.items():
            _assert_template_shape(v, f"{path}.{k}" if path else k)
    elif isinstance(template, list):
        assert len(template) == 1, f"szablon list at {path} must hold exactly 1 item"
        _assert_template_shape(template[0], f"{path}[]")
    else:
        assert template is None, f"szablon leaf at {path} must be null, got {template!r}"


def _assert_same_structure_and_key_order(template: Any, instance: Any, path: str = "") -> None:
    """Verify exact key names, key order, and container types match `szablon`."""
    if isinstance(template, dict):
        assert isinstance(instance, dict), f"{path}: expected dict, got {type(instance).__name__}"
        assert list(instance.keys()) == list(template.keys()), (
            f"{path}: key order mismatch: {list(instance.keys())} != {list(template.keys())}"
        )
        for k in template:
            _assert_same_structure_and_key_order(
                template[k], instance[k], f"{path}.{k}" if path else k
            )
    elif isinstance(template, list):
        assert isinstance(instance, list), f"{path}: expected list, got {type(instance).__name__}"
        assert len(instance) >= 1, f"{path}: expected non-empty list"
        for idx, item in enumerate(instance):
            _assert_same_structure_and_key_order(template[0], item, f"{path}[{idx}]")
    else:
        assert not isinstance(instance, (dict, list)), (
            f"{path}: expected scalar/null leaf, got {type(instance).__name__}"
        )


def test_yaml_parses_and_conforms_to_config_format() -> None:
    cfg = _load_config()

    assert REQUIRED_TOP_KEYS <= set(cfg.keys())
    assert set(cfg.keys()) <= ALLOWED_TOP_KEYS
    assert cfg["id"] == CONFIG_PATH.stem == "pelnomocnictwo"
    assert isinstance(cfg["nazwa"], str) and cfg["nazwa"].strip()
    assert isinstance(cfg["opis"], str) and cfg["opis"].strip()

    czytanie = cfg["czytanie"]
    assert isinstance(czytanie, dict)
    assert set(czytanie.keys()) <= ALLOWED_CZYTANIE_KEYS
    assert isinstance(czytanie.get("max_stron"), int) and czytanie["max_stron"] >= 1
    if "znacznik" in czytanie:
        re.compile(czytanie["znacznik"])
    if "stron_po_znaczniku" in czytanie:
        spz = czytanie["stron_po_znaczniku"]
        assert isinstance(spz, int) and spz >= 0

    _assert_template_shape(cfg["szablon"])

    szablon_leaves = _extract_leaf_paths(cfg["szablon"])
    pola = cfg["pola"]
    assert isinstance(pola, dict)
    assert set(pola.keys()) == szablon_leaves, (
        f"pola keys {set(pola.keys())} != szablon leaves {szablon_leaves}"
    )

    for leaf_path, spec in pola.items():
        assert isinstance(spec, dict), f"{leaf_path}: field spec must be a mapping"
        assert set(spec.keys()) <= ALLOWED_FIELD_KEYS, (
            f"{leaf_path}: unknown keys {set(spec.keys()) - ALLOWED_FIELD_KEYS}"
        )
        assert isinstance(spec.get("opis"), str) and spec["opis"].strip(), (
            f"{leaf_path}: opis is required"
        )
        typ_name = spec.get("typ", "str")
        assert typ_name in KNOWN_TYPES, f"{leaf_path}: unknown typ {typ_name!r}"
        py_type = KNOWN_TYPES[typ_name]

        if "normalizacja" in spec:
            assert spec["normalizacja"] in KNOWN_NORMALIZERS, (
                f"{leaf_path}: unknown normalizacja {spec['normalizacja']!r}"
            )
            if spec["normalizacja"] == "regex_sub":
                params = spec.get("parametry") or {}
                assert "pattern" in params and "repl" in params
                re.compile(params["pattern"])

        if "format" in spec:
            pattern = re.compile(spec["format"])
            for ex in spec.get("przyklady", []):
                assert pattern.fullmatch(str(ex)), (
                    f"{leaf_path}: example {ex!r} does not match format {spec['format']!r}"
                )

        if "wartosci" in spec:
            assert isinstance(spec["wartosci"], dict) and spec["wartosci"]
            for allowed_val, meaning in spec["wartosci"].items():
                assert isinstance(allowed_val, py_type), (
                    f"{leaf_path}: wartosci key {allowed_val!r} is not {typ_name}"
                )
                assert isinstance(meaning, str) and meaning.strip()


def test_szablon_and_pola_match_all_training_jsons() -> None:
    cfg = _load_config()
    szablon = cfg["szablon"]
    szablon_leaves = _extract_leaf_paths(szablon)
    pola = cfg["pola"]

    paths = _training_json_paths()
    assert len(paths) >= 70, (
        f"expected >= 70 training JSONs (60 przyklad + 10 skany), got {len(paths)}"
    )

    training_values_by_field: dict[str, list[tuple[Path, Any]]] = {k: [] for k in pola}

    for json_path in paths:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        _assert_same_structure_and_key_order(szablon, data)
        assert _extract_leaf_paths(data) == szablon_leaves, (
            f"{json_path}: leaves differ from szablon"
        )
        for leaf_path, val in _collect_leaf_values(data):
            if val is not None:
                training_values_by_field[leaf_path].append((json_path, val))

    for leaf_path, spec in pola.items():
        typ_name = spec.get("typ", "str")
        py_type = KNOWN_TYPES[typ_name]
        fmt_re = re.compile(spec["format"]) if "format" in spec else None
        allowed = set(spec["wartosci"].keys()) if "wartosci" in spec else None

        for json_path, val in training_values_by_field[leaf_path]:
            # bool is a subclass of int in Python; reject booleans explicitly.
            assert not isinstance(val, bool) and isinstance(val, py_type), (
                f"{json_path} {leaf_path}: value {val!r} has type {type(val).__name__}, "
                f"expected {typ_name}"
            )
            if fmt_re is not None:
                assert fmt_re.fullmatch(str(val)), (
                    f"{json_path} {leaf_path}: value {val!r} does not fullmatch {spec['format']!r}"
                )
            if allowed is not None:
                assert val in allowed, (
                    f"{json_path} {leaf_path}: value {val!r} not in wartosci {sorted(allowed)}"
                )


def test_examples_are_invented_not_copied_from_training_data() -> None:
    cfg = _load_config()
    training_values: set[str] = set()
    for json_path in _training_json_paths():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        for _, val in _collect_leaf_values(data):
            if val is not None:
                training_values.add(str(val))

    for leaf_path, spec in cfg["pola"].items():
        if "wartosci" in spec:
            continue
        for ex in spec.get("przyklady", []):
            assert str(ex) not in training_values, (
                f"{leaf_path}: example {ex!r} collides with a training value (violates D9)"
            )
