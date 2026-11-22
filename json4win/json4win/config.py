"""Document class configs: one YAML file per class in json4win/config/ (architecture D6).

The format and the rules enforced here are fixed in json4win/config/README.md. Every `*.yaml` /
`*.yml` file in the directory is a class; other files (README.md, prompt_*.md) are ignored. Adding a
class means adding a file.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from json4win import env

CONFIG_DIR = env.APP_ROOT / "config"
OTHER = "inne"  # the decision model's answer for "no class"
TYPES = {"str": str, "int": int, "float": float}
NORMALIZERS = {"text", "digits", "date", "amount", "int", "regex_sub"}


class ConfigError(ValueError):
    """A class file breaks the format of json4win/config/README.md."""


@dataclass(frozen=True)
class FieldRule:
    path: str  # "Odwolujacy[].pelnomocnik.mail"
    opis: str
    typ: str = "str"
    normalizacja: str | None = None
    parametry: dict = field(default_factory=dict)
    format: str | None = None
    wartosci: dict | None = None
    przyklady: list = field(default_factory=list)
    poprawki_ocr: str | None = None


@dataclass(frozen=True)
class Reading:
    max_stron: int
    znacznik: str | None = None
    stron_po_znaczniku: int = 0
    kompletny_gdy: str | None = None


@dataclass(frozen=True)
class DocClass:
    id: str
    nazwa: str
    opis: str
    czytanie: Reading
    szablon: dict
    pola: dict[str, FieldRule]  # in szablon leaf order
    cechy: list[str] = field(default_factory=list)
    nie_mylic_z: list[str] = field(default_factory=list)
    instrukcje: str | None = None
    source: Path | None = None


def leaf_paths(template: Any, prefix: str = "") -> list[str]:
    """Leaf paths of a szablon in order: `a.b`, list items as `a[].b`."""
    if isinstance(template, dict):
        out = []
        for k, v in template.items():
            out += leaf_paths(v, f"{prefix}.{k}" if prefix else str(k))
        return out
    if isinstance(template, list):
        return leaf_paths(template[0], f"{prefix}[]") if template else []
    return [prefix]


def _err(src: Path, key: str, msg: str) -> ConfigError:
    return ConfigError(f"{src.name}: {key}: {msg}")


def _str(src: Path, d: dict, key: str, where: str, required: bool = True) -> str | None:
    v = d.get(key)
    if v is None:
        if required:
            raise _err(src, f"{where}{key}", "required key missing")
        return None
    if not isinstance(v, str) or not v.strip():
        raise _err(src, f"{where}{key}", f"must be a non-empty string, got {v!r}")
    return v.strip()


def _str_list(src: Path, d: dict, key: str) -> list[str]:
    v = d.get(key)
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise _err(src, key, "must be a list of strings")
    return v


def _regex(src: Path, key: str, pattern: Any) -> str:
    if not isinstance(pattern, str):
        raise _err(src, key, f"regex must be a string, got {pattern!r}")
    try:
        re.compile(pattern)
    except re.error as e:
        raise _err(src, key, f"regex does not compile: {e}") from None
    return pattern


def _check_template(src: Path, t: Any, path: str) -> None:
    if isinstance(t, dict):
        if not t:
            raise _err(src, path or "szablon", "empty object")
        for k, v in t.items():
            if not isinstance(k, str):
                raise _err(src, f"{path}.{k}" if path else str(k), "key must be a string")
            _check_template(src, v, f"{path}.{k}" if path else k)
    elif isinstance(t, list):
        if len(t) != 1:
            raise _err(
                src, path, f"a list must hold exactly one item (the item shape), has {len(t)}"
            )
        _check_template(src, t[0], f"{path}[]")
    elif t is not None:
        raise _err(src, path, f"template leaves must be null, got {t!r}")


def _reading(src: Path, raw: Any) -> Reading:
    if not isinstance(raw, dict):
        raise _err(src, "czytanie", "required mapping missing")
    max_stron = raw.get("max_stron")
    if isinstance(max_stron, bool) or not isinstance(max_stron, int) or max_stron < 1:
        raise _err(src, "czytanie.max_stron", f"must be an integer >= 1, got {max_stron!r}")
    after = raw.get("stron_po_znaczniku", 0)
    if isinstance(after, bool) or not isinstance(after, int) or after < 0:
        raise _err(src, "czytanie.stron_po_znaczniku", f"must be an integer >= 0, got {after!r}")
    marker = raw.get("znacznik")
    if marker is not None:
        _regex(src, "czytanie.znacznik", marker)
    return Reading(
        max_stron=max_stron,
        znacznik=marker,
        stron_po_znaczniku=after,
        kompletny_gdy=_str(src, raw, "kompletny_gdy", "czytanie.", required=False),
    )


def _field(src: Path, path: str, raw: Any) -> FieldRule:
    key = f"pola.{path}"
    if not isinstance(raw, dict):
        raise _err(src, key, "must be a mapping with at least `opis`")
    w = f"{key}."
    typ = raw.get("typ", "str")
    if typ not in TYPES:
        raise _err(src, f"{w}typ", f"unknown type {typ!r}, expected one of {sorted(TYPES)}")
    norm = raw.get("normalizacja")
    if norm is not None and norm not in NORMALIZERS:
        raise _err(
            src, f"{w}normalizacja", f"unknown kind {norm!r}, expected {sorted(NORMALIZERS)}"
        )
    params = raw.get("parametry") or {}
    if not isinstance(params, dict):
        raise _err(src, f"{w}parametry", "must be a mapping")
    if norm == "regex_sub":
        if "pattern" not in params or "repl" not in params:
            raise _err(src, f"{w}parametry", "regex_sub needs `pattern` and `repl`")
    if "pattern" in params:
        _regex(src, f"{w}parametry.pattern", params["pattern"])
    fmt = raw.get("format")
    if fmt is not None:
        _regex(src, f"{w}format", fmt)
    values = raw.get("wartosci")
    if values is not None:
        if not isinstance(values, dict) or not values:
            raise _err(src, f"{w}wartosci", "must be a non-empty mapping value -> meaning")
        for v in values:
            ok = isinstance(v, TYPES[typ]) and not isinstance(v, bool)
            if typ == "float":
                ok = isinstance(v, int | float) and not isinstance(v, bool)
            if not ok:
                raise _err(src, f"{w}wartosci", f"key {v!r} does not match typ {typ}")
    examples = raw.get("przyklady") or []
    if not isinstance(examples, list):
        raise _err(src, f"{w}przyklady", "must be a list")
    hints = raw.get("poprawki_ocr")
    return FieldRule(
        path=path,
        opis=_str(src, raw, "opis", w),
        typ=typ,
        normalizacja=norm,
        parametry=params,
        format=fmt,
        wartosci=values,
        przyklady=examples,
        poprawki_ocr=str(hints).strip() if hints is not None else None,
    )


def load_class(path: Path) -> DocClass:
    """Load and validate one class file."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path.name}: not valid YAML: {e}") from None
    if not isinstance(raw, dict):
        raise ConfigError(f"{path.name}: must be a YAML mapping")

    cid = _str(path, raw, "id", "")
    if cid != path.stem:
        raise _err(path, "id", f"{cid!r} must equal the file name {path.stem!r}")
    if cid == OTHER:
        raise _err(path, "id", f"{OTHER!r} is reserved for 'no class'")

    if "szablon" not in raw:
        raise _err(path, "szablon", "required key missing")
    template = raw["szablon"]
    if not isinstance(template, dict):
        raise _err(path, "szablon", "must be a mapping (the output object)")
    _check_template(path, template, "")

    pola = raw.get("pola")
    if not isinstance(pola, dict) or not pola:
        raise _err(path, "pola", "required mapping missing")
    leaves = leaf_paths(template)
    missing = [p for p in leaves if p not in pola]
    if missing:
        raise _err(path, "pola", f"no entry for template leaves {missing}")
    extra = [p for p in pola if p not in leaves]
    if extra:
        raise _err(path, "pola", f"keys are not template leaves: {extra}")

    instr = raw.get("instrukcje")
    return DocClass(
        id=cid,
        nazwa=_str(path, raw, "nazwa", ""),
        opis=_str(path, raw, "opis", ""),
        czytanie=_reading(path, raw.get("czytanie")),
        szablon=template,
        pola={p: _field(path, p, pola[p]) for p in leaves},
        cechy=_str_list(path, raw, "cechy"),
        nie_mylic_z=_str_list(path, raw, "nie_mylic_z"),
        instrukcje=str(instr).strip() if instr is not None else None,
        source=path,
    )


