from pathlib import Path

import pytest

from json4win import decide, llm, ocr, pipeline
from json4win.config import Reading
from tests.fakes import FakeLlm


class FakeOcr:
    def __init__(self, pages: list[str]) -> None:
        self.pages, self.read = pages, []

    def page_count(self, pdf: Path) -> int:
        return len(self.pages)

    def ocr_page(self, pdf: Path, index: int) -> str:
        self.read.append(index)
        return self.pages[index]


@pytest.fixture
def fake_ocr(monkeypatch):
    def install(pages):
        f = FakeOcr(pages)
        monkeypatch.setattr(ocr, "page_count", f.page_count)
        monkeypatch.setattr(ocr, "ocr_page", f.ocr_page)
        return f

    return install


@pytest.fixture(autouse=True)
def _prompts(monkeypatch, config_dir):
    monkeypatch.setattr("json4win.prompts.CONFIG_DIR", config_dir)


def _cls(faktura, **reading):
    from dataclasses import replace

    return replace(faktura, czytanie=Reading(**reading))


PAGES = ["Faktura VAT", "Do zapłaty: 100 zł", "warunki", "załącznik", "koniec"]


@pytest.mark.parametrize(
    "reading, pages, want_read",
    [
        (dict(max_stron=5, znacznik="(?i)do zapłaty", stron_po_znaczniku=1), PAGES, 3),
        (dict(max_stron=5, znacznik="(?i)do zapłaty", stron_po_znaczniku=0), PAGES, 2),
        (dict(max_stron=5, znacznik="(?i)faktura", stron_po_znaczniku=0), PAGES, 1),
        (dict(max_stron=4, znacznik="(?i)nie ma tego", stron_po_znaczniku=1), PAGES, 4),
        (dict(max_stron=5, znacznik="(?i)do zapłaty", stron_po_znaczniku=9), PAGES, 5),
        (dict(max_stron=9), PAGES[:2], 2),  # never beyond the page count
        (dict(max_stron=1, znacznik="x"), PAGES, 1),
    ],
)
def test_reading_by_marker(fake_ocr, faktura, reading, pages, want_read) -> None:
    f = fake_ocr(pages)
    got = decide.read_pages(Path("a.pdf"), _cls(faktura, **reading), pages[0])
    assert got == pages[:want_read]
    assert f.read == list(range(1, want_read))  # page 1 was already read for the decision


def test_reading_by_question(monkeypatch, fake_ocr, faktura) -> None:
    fake_ocr(PAGES)
    llm_fake = FakeLlm({"kompletny": False}, {"kompletny": "true"})
    monkeypatch.setattr(llm, "chat_json", llm_fake)
    c = _cls(faktura, max_stron=5, kompletny_gdy="Tekst zawiera warunki.")
    # asked after page 1 (no) and page 2 (yes): 2 pages read
    assert decide.read_pages(Path("a.pdf"), c, PAGES[0]) == PAGES[:2]
    assert len(llm_fake.calls) == 2
    assert "Tekst zawiera warunki." in llm_fake.calls[0][1][0]["content"]


def test_question_used_when_marker_does_not_match(monkeypatch, fake_ocr, faktura) -> None:
    fake_ocr(PAGES)
    monkeypatch.setattr(llm, "chat_json", FakeLlm({"kompletny": True}))
    c = _cls(faktura, max_stron=5, znacznik="nie ma tego", kompletny_gdy="Czy jest koniec?")
    assert decide.read_pages(Path("a.pdf"), c, PAGES[0]) == PAGES[:1]


@pytest.mark.parametrize(
    "answer, want",
    [
        ("faktura", "faktura"),
        (" `faktura` ", "faktura"),
        ("inne", None),
        ("rachunek", None),
        (None, None),
    ],
)
def test_classify(monkeypatch, config_dir, answer, want) -> None:
    from json4win import config

    classes = config.load_classes(config_dir)
    fake = FakeLlm({"klasa": answer})
    monkeypatch.setattr(llm, "chat_json", fake)
    assert decide.classify("Faktura VAT nr FV/1/2031", classes) == want
    system = fake.calls[0][1][0]["content"]
    assert "`faktura`: Faktura VAT." in system and '"faktura", "inne"' in system


@pytest.fixture
def pipeline_classes(monkeypatch, config_dir):
    from json4win import config

    monkeypatch.setattr(pipeline, "classes", lambda: config.load_classes(config_dir))


def test_pipeline_inne_after_one_page(monkeypatch, fake_ocr, pipeline_classes) -> None:
    f = fake_ocr(PAGES)
    monkeypatch.setattr(llm, "chat_json", FakeLlm({"klasa": "inne"}))
    assert pipeline.process_document(Path("a.pdf")) == {}
    assert f.read == [0]


def test_pipeline_end_to_end(monkeypatch, fake_ocr, pipeline_classes) -> None:
    from json4win import normalize
    from tests.fakes import fake_normalize

    monkeypatch.setattr(normalize, "normalize", fake_normalize)
    f = fake_ocr(PAGES)
    answer = {"Faktura": {"numer": "FV/1/2031", "kwota": "100"}, "Nabywcy": [{"nazwa": "Alfa"}]}
    fake = FakeLlm({"klasa": "faktura"}, answer)
    monkeypatch.setattr(llm, "chat_json", fake)
    out = pipeline.process_document(Path("a.pdf"))
    assert f.read == [0, 1, 2]
    assert out == {
        "Faktura": {"numer": "FV/1/2031", "data": None, "kwota": 100.0, "pozycje": None},
        "Nabywcy": [{"nazwa": "Alfa", "nip": None, "typ": None}],
    }


def test_pipeline_ocr_cache_miss_propagates(monkeypatch, pipeline_classes) -> None:
    def miss(pdf, index):
        raise ocr.OcrCacheMiss("not cached")

    monkeypatch.setattr(ocr, "ocr_page", miss)
    with pytest.raises(ocr.OcrCacheMiss):
        pipeline.process_document(Path("a.pdf"))
