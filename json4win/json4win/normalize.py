"""Field normalisers named in class configs (`normalizacja:` + `parametry:`), architecture §3.

Kinds:
- text: collapse whitespace (incl. newlines, NBSP) to single spaces, strip; "" -> None.
- digits: keep ASCII digits only (NIP, REGON, KRS with leading zeros, IBAN/accounts);
  no digits -> None. No checksum validation (training data is synthetic).
- date: -> "YYYY-MM-DD" from ISO, numeric DMY, Polish month names (genitive/nominative,
  case-insensitive, with or without diacritics, common abbreviations), and uppercase
  Roman months; invalid calendar dates or no date -> None. First valid date wins.
- amount: -> float ("50,00 zł", "1 234,56 PLN", "1.234,56", "1,234.56", "10 000,00",
  "10000", "50 PLN", "kwota: 50,00"); no number -> None.
- int: -> int from int, integral float, or integer string ("4", " 4 ", "4."); else None.
- regex_sub: re.sub(params["pattern"], params["repl"], str(value)); unchanged if no match;
  missing or non-string params -> ValueError.
"""

from __future__ import annotations

import datetime
import math
import re
import unicodedata
from collections.abc import Callable
from decimal import Decimal
from typing import Any

_PL_ASCII = str.maketrans("ąćęłńóśźż", "acelnoszz")

_PL_MONTHS: dict[str, int] = {
    "stycznia": 1,
    "styczen": 1,
    "sty": 1,
    "lutego": 2,
    "luty": 2,
    "lut": 2,
    "marca": 3,
    "marzec": 3,
    "mar": 3,
    "kwietnia": 4,
    "kwiecien": 4,
    "kwi": 4,
    "maja": 5,
    "maj": 5,
    "czerwca": 6,
    "czerwiec": 6,
    "cze": 6,
    "lipca": 7,
    "lipiec": 7,
    "lip": 7,
    "sierpnia": 8,
    "sierpien": 8,
    "sie": 8,
    "wrzesnia": 9,
    "wrzesien": 9,
    "wrz": 9,
    "pazdziernika": 10,
    "pazdziernik": 10,
    "paz": 10,
    "listopada": 11,
    "listopad": 11,
    "lis": 11,
    "grudnia": 12,
    "grudzien": 12,
    "gru": 12,
}

_ROMAN_MONTHS: dict[str, int] = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
    "VII": 7,
    "VIII": 8,
    "IX": 9,
    "X": 10,
    "XI": 11,
    "XII": 12,
}

_RE_NON_DIGIT = re.compile(r"[^0-9]")

_RE_DATE_YMD = re.compile(r"(?<!\d)(?P<y>\d{4})[./-](?P<m>\d{1,2})[./-](?P<d>\d{1,2})(?!\d)")
_RE_DATE_DMY = re.compile(
    r"(?<!\d)(?P<d>\d{1,2})\s*[./-]\s*(?P<m>\d{1,2})\s*[./-]\s*(?P<y>\d{4})(?!\d)"
)
_RE_DATE_PL = re.compile(
    r"(?<!\d)(?P<d>\d{1,2})\.?\s+(?P<m>[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+)\.?\s+(?P<y>\d{4})(?!\d)"
)
_RE_DATE_ROMAN = re.compile(
    r"(?<!\d)(?P<d>\d{1,2})(?:\s*[./-]\s*|\s+)"
    r"(?P<m>XII|XI|IX|X|VIII|VII|VI|IV|V|III|II|I)"
    r"(?:\s*[./-]\s*|\s+)(?P<y>\d{4})(?!\d)"
)

_RE_AMOUNT = re.compile(
    r"(?P<sign>(?<![\w.,])[+-])?"
    r"(?P<num>\d{1,3}(?:[\s\u00a0\u202f]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)*)"
)
_RE_THOUSANDS_DOT = re.compile(r"\d{1,3}(?:\.\d{3})+")
_RE_THOUSANDS_COMMA = re.compile(r"\d{1,3}(?:,\d{3})+")

_RE_INT_STR = re.compile(r"[+-]?\d+(?:\.|[.,]0+)?")


def _norm_text(value: Any, _params: dict[str, Any] | None) -> str | None:
    cleaned = " ".join(str(value).split())
    return cleaned or None


def _norm_digits(value: Any, _params: dict[str, Any] | None) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        raw = str(value)
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        raw = str(int(value))
    else:
        raw = str(value)
    digits = _RE_NON_DIGIT.sub("", raw)
    return digits or None


def _try_iso_date(year: int, month: int, day: int) -> str | None:
    if not (1000 <= year <= 2999):
        return None
    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


