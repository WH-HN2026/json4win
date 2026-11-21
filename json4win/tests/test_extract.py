import pytest
from tests.fakes import FakeLlm, fail, fake_normalize

from json4win import extract, llm, normalize

GOOD = {
    "Faktura": {"numer": "FV/12/2031", "data": "17.04.2031", "kwota": "100,00", "pozycje": 1},
    "Nabywcy": [{"nazwa": "Alfa", "nip": "1234567890", "typ": "firma"}],
}
WANT = {
    "Faktura": {"numer": "FV/12/2031", "data": "2031-04-17", "kwota": 100.0, "pozycje": 1},
    "Nabywcy": [{"nazwa": "Alfa", "nip": "1234567890", "typ": "firma"}],
}


def _with(base: dict, **faktura) -> dict:
    return {"Faktura": base["Faktura"] | faktura, "Nabywcy": base["Nabywcy"]}


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    monkeypatch.setattr(normalize, "normalize", fake_normalize)
    monkeypatch.delenv("LLM_VALIDATION_RETRIES", raising=False)


def _run(monkeypatch, faktura, *answers):
    fake = FakeLlm(*answers)
    monkeypatch.setattr(llm, "chat_json", fake)
    monkeypatch.setattr("json4win.prompts.CONFIG_DIR", faktura.source.parent)
    return extract.extract(faktura, ["Faktura VAT nr FV/12/2031", "Do zapłaty 100,00 zł"]), fake


def test_valid_first_time(monkeypatch, faktura) -> None:
    r, fake = _run(monkeypatch, faktura, GOOD)
    assert (r.data, r.retries, r.nulled) == (WANT, 0, [])
    system, user = fake.calls[0][1]
    assert "=== strona 2 ===\nDo zapłaty 100,00 zł" in user["content"]
    assert "`Faktura.numer`" in system["content"]


def test_invalid_then_valid(monkeypatch, faktura) -> None:
    bad = _with(GOOD, numer="FV-12", pozycje=7)
    # The retry also changes a field that was valid: only the invalid ones are taken from it.
    fixed = _with(GOOD, numer="FV/12/2031", pozycje=1, kwota="999,00")
    r, fake = _run(monkeypatch, faktura, bad, fixed)
    assert (r.data, r.retries, r.nulled) == (WANT, 1, [])
    retry = fake.calls[1][1]
    assert [m["role"] for m in retry] == ["system", "user", "assistant", "user"]
    assert "`Faktura.numer`" in retry[3]["content"] and "`Faktura.pozycje`" in retry[3]["content"]


def test_still_invalid_is_nulled(monkeypatch, faktura) -> None:
    bad = _with(GOOD, numer="FV-12")
    r, fake = _run(monkeypatch, faktura, bad, bad, bad)
    assert r.retries == 2 and r.nulled == ["Faktura.numer"]
    assert r.data == _with(WANT, numer=None)
    assert len(fake.calls) == 3


def test_retry_count_from_env_and_failed_retry(monkeypatch, faktura) -> None:
    monkeypatch.setenv("LLM_VALIDATION_RETRIES", "0")
    r, _ = _run(monkeypatch, faktura, _with(GOOD, numer="x"))
    assert r.retries == 0 and r.nulled == ["Faktura.numer"]
    monkeypatch.setenv("LLM_VALIDATION_RETRIES", "2")
    r, _ = _run(monkeypatch, faktura, _with(GOOD, numer="x"), fail())
    assert r.retries == 1 and r.data["Faktura"]["numer"] is None


def test_first_call_failure_raises(monkeypatch, faktura) -> None:
    with pytest.raises(llm.LlmError):
        _run(monkeypatch, faktura, fail())
