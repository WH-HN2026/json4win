"""Opt-in smoke test against the real LLM API: LLM_LIVE=1 pytest json4win/tests/test_live_llm.py -s

Not part of `make check` (skipped without LLM_LIVE=1). Uses the invented `faktura` class and an
invented snippet, so no training data leaves the machine.
"""

import json
import os
from pathlib import Path

import pytest

from json4win import decide, env, extract, llm, normalize
from tests.fakes import fake_normalize

pytestmark = pytest.mark.skipif(os.environ.get("LLM_LIVE") != "1", reason="set LLM_LIVE=1")

SNIPPET = """Faktura VAT nr FV/7/2031
Data wystawienia: 03.02.2031
Nabywca: Przykładowa Spółdzielnia Mleczarska, NIP 111-222-33-44
Pozycje: 1. Usługa doradcza
Do zapłaty: 1 230,00 zł"""


@pytest.fixture(autouse=True)
def _env(monkeypatch, config_dir):
    env.load_env()
    monkeypatch.setattr("json4win.prompts.CONFIG_DIR", config_dir)
    monkeypatch.setattr(normalize, "normalize", fake_normalize)


def test_live_decision(config_dir) -> None:
    from json4win import config

    classes = config.load_classes(config_dir)
    got = decide.classify(SNIPPET, classes)
    other = decide.classify("Wyrok Sądu Okręgowego w sprawie o zapłatę czynszu najmu.", classes)
    print(f"\nmodel={llm.model('decision')} faktura -> {got!r}, wyrok -> {other!r}")
    assert got == "faktura" and other is None


def test_live_extraction(faktura) -> None:
    r = extract.extract(faktura, [SNIPPET])
    print(f"\nmodel={llm.model('extract')} retries={r.retries} nulled={r.nulled}")
    print(json.dumps(r.data, ensure_ascii=False, indent=2))
    assert r.data["Faktura"]["numer"] == "FV/7/2031"
    assert r.data["Nabywcy"][0]["nip"] == "1112223344"


def test_live_length_retry(monkeypatch, tmp_path) -> None:
    """A budget too small for default reasoning forces finish_reason=length; the low-effort retry
    (and random_seed) must be accepted by the API and give an answer."""
    from json4win import trace

    monkeypatch.setenv("LLM_MAX_TOKENS", "50")
    monkeypatch.setenv("LLM_ANSWER_RETRIES", "3")
    monkeypatch.setenv("LLM_MAX_TOKENS_CAP", "400")
    messages = [{"role": "user", "content": 'Zwróć JSON {"wynik": <2+2>}'}]
    with trace.document(Path(__file__), tmp_path / "r1.trace.json") as t:
        got = llm.chat_json(llm.model("extract"), messages)
    for a in t.data["llm"][0]["attempts"]:
        print({k: a[k] for k in ("max_tokens", "reasoning_effort", "outcome", "reasoning_tokens")})
    assert got == {"wynik": 4}