def _extra_config_dirs() -> list[Path]:
    raw = env.get("JSON4WIN_CONFIG_DIRS")
    if not raw:
        return []
    dirs: list[Path] = []
    for entry in raw.split(os.pathsep):
        entry = entry.strip()
        if not entry:
            continue
        p = Path(entry)
        if not p.is_absolute() and not p.is_dir():
            alt = env.APP_ROOT / p
            if alt.is_dir():
                p = alt
        if not p.is_dir():
            raise ConfigError(f"JSON4WIN_CONFIG_DIRS: directory not found: {entry!r}")
        dirs.append(p)
    return dirs


def load_classes(config_dir: Path | None = None) -> dict[str, DocClass]:
    """Every class in the config dir (plus JSON4WIN_CONFIG_DIRS when default), by id."""
    dirs = [config_dir] if config_dir is not None else [CONFIG_DIR, *_extra_config_dirs()]
    classes: dict[str, DocClass] = {}
    for d in dirs:
        files = sorted(p for p in d.iterdir() if p.suffix.lower() in (".yaml", ".yml"))
        for c in map(load_class, files):
            if c.id in classes:
                raise ConfigError(
                    f"{c.source}: duplicate class id {c.id!r} (already in {classes[c.id].source})"
                )
            classes[c.id] = c
    return classes
