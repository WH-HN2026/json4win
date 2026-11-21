"""Table-driven unit tests for json4win.normalize (real PDF snippets + edge cases)."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from json4win.normalize import KINDS, normalize


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_none_returns_none_for_every_kind(kind):
    assert normalize(None, kind) is None


@pytest.mark.parametrize("bad_kind", ["", "unknown", "float", "TEXT", "nip"])
def test_unknown_kind_raises_value_error_naming_kind(bad_kind):
    with pytest.raises(ValueError, match=bad_kind or "Unknown"):
        normalize("abc", bad_kind)


def test_unknown_kind_raises_even_when_value_is_none():
    with pytest.raises(ValueError, match="bogus"):
        normalize(None, "bogus")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Real snippets from training PDFs
        (
            "Zakup i dostawa sprzętu komputerowego wraz z oprogramowaniem oraz usługą\nwdrożenia",
            "Zakup i dostawa sprzętu komputerowego wraz z oprogramowaniem oraz usługą wdrożenia",
        ),
        (
            "Kancelaria Adwokacka Spółka z ograniczoną\nodpowiedzialnością",
            "Kancelaria Adwokacka Spółka z ograniczoną odpowiedzialnością",
        ),
        (
            "opłata skarbowa od pełnomocnictwa dla\n  Aleksandra\u00a0Marciniak",
            "opłata skarbowa od pełnomocnictwa dla Aleksandra Marciniak",
        ),
        ("  Belmoria\t\tRozwiązania\u202fS.A.  ", "Belmoria Rozwiązania S.A."),
        ("  \n\t\u00a0  ", None),
        ("", None),
        (12345, "12345"),
    ],
)
def test_normalize_text(raw, expected):
    assert normalize(raw, "text") == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Real snippets & spec examples (incl. synthetic NIPs/accounts that fail checksums)
        ("PL 999-579-14-92", "9995791492"),
        ("NIP: 999 579 14 92", "9995791492"),
        ("NIP: 9999284065", "9999284065"),
        ("KRS 0000054588", "0000054588"),
        ("KRS: 9999405188", "9999405188"),
        ("REGON: 000279077", "000279077"),
        ("PESEL 85071204278", "85071204278"),
        ("PL95 5048 8442 5794 5465 0864 7369", "95504884425794546508647369"),
        ("PL05470680287581539721455024", "05470680287581539721455024"),
        ("PL02 8303 3566 8029 4951 6078 2084", "02830335668029495160782084"),
        ("03 7129 1844 2654 8930 6542 7654", "03712918442654893065427654"),
        ("09460896147587484470692985", "09460896147587484470692985"),
        (85071204278, "85071204278"),
        (12345.0, "12345"),
        (123.45, None),
        (True, None),
        ("PL", None),
        ("brak danych", None),
        ("m²", None),
        ("", None),
    ],
)
def test_normalize_digits(raw, expected):
    assert normalize(raw, "digits") == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Numeric DMY & ISO forms (from spec and real PDFs)
        ("13.10.2025", "2025-10-13"),
        ("13.10.2025 r.", "2025-10-13"),
        ("13.10.2025r.", "2025-10-13"),
        ("17.02.2026", "2026-02-17"),
        ("13-10-2025", "2025-10-13"),
        ("01-08-2026", "2026-08-01"),
        ("13/10/2025", "2025-10-13"),
        ("03/06/2025", "2025-06-03"),
        ("3.5.2025", "2025-05-03"),
        ("2025-10-13", "2025-10-13"),
        ("2026-03-21", "2026-03-21"),
        ("2025.10.13", "2025-10-13"),
        ("2025/10/13", "2025-10-13"),
        ("2025-10-13T14:30:00", "2025-10-13"),
        ("DATA REALIZACJI ............. 17.02.2026", "2026-02-17"),
        # Polish month names — all 12 months (genitive, nominative, no diacritics, case)
        ("5 stycznia 2026 r.", "2026-01-05"),
        ("5 styczeń 2026", "2026-01-05"),
        ("5 styczen 2026", "2026-01-05"),
        ("16 lutego 2026 roku", "2026-02-16"),
        ("16 luty 2026", "2026-02-16"),
        ("20 marca 2026 roku", "2026-03-20"),
        ("2 marzec 2026", "2026-03-02"),
        ("Łódź, 1 kwietnia 2026", "2026-04-01"),
        ("1 kwiecien 2026", "2026-04-01"),
        ("12 maja 2026 r.", "2026-05-12"),
        ("12 maj 2026", "2026-05-12"),
        ("1 czerwca 2026 r.", "2026-06-01"),
        ("1 czerwiec 2026", "2026-06-01"),
        ("1 lipca 2026 r.", "2026-07-01"),
        ("1 lipiec 2026", "2026-07-01"),
        ("23 sierpnia 2026", "2026-08-23"),
        ("23 sierpien 2026", "2026-08-23"),
        ("Gdańsk, dnia 3 września 2026 roku", "2026-09-03"),
        ("3 wrzesnia 2026", "2026-09-03"),
        ("3 wrzesien 2026", "2026-09-03"),
        ("13 października 2025 r.", "2025-10-13"),
        ("13 pazdziernika 2025", "2025-10-13"),
        ("13 PAŹDZIERNIKA 2025 R.", "2025-10-13"),
        ("13 październik 2025", "2025-10-13"),
        ("13 paź. 2025", "2025-10-13"),
        ("11 listopada 2026", "2026-11-11"),
        ("11 listopad 2026", "2026-11-11"),
        ("24 grudnia 2026 r.", "2026-12-24"),
        ("24 grudzien 2026", "2026-12-24"),
        ("13.\u00a0października\n2025 r.", "2025-10-13"),
        ("13 paz\u0301dziernika 2025 r.", "2025-10-13"),
        # Roman numeral months (uppercase only; lowercase Polish conjunction 'i' ignored)
        ("3 X 2025", "2025-10-03"),
        ("13.X.2025 r.", "2025-10-13"),
        ("1 IV 2026", "2026-04-01"),
        ("15 XII 2025", "2025-12-15"),
        ("część 1 i 2026", None),
        # Multiple dates: first valid date wins (regardless of format)
        ("od 01.03.2026 do 15.03.2026", "2026-03-01"),
        ("20 marca 2026 roku (publikacja 2026-03-21)", "2026-03-20"),
        ("2026-03-21 oraz 20 marca 2026", "2026-03-21"),
        # Leap years & calendar validation
        ("29.02.2024", "2024-02-29"),
        ("29.02.2025", None),
        ("31.04.2025", None),
        ("32.10.2025", None),
        ("13.13.2025", None),
        ("00.10.2025", None),
        ("31 lutego 2026", None),
        # Native date / datetime & non-date inputs
        (datetime.date(2026, 3, 20), "2026-03-20"),
        (datetime.datetime(2026, 3, 20, 13, 3), "2026-03-20"),
        ("brak daty", None),
        ("", None),
        (20251013, None),
        (True, None),
    ],
)
def test_normalize_date(raw, expected):
    assert normalize(raw, "date") == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Spec examples and real przelew PDF snippets
        ("50,00 zł", 50.0),
        ("1 234,56 PLN", 1234.56),
        ("1\u00a0234,56\u00a0PLN", 1234.56),
        ("1.234,56", 1234.56),
        ("1,234.56", 1234.56),
        ("10 000,00", 10000.0),
        ("11 640 000,00 zł", 11640000.0),
        ("10000", 10000.0),
        ("50 PLN", 50.0),
        ("kwota: 50,00", 50.0),
        ("Kwota operacji: 50.00 PLN", 50.0),
        ("Kwota operacji: 17,00 zł", 17.0),
        ("PLN 200.00", 200.0),
        ("KWOTA PRZELEWU ....................................... 50,00 PLN", 50.0),
        ("WARTOŚĆ .............................................. 200,00 zł", 200.0),
        ("0,00 PLN", 0.0),
        ("1.234.567,89 zł", 1234567.89),
        ("1,234,567.89 PLN", 1234567.89),
        ("1.234.567", 1234567.0),
        ("1,234,567", 1234567.0),
        ("-50,00 PLN", -50.0),
        ("-0,00 PLN", 0.0),
        ("kwota - 50,00 zł", 50.0),
        # Native numeric & invalid inputs
        (50, 50.0),
        (50.5, 50.5),
        (Decimal("17.00"), 17.0),
        (float("nan"), None),
        (float("inf"), None),
        (Decimal("NaN"), None),
        (True, None),
        ("13.10.2025", None),
        ("1.2.3", None),
        ("brak kwoty", None),
        ("PLN", None),
        ("", None),
    ],
)
def test_normalize_amount(raw, expected):
    result = normalize(raw, "amount")
    assert result == expected
    if expected is not None:
        assert isinstance(result, float)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (4, 4),
        (0, 0),
        (-3, -3),
        (4.0, 4),
        (0.0, 0),
        (4.5, None),
        (float("nan"), None),
        (float("inf"), None),
        (True, None),
        (False, None),
        ("4", 4),
        (" 4 ", 4),
        ("4.", 4),
        (" 4. ", 4),
        ("04", 4),
        ("4.0", 4),
        ("4,00", 4),
        ("-2", -2),
        ("+7", 7),
        ("4.5", None),
        ("4,5", None),
        ("4.0.0", None),
        ("4 pkt", None),
        ("brak", None),
        ("", None),
        ("   ", None),
        (".", None),
        ([4], None),
    ],
)
def test_normalize_int(raw, expected):
    result = normalize(raw, "int")
    assert result == expected
    if expected is not None:
        assert type(result) is int


@pytest.mark.parametrize(
    ("raw", "params", "expected"),
    [
        # TED canonicalisation from spec & real PDFs
        (
            "2026/S086-999073",
            {"pattern": r"(\d{4})/S\s*\d{1,3}-(\d{6})", "repl": r"\2-\1"},
            "999073-2026",
        ),
        (
            "2025/S 023-998397",
            {"pattern": r"(\d{4})/S\s*\d{1,3}-(\d{6})", "repl": r"\2-\1"},
            "998397-2025",
        ),
        # Unchanged when pattern does not match
        (
            "999137-2026",
            {"pattern": r"(\d{4})/S\s*\d{1,3}-(\d{6})", "repl": r"\2-\1"},
            "999137-2026",
        ),
        # BZP space stripping (empty repl)
        (
            "2025/BZP 00143067/01",
            {"pattern": r"\s+", "repl": ""},
            "2025/BZP00143067/01",
        ),
        (
            "2026/BZP00999778",
            {"pattern": r"\s+", "repl": ""},
            "2026/BZP00999778",
        ),
        # Non-string input converted via str(value)
        (12345, {"pattern": r"^(\d{2})(\d{3})$", "repl": r"\1-\2"}, "12-345"),
    ],
)
def test_normalize_regex_sub(raw, params, expected):
    assert normalize(raw, "regex_sub", params=params) == expected


@pytest.mark.parametrize(
    "bad_params",
    [
        None,
        {},
        {"pattern": r"\d+"},
        {"repl": "x"},
        {"pattern": 123, "repl": "x"},
        {"pattern": r"\d+", "repl": None},
        {"pattern": r"[unclosed", "repl": ""},
    ],
)
def test_normalize_regex_sub_bad_params_raises(bad_params):
    with pytest.raises(ValueError):
        normalize("2026/S086-999073", "regex_sub", params=bad_params)
