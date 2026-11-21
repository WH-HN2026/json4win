import json
from pathlib import Path

import pytest

from json4win import config, env, llm, ocr, pipeline, trace
from json4win.cli import main
from tests.fakes import FakeLlm, fail

PAGES = {
    "faktura.pdf": [
        "FAKTURA VAT nr FV/12/2031\nData wystawienia: 17.04.2031\n"
        "Nabywca: Alfa Sp. z o.o., ul. Polna 3\nNIP 123-456-78-90",
        "Pozycje: 1\nDo zapłaty: 100,00 zł\nDziękujemy.",
    ],
    "inne.pdf": ["Ulotka: promocja na kawę"],
    "zły dokument.pdf": ["Faktura?"],
}
EXTRACTED = {
    "Faktura": {"numer": "FV-12", "data": "17.04.2031", "kwota": "100,00 zł", "pozycje": 1},
    "Nabywcy": [
        {"nazwa": "Alfa Sp z o.o.", "nip": "1234567890", "typ": "firma"},
        {"nazwa": "Zeta Logistyka", "nip": None, "typ": "firma"},
    ],
}


class FakeOcr:
    def page_count(self, pdf: Path) -> int:
        return len(PAGES[pdf.name])

    def ocr_page(self, pdf: Path, index: int) -> str:
        return PAGES[pdf.name][index]


@pytest.fixture
def app(monkeypatch, config_dir, tmp_path):
    """Fake OCR + scripted LLM; three PDFs in one case: faktura, an "inne" leaflet, a failure."""
    classes = config.load_classes(config_dir)
    monkeypatch.setattr(pipeline, "classes", lambda: classes)
    monkeypatch.setattr("json4win.prompts.CONFIG_DIR", config_dir)
    monkeypatch.setattr(env, "load_env", lambda path=None: None)
    monkeypatch.setenv("LLM_VALIDATION_RETRIES", "2")
    f = FakeOcr()
    monkeypatch.setattr(ocr, "page_count", f.page_count)
    monkeypatch.setattr(ocr, "ocr_page", f.ocr_page)
    # sorted order: faktura.pdf, inne.pdf, zły dokument.pdf
    fake = FakeLlm(
        {"klasa": "faktura"},
        EXTRACTED,
        EXTRACTED,
        EXTRACTED,  # numer stays invalid -> null after 2 retries
        {"klasa": "inne"},
        fail(),
    )
    monkeypatch.setattr(llm, "chat_json", fake)
    inp, out = tmp_path / "input", tmp_path / "output"
    for name in PAGES:
        (inp / "sprawa 1").mkdir(parents=True, exist_ok=True)
        (inp / "sprawa 1" / name).write_bytes(b"%PDF-1.4 " + name.encode())
    return inp, out


def _files(d: Path) -> list[str]:
    return sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file())


def _load(tdir: Path, name: str) -> dict:
    return json.loads((tdir / "sprawa 1" / f"{name}.trace.json").read_text(encoding="utf-8"))


def test_traces_written_outside_output(app, tmp_path) -> None:
    inp, out = app
    tdir = tmp_path / "ślady"
    assert (
        main(["--input", str(inp), "--output", str(out), "--trace", str(tdir)]) == 1
    )  # one failed

    assert _files(out) == [f"sprawa 1/{Path(n).stem}.json" for n in sorted(PAGES)]
    assert _files(tdir) == sorted(
        f"sprawa 1/{Path(n).stem}.trace{s}" for n in PAGES for s in (".json", ".md")
    )

    t = _load(tdir, "faktura")
    assert t["pdf"] == "sprawa 1/faktura.pdf" and len(t["sha256"]) == 64
    assert t["status"] == "ok" and t["class"] == "faktura"
    assert t["decision"]["class"] == "faktura" and t["decision_llm_calls"] == 1
    assert [p["page"] for p in t["ocr_pages"]] == [1, 2]
    assert set(t["steps_s"]) == {"ocr", "decyzja", "czytanie", "ekstrakcja", "pochodzenie"}
    ex = t["extraction"]
    assert (ex["llm_calls"], ex["retries"], ex["nulled"]) == (3, 2, ["Faktura.numer"])
    assert len(ex["validation_errors"]) == 3 and "Faktura.numer" in ex["validation_errors"][2][0]
    assert t["result"] == json.loads((out / "sprawa 1" / "faktura.json").read_text("utf-8"))

    f = {x["field"]: x for x in t["fields"]}
    data = f["Faktura.data"]
    assert (data["value"], data["raw"], data["normalizer"]) == ("2031-04-17", "17.04.2031", "date")
    assert data["method"] == trace.METHOD_NORM
    assert data["provenance"]["page"] == 1 and "17.04.2031" in data["provenance"]["snippet"]
    kwota = f["Faktura.kwota"]["provenance"]
    assert kwota["page"] == 2 and "100,00 zł" in kwota["snippet"]
    nip = f["Nabywcy[0].nip"]  # digits-only comparison across separators
    assert nip["method"] == trace.METHOD_LLM
    assert nip["provenance"]["score"] == 1.0 and "123-456-78-90" in nip["provenance"]["snippet"]
    assert f["Nabywcy[0].nazwa"]["provenance"]["page"] == 1
    assert f["Nabywcy[1].nazwa"]["provenance"] == {"status": trace.NOT_FOUND}
    assert f["Nabywcy[1].nip"]["provenance"] is None
    assert f["Faktura.pozycje"]["provenance"] == {"status": trace.FROM_LIST}
    numer = f["Faktura.numer"]
    assert (numer["value"], numer["raw"], numer["method"]) == (None, "FV-12", trace.METHOD_NULLED)

    md = (tdir / "sprawa 1" / "faktura.trace.md").read_text(encoding="utf-8")
    assert "| pole | wartość | strona | fragment | metoda |" in md
    assert "| Nabywcy[1].nazwa | Zeta Logistyka | — | nie znaleziono w tekście | llm |" in md
    assert "walidacja→null" in md

    other = _load(tdir, "inne")
    assert (other["class"], other["result"], other["status"]) == ("inne", {}, "ok")
    assert "fields" not in other

    bad = _load(tdir, "zły dokument")
    assert bad["status"] == "error"
    assert bad["error"] == {"type": "LlmError", "message": "fake failure", "step": "decyzja"}
    assert "Błąd" in (tdir / "sprawa 1" / "zły dokument.trace.md").read_text(encoding="utf-8")