def _norm_date(value: Any, _params: dict[str, Any] | None) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    if not isinstance(value, str):
        return None

    text = unicodedata.normalize("NFC", value)
    candidates: list[tuple[int, str]] = []

    for m in _RE_DATE_YMD.finditer(text):
        iso = _try_iso_date(int(m["y"]), int(m["m"]), int(m["d"]))
        if iso is not None:
            candidates.append((m.start(), iso))

    for m in _RE_DATE_DMY.finditer(text):
        iso = _try_iso_date(int(m["y"]), int(m["m"]), int(m["d"]))
        if iso is not None:
            candidates.append((m.start(), iso))

    for m in _RE_DATE_PL.finditer(text):
        month_key = m["m"].lower().translate(_PL_ASCII)
        month = _PL_MONTHS.get(month_key)
        if month is not None:
            iso = _try_iso_date(int(m["y"]), month, int(m["d"]))
            if iso is not None:
                candidates.append((m.start(), iso))

    for m in _RE_DATE_ROMAN.finditer(text):
        month = _ROMAN_MONTHS.get(m["m"])
        if month is not None:
            iso = _try_iso_date(int(m["y"]), month, int(m["d"]))
            if iso is not None:
                candidates.append((m.start(), iso))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _parse_amount_token(token: str) -> float | None:
    raw = re.sub(r"\s+", "", token)
    has_comma = "," in raw
    has_dot = "." in raw

    if has_comma and has_dot:
        if raw.rfind(",") > raw.rfind("."):
            if raw.count(",") > 1:
                return None
            int_part, frac_part = raw.split(",")
            if "." in int_part and not _RE_THOUSANDS_DOT.fullmatch(int_part):
                return None
            cleaned = f"{int_part.replace('.', '')}.{frac_part}"
        else:
            if raw.count(".") > 1:
                return None
            int_part, frac_part = raw.split(".")
            if "," in int_part and not _RE_THOUSANDS_COMMA.fullmatch(int_part):
                return None
            cleaned = f"{int_part.replace(',', '')}.{frac_part}"
    elif has_comma:
        if raw.count(",") > 1:
            if not _RE_THOUSANDS_COMMA.fullmatch(raw):
                return None
            cleaned = raw.replace(",", "")
        else:
            cleaned = raw.replace(",", ".")
    elif has_dot:
        if raw.count(".") > 1:
            if not _RE_THOUSANDS_DOT.fullmatch(raw):
                return None
            cleaned = raw.replace(".", "")
        else:
            cleaned = raw
    else:
        cleaned = raw

    try:
        result = float(cleaned)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _norm_amount(value: Any, _params: dict[str, Any] | None) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else None
    if not isinstance(value, str):
        return None

    m = _RE_AMOUNT.search(value)
    if m is None:
        return None
    num = _parse_amount_token(m["num"])
    if num is None:
        return None
    if m["sign"] == "-":
        num = -num
    return 0.0 if num == 0.0 else num


def _norm_int(value: Any, _params: dict[str, Any] | None) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        s = value.strip()
        if not s or not _RE_INT_STR.fullmatch(s):
            return None
        head = re.split(r"[.,]", s, maxsplit=1)[0]
        return int(head)
    return None


def _norm_regex_sub(value: Any, params: dict[str, Any] | None) -> str:
    if not isinstance(params, dict) or "pattern" not in params or "repl" not in params:
        raise ValueError("regex_sub requires params with 'pattern' and 'repl'")
    pattern = params["pattern"]
    repl = params["repl"]
    if not isinstance(pattern, str) or not isinstance(repl, str):
        raise ValueError("regex_sub params 'pattern' and 'repl' must be strings")
    try:
        return re.sub(pattern, repl, str(value))
    except re.error as e:
        raise ValueError(f"regex_sub invalid pattern {pattern!r}: {e}") from e


_NORMALIZERS: dict[str, Callable[[Any, dict[str, Any] | None], Any]] = {
    "text": _norm_text,
    "digits": _norm_digits,
    "date": _norm_date,
    "amount": _norm_amount,
    "int": _norm_int,
    "regex_sub": _norm_regex_sub,
}

KINDS: frozenset[str] = frozenset(_NORMALIZERS)


def normalize(value: Any, kind: str, params: dict[str, Any] | None = None) -> Any:
    """Normalised `value`, or None if it can't be read as `kind`; unknown kind -> ValueError."""
    fn = _NORMALIZERS.get(kind)
    if fn is None:
        raise ValueError(f"Unknown normalizer kind: {kind!r}")
    if value is None:
        return None
    return fn(value, params)
