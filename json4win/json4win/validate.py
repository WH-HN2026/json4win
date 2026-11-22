"""Shape coercion and per-field validation against a class config (architecture §3, steps 7-8)."""

import re
from typing import Any

from json4win import normalize
from json4win.config import DocClass, FieldRule

Loc = tuple  # concrete location in the output: ("Odwolujacy", 0, "nip")


def coerce(template: Any, data: Any) -> Any:
    """`data` forced into the template's shape: missing keys -> null, extra keys dropped.

    A list holds 1..n items shaped by the template item (a single object is wrapped; an empty or
    missing list gives one all-null item; all-null items are dropped when others have values).
    Leaves keep scalars only. Objects are never null.
    """
    if isinstance(template, dict):
        data = data if isinstance(data, dict) else {}
        return {k: coerce(t, data.get(k)) for k, t in template.items()}
    if isinstance(template, list):
        if isinstance(data, dict):
            data = [data]
        items = [coerce(template[0], x) for x in data] if isinstance(data, list) else []
        filled = [x for x in items if not _all_null(x)]
        return filled or [coerce(template[0], None)]
    return data if isinstance(data, str | int | float | bool) else None


def _all_null(x: Any) -> bool:
    if isinstance(x, dict):
        return all(_all_null(v) for v in x.values())
    if isinstance(x, list):
        return all(_all_null(v) for v in x)
    return x is None


def leaves(data: Any, rule_path: str = "", path: Loc = ()) -> list[tuple[str, Loc, Any]]:
    """(rule path `a[].b`, concrete path ('a', 0, 'b'), value) for every leaf of coerced data."""
    if isinstance(data, dict):
        out = []
        for k, v in data.items():
            out += leaves(v, f"{rule_path}.{k}" if rule_path else k, (*path, k))
        return out
    if isinstance(data, list):
        out = []
        for i, v in enumerate(data):
            out += leaves(v, f"{rule_path}[]", (*path, i))
        return out
    return [(rule_path, path, data)]


def show_path(path: Loc) -> str:
    """('Odwolujacy', 0, 'nip') -> 'Odwolujacy[0].nip'."""
    s = ""
    for p in path:
        s += f"[{p}]" if isinstance(p, int) else (f".{p}" if s else p)
    return s


def get_at(data: Any, path: Loc) -> Any:
    for p in path:
        data = data[p]
    return data


def set_at(data: Any, path: Loc, value: Any) -> None:
    for p in path[:-1]:
        data = data[p]
    data[path[-1]] = value


def _cast(value: Any, typ: str) -> Any:
    """Lossless casts to the field type; returns the value unchanged if none applies."""
    if isinstance(value, bool):
        return value
    if typ == "str" and isinstance(value, int | float):
        return str(value)
    if typ == "int":
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and re.fullmatch(r"\s*-?\d+\s*", value):
            return int(value)
    if typ == "float":
        if isinstance(value, int):
            return float(value)
        if isinstance(value, str) and re.fullmatch(r"\s*-?\d+(\.\d+)?\s*", value):
            return float(value)
    return value


def check_field(rule: FieldRule, value: Any) -> tuple[Any, str | None]:
    """Normalise and validate one value: (value, None) if valid, else (raw value, Polish reason)."""
    if isinstance(value, str) and not value.strip():
        value = None
    if value is None:
        return None, None
    if rule.typ == "str" and isinstance(value, int | float) and not isinstance(value, bool):
        value = str(value)
    raw = value
    if rule.normalizacja:
        try:
            value = normalize.normalize(value, rule.normalizacja, rule.parametry)
        except (ValueError, TypeError):
            value = None
        if value is None:
            return raw, f"wartości {raw!r} nie da się odczytać jako {rule.normalizacja}"
    value = _cast(value, rule.typ)
    want = {"str": str, "int": int, "float": float}[rule.typ]
    if isinstance(value, bool) or not isinstance(value, want):
        return raw, f"wartość {raw!r} nie jest typu {rule.typ}"
    if rule.format and not re.fullmatch(rule.format, str(value)):
        return raw, f"wartość {raw!r} nie pasuje do formatu `{rule.format}`"
    if rule.wartosci is not None and value not in rule.wartosci:
        allowed = ", ".join(repr(k) for k in rule.wartosci)
        return raw, f"wartość {raw!r} nie jest jedną z dozwolonych: {allowed}"
    return value, None


def check(c: DocClass, data: Any) -> tuple[dict, dict[Loc, str]]:
    """Coerce `data` to the class template, normalise and validate every field.

    Returns (output, errors): `output` has the template shape with valid values normalised and
    invalid ones still raw; `errors` maps each invalid field's concrete path to a reason.
    """
    out = coerce(c.szablon, data)
    errors = {}
    for rule_path, path, value in leaves(out):
        value, err = check_field(c.pola[rule_path], value)
        set_at(out, path, value)
        if err:
            errors[path] = err
    return out, errors


def error_lines(errors: dict[Loc, str]) -> list[str]:
    return [f"`{show_path(p)}`: {e}" for p, e in errors.items()]
