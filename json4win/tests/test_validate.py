import pytest
from tests.fakes import fake_normalize

from json4win import normalize, validate


@pytest.fixture(autouse=True)
def _fake_normalize(monkeypatch):
    monkeypatch.setattr(normalize, "normalize", fake_normalize)


T = {"A": {"x": None, "y": None}, "L": [{"n": None, "s": {"k": None}}]}


@pytest.mark.parametrize(
    "data, want",
    [
        (None, {"A": {"x": None, "y": None}, "L": [{"n": None, "s": {"k": None}}]}),
        ([1, 2], {"A": {"x": None, "y": None}, "L": [{"n": None, "s": {"k": None}}]}),
        (
            {"A": {"x": "1", "extra": 2}, "B": 3, "L": []},
            {"A": {"x": "1", "y": None}, "L": [{"n": None, "s": {"k": None}}]},
        ),
        (  # a single object instead of a list is wrapped
            {"L": {"n": "a"}},
            {"A": {"x": None, "y": None}, "L": [{"n": "a", "s": {"k": None}}]},
        ),
        (  # all-null items dropped when others have values; order kept
            {"L": [{"n": "b"}, {}, {"n": None, "s": {"k": None}}, {"n": "a", "s": {"k": 5}}]},
            {
                "A": {"x": None, "y": None},
                "L": [{"n": "b", "s": {"k": None}}, {"n": "a", "s": {"k": 5}}],
            },
        ),
        (  # objects / lists at leaves become null; objects at object keys become all-null
            {"A": {"x": {"v": 1}, "y": [1]}, "L": [{"n": "a", "s": "flat"}]},
            {"A": {"x": None, "y": None}, "L": [{"n": "a", "s": {"k": None}}]},
        ),
    ],
)
def test_coerce(data, want) -> None:
    assert validate.coerce(T, data) == want


@pytest.mark.parametrize(
    "path, value, want, error",
    [
        ("Faktura.numer", "FV/12/2031", "FV/12/2031", None),
        ("Faktura.numer", "FV-12", "FV-12", "nie pasuje do formatu"),
        ("Faktura.numer", "  ", None, None),
        ("Faktura.numer", None, None, None),
        ("Faktura.data", "17.04.2031", "2031-04-17", None),
        ("Faktura.data", "wczoraj", "wczoraj", "nie da się odczytać jako date"),
        ("Faktura.kwota", "1 234,50 zł", 1234.5, None),
        ("Faktura.kwota", 50, 50.0, None),
        ("Faktura.pozycje", 2, 2, None),
        ("Faktura.pozycje", "2", 2, None),
        ("Faktura.pozycje", 2.0, 2, None),
        ("Faktura.pozycje", 3, 3, "nie jest jedną z dozwolonych"),
        ("Faktura.pozycje", True, True, "nie jest typu int"),
        ("Faktura.pozycje", "dwie", "dwie", "nie jest typu int"),
        ("Nabywcy[].nip", "999-123-45-67", "9991234567", None),
        ("Nabywcy[].nip", 9991234567, "9991234567", None),
        ("Nabywcy[].nip", "999 123", "999 123", "nie pasuje do formatu"),
        ("Nabywcy[].typ", "firma", "firma", None),
        ("Nabywcy[].typ", "spółka", "spółka", "nie jest jedną z dozwolonych"),
    ],
)
def test_check_field(faktura, path, value, want, error) -> None:
    got, err = validate.check_field(faktura.pola[path], value)
    assert got == want and type(got) is type(want)
    assert (err is None) if error is None else (error in err)


def test_check_reports_concrete_paths(faktura) -> None:
    data = {"Faktura": {"numer": "FV/1/2031"}, "Nabywcy": [{"nip": "1234567890"}, {"nip": "12"}]}
    out, errors = validate.check(faktura, data)
    assert out["Nabywcy"][0]["nip"] == "1234567890"
    assert validate.error_lines(errors) == [
        "`Nabywcy[1].nip`: wartość '12' nie pasuje do formatu `^\\d{10}$`"
    ]