def test_default_dir_from_env_and_no_trace(app, _trace_dir) -> None:
    inp, out = app
    assert main(["--input", str(inp), "--output", str(out), "--no-trace"]) == 1
    assert not _trace_dir.exists()
    assert len(_files(out)) == 3


def test_default_dir_from_env(app, _trace_dir) -> None:
    inp, out = app
    main(["--input", str(inp), "--output", str(out)])
    assert (_trace_dir / "sprawa 1" / "faktura.trace.json").is_file()


def test_trace_dir_inside_output_is_refused(app) -> None:
    inp, out = app
    with pytest.raises(SystemExit):
        main(["--input", str(inp), "--output", str(out), "--trace", str(out / "t")])


def test_failure_trace_has_no_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "sk-very-secret-123")
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    path = tmp_path / "t" / "a.trace.json"
    with pytest.raises(RuntimeError), trace.document(pdf, path):
        with trace.step("ekstrakcja"):
            raise RuntimeError("HTTP 401 for key sk-very-secret-123")
    body = path.read_text(encoding="utf-8")
    assert "sk-very-secret" not in body and "***" in body
    assert json.loads(body)["error"]["step"] == "ekstrakcja"


def test_hooks_are_noops_without_a_trace(tmp_path) -> None:
    trace.put("x", 1)
    trace.add("y", 2)
    trace.count("z")
    with trace.step("s"):
        pass
    with trace.document(tmp_path / "missing.pdf", None) as t:
        assert t is None


@pytest.mark.parametrize(
    "needle, pages, digits, want_page, min_score",
    [
        (
            "61 1090 1014 0000 0712 1981 2874",
            ["x", "Rachunek 61109010140000071219812874."],
            1,
            2,
            1,
        ),
        ("1500.5", ["Kwota: 1 500,50 PLN"], 1, 1, 1),
        ("Przedsiębiorstwo Handlowe", ["Odwołujący: PRZEDSIEBIORSTWO Hand1owe sp.j."], 0, 1, 0.75),
        ("Jan Kowalski", ["Pełnomocnik:\n  jan\n kowalski, adwokat"], 0, 1, 1),
    ],
)
def test_locate_found(needle, pages, digits, want_page, min_score) -> None:
    got = trace.locate(needle, pages, bool(digits))
    assert got["status"] == "found" and got["page"] == want_page and got["score"] >= min_score


@pytest.mark.parametrize(
    "needle, digits, want",
    [
        ("Nowak", False, trace.NOT_FOUND),
        ("9876543210", True, trace.NOT_FOUND),
        ("ab", False, trace.TOO_SHORT),
    ],
)
def test_locate_not_found(needle, digits, want) -> None:
    pages = ["Wnoszę odwołanie, NIP 123-456-78-90, Jan Kowalski"]
    assert trace.locate(needle, pages, digits) == {"status": want}


def test_snippet_is_bounded() -> None:
    page = "a" * 500 + " NIP 1234567890 " + "b" * 500
    got = trace.locate("1234567890", [page], True)
    assert got["snippet"].startswith("…") and got["snippet"].endswith("…")
    assert len(got["snippet"]) <= 10 + 2 * trace.SNIPPET + 2
