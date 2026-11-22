"""Tests for the GUI config wizard ("Nowa klasa": gui_wizard.py + /api/wizard/*)."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest
import yaml

from json4win import config, gui, gui_wizard, llm, ocr


def _http_request(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    req = Request(url, data=body, method=method, headers=headers or {})
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except HTTPError as err:
        return err.code, {k.lower(): v for k, v in err.headers.items()}, err.read()


def _http_json(
    url: str,
    *,
    method: str = "GET",
    payload: Any = None,
) -> tuple[int, Any]:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    status, _, raw = _http_request(url, method=method, body=body, headers=headers)
    return status, json.loads(raw.decode("utf-8"))


@pytest.fixture()
def wizard_server(tmp_path: Path) -> Iterator[tuple[gui.GuiServer, Path, Path, Path, Path]]:
    inp = tmp_path / "input"
    out = tmp_path / "output"
    wiz_dir = tmp_path / "wizard_work"
    cfg_dir = tmp_path / "saved_configs"
    inp.mkdir()
    out.mkdir()
    server = gui.create_server(inp, out, port=0, wizard_dir=wiz_dir, config_dir=cfg_dir)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    try:
        yield server, inp, out, wiz_dir, cfg_dir
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def _upload_pdf(
    server: gui.GuiServer, filename: str, data: bytes = b"%PDF-1.4\n%%EOF\n"
) -> tuple[int, dict[str, Any]]:
    url = f"{server.url}/api/wizard/upload?filename={quote(filename, safe='')}"
    status, _, raw = _http_request(
        url,
        method="POST",
        body=data,
        headers={"Content-Type": "application/pdf"},
    )
    return status, json.loads(raw.decode("utf-8"))


def test_serves_wizard_ui_offline_and_nav_link(
    wizard_server: tuple[gui.GuiServer, Path, Path, Path, Path],
) -> None:
    server, _, _, _, _ = wizard_server

    # Main GUI still has its content plus link to /wizard
    st_idx, _, idx_bytes = _http_request(f"{server.url}/")
    assert st_idx == 200
    assert 'href="/wizard"' in idx_bytes.decode("utf-8")

    # Wizard HTML/CSS/JS served offline with no external URLs
    st_w, hdr_w, html_bytes = _http_request(f"{server.url}/wizard")
    assert st_w == 200
    assert "text/html" in hdr_w["content-type"]
    html = html_bytes.decode("utf-8")
    assert "Nowa klasa" in html
    assert "Przykłady PDF" in html
    assert "Kształt JSON" in html
    assert "Konfiguracja YAML" in html
    assert "http://" not in html and "https://" not in html

    for path, expected_ct in [
        ("/static/ui.css", "text/css"),
        ("/static/wizard.js", "application/javascript"),
    ]:
        st, hdrs, data = _http_request(f"{server.url}{path}")
        assert st == 200
        assert expected_ct in hdrs["content-type"]
        text = data.decode("utf-8")
        assert "http://" not in text and "https://" not in text


def test_wizard_prompt_templates_exist_and_mention_d9() -> None:
    for name in ("kreator_szablon", "kreator_podglad", "kreator_yaml"):
        p = config.CONFIG_DIR / f"prompt_{name}.md"
        assert p.is_file()
        assert len(p.read_text(encoding="utf-8")) > 100
    yaml_tpl = (config.CONFIG_DIR / "prompt_kreator_yaml.md").read_text(encoding="utf-8")
    assert "zmyślone" in yaml_tpl
    assert "NIGDY nie kopiuj" in yaml_tpl
    # Loader still ignores prompt_kreator_*.md
    classes = config.load_classes()
    assert "prompt_kreator_yaml" not in classes


def test_upload_ocr_remove_reset_and_file_limit(
    wizard_server: tuple[gui.GuiServer, Path, Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, inp, out, wiz_dir, _ = wizard_server

    ocr_calls: list[tuple[str, int]] = []

    def fake_page_count(pdf: Path) -> int:
        return 4 if "wielo" in pdf.name else 1

    def fake_ocr_page(pdf: Path, index: int) -> str:
        ocr_calls.append((pdf.name, index))
        return f"Tekst OCR pliku {pdf.name} strona {index + 1}"

    monkeypatch.setattr(ocr, "page_count", fake_page_count)
    monkeypatch.setattr(ocr, "ocr_page", fake_ocr_page)

    st1, f1 = _upload_pdf(server, "protokół wielostronicowy.pdf")
    assert st1 == 201
    st2, f2 = _upload_pdf(server, "krótki skan.pdf")
    assert st2 == 201

    # Uploads must NOT touch input/ or output/
    assert list(inp.rglob("*")) == []
    assert list(out.rglob("*")) == []
    assert len(list(wiz_dir.rglob("*.pdf"))) == 2

    # Run OCR with max_pages=2 -> 2 pages for 4-page PDF, 1 page for 1-page PDF
    st_ocr, ocr_res = _http_json(
        f"{server.url}/api/wizard/ocr",
        method="POST",
        payload={"max_pages": 2},
    )
    assert st_ocr == 200
    assert ocr_res["max_pages"] == 2
    by_id = {f["doc_id"]: f for f in ocr_res["files"]}
    assert by_id[f1["doc_id"]]["total_pages"] == 4
    assert [p["page"] for p in by_id[f1["doc_id"]]["pages"]] == [1, 2]
    assert "strona 2" in by_id[f1["doc_id"]]["pages"][1]["text"]
    assert by_id[f2["doc_id"]]["total_pages"] == 1
    assert [p["page"] for p in by_id[f2["doc_id"]]["pages"]] == [1]
    assert ocr_calls == [
        ("protokół wielostronicowy.pdf", 0),
        ("protokół wielostronicowy.pdf", 1),
        ("krótki skan.pdf", 0),
    ]

    # Enforce 5-file limit
    for i in range(3, 6):
        st, _ = _upload_pdf(server, f"doc_{i}.pdf")
        assert st == 201
    st6, err6 = _upload_pdf(server, "doc_6.pdf")
    assert st6 == 400
    assert "Maksymalnie 5" in err6["error"]

    # Remove one file and reset session
    st_rm, snap_rm = _http_json(
        f"{server.url}/api/wizard/remove", method="POST", payload={"doc_id": f1["doc_id"]}
    )
    assert st_rm == 200
    assert len(snap_rm["files"]) == 4

    st_rst, snap_rst = _http_json(f"{server.url}/api/wizard/reset", method="POST", payload={})
    assert st_rst == 200
    assert snap_rst["files"] == []
    assert list(wiz_dir.rglob("*.pdf")) == []


@pytest.mark.parametrize(
    ("filename", "body"),
    [
        ("../evil.pdf", b"%PDF-1.4\n"),
        ("sub/evil.pdf", b"%PDF-1.4\n"),
        ("sub\\evil.pdf", b"%PDF-1.4\n"),
        ("/etc/passwd", b"%PDF-1.4\n"),
        ("notes.txt", b"plain text"),
        (".pdf", b"%PDF-1.4\n"),
        ("bad:name.pdf", b"%PDF-1.4\n"),
        ("trailing..pdf.", b"%PDF-1.4\n"),
        ("empty.pdf", b""),
        ("..", b"%PDF-1.4\n"),
    ],
)
def test_wizard_upload_path_safety(
    wizard_server: tuple[gui.GuiServer, Path, Path, Path, Path],
    filename: str,
    body: bytes,
) -> None:
    server, _, _, wiz_dir, _ = wizard_server
    status, res = _upload_pdf(server, filename, data=body)
    assert status == 400
    assert "error" in res
    assert list(wiz_dir.rglob("*")) == []


def test_wizard_dir_cannot_be_inside_output_or_input(tmp_path: Path) -> None:
    inp = tmp_path / "input"
    out = tmp_path / "output"
    inp.mkdir()
    out.mkdir()
    with pytest.raises(gui_wizard.WizardError):
        gui_wizard.WizardState(wizard_dir=out / "sub", forbidden_dirs=(out, inp))
    with pytest.raises(gui_wizard.WizardError):
        gui_wizard.WizardState(wizard_dir=inp / "sub", forbidden_dirs=(out, inp))


def test_propose_szablon_preview_and_llm_error_keeps_editor(
    wizard_server: tuple[gui.GuiServer, Path, Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _, _, _, _ = wizard_server
    huge_text = "A" * (gui_wizard.MAX_CHARS_PER_DOC + 5000)

    monkeypatch.setattr(ocr, "page_count", lambda _p: 1)
    monkeypatch.setattr(
        ocr,
        "ocr_page",
        lambda pdf, _idx: f"FAKTURA NR FV/10/2031 KWOTA 1200,50\n{huge_text}"
        if pdf.name == "a.pdf"
        else "FAKTURA NR FV/11/2031 KWOTA 300,00",
    )

    _upload_pdf(server, "a.pdf")
    _upload_pdf(server, "b.pdf")
    st_ocr, _ = _http_json(f"{server.url}/api/wizard/ocr", method="POST", payload={"max_pages": 2})
    assert st_ocr == 200

    seen_prompts: list[str] = []

    def fake_chat_json(_model: str, messages: list[dict], **_kw: Any) -> dict[str, Any]:
        seen_prompts.append(messages[0]["content"])
        if (
            "kreator" not in messages[0]["content"]
            and "podglady" in messages[1]["content"]
            and "szablon" not in messages[1]["content"]
        ):
            # refresh preview call
            return {
                "podglady": [
                    {
                        "plik": "a.pdf",
                        "dane": {
                            "faktura": {"numer": "FV/10/2031", "pozycje": [{"opis": "Usługa"}]}
                        },
                    },
                    {
                        "plik": "b.pdf",
                        "dane": {
                            "faktura": {"numer": "FV/11/2031", "pozycje": [{"opis": "Towar"}]}
                        },
                    },
                ]
            }
        return {
            "szablon": {
                "faktura": {
                    "numer": None,
                    "kwota": "nie_null_od_llm",  # must be coerced to None
                }
            },
            "typy": {"faktura.numer": "str", "faktura.kwota": "float"},
            "podglady": [
                {"plik": "a.pdf", "dane": {"faktura": {"numer": "FV/10/2031", "kwota": 1200.5}}},
                {"plik": "b.pdf", "dane": {"faktura": {"numer": "FV/11/2031", "kwota": 300.0}}},
            ],
        }

    monkeypatch.setattr(llm, "chat_json", fake_chat_json)

    st, res = _http_json(
        f"{server.url}/api/wizard/propose-szablon",
        method="POST",
        payload={"hint": "faktury VAT"},
    )
    assert st == 200
    assert res["szablon"] == {"faktura": {"numer": None, "kwota": None}}
    assert res["typy"] == {"faktura.numer": "str", "faktura.kwota": "float"}
    assert len(res["previews"]) == 2
    assert res["previews"][0]["data"]["faktura"]["kwota"] == 1200.5
    # Verify bounded input truncation happened
    assert "ucięto ze względu na limit znaków" in seen_prompts[0]
    assert len(seen_prompts[0]) < gui_wizard.MAX_TOTAL_CHARS + 4000

    # Refresh preview with edited shape (added list)
    edited_szablon = {"faktura": {"numer": None, "pozycje": [{"opis": None}]}}
    edited_typy = {"faktura.numer": "str", "faktura.pozycje[].opis": "str"}
    st_prev, prev_res = _http_json(
        f"{server.url}/api/wizard/preview",
        method="POST",
        payload={"szablon": edited_szablon, "typy": edited_typy},
    )
    assert st_prev == 200
    assert prev_res["previews"][0]["data"]["faktura"]["pozycje"] == [{"opis": "Usługa"}]

    # LLM failure returns 502 and preserves existing szablon/previews in state
    def failing_chat_json(*_a: Any, **_kw: Any) -> dict[str, Any]:
        raise llm.LlmError("timeout")

    monkeypatch.setattr(llm, "chat_json", failing_chat_json)
    st_err, err_body = _http_json(
        f"{server.url}/api/wizard/propose-szablon", method="POST", payload={}
    )
    assert st_err == 502
    assert "timeout" in err_body["error"]

    st_state, snap = _http_json(f"{server.url}/api/wizard/state")
    assert st_state == 200
    assert snap["szablon"] == edited_szablon
    assert len(snap["previews"]) == 2


def test_propose_yaml_enforces_szablon_pola_consistency(
    wizard_server: tuple[gui.GuiServer, Path, Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _, _, _, _ = wizard_server
    monkeypatch.setattr(ocr, "page_count", lambda _p: 2)
    monkeypatch.setattr(
        ocr,
        "ocr_page",
        lambda _p, idx: "FAKTURA VAT\nNumer: FV/1/2031"
        if idx == 0
        else "RAZEM DO ZAPŁATY: 500,00 PLN",
    )
    _upload_pdf(server, "fv1.pdf")
    _http_json(f"{server.url}/api/wizard/ocr", method="POST", payload={"max_pages": 2})

    szablon = {
        "faktura": {
            "numer": None,
            "kwota": None,
            "pozycje": [{"nazwa": None, "ilosc": None}],
        }
    }
    typy = {
        "faktura.numer": "str",
        "faktura.kwota": "float",
        "faktura.pozycje[].nazwa": "str",
        "faktura.pozycje[].ilosc": "int",
    }

    # Fake LLM omits `faktura.pozycje[].ilosc`, adds extra bogus key, and uses reserved id
    def fake_yaml_llm(_model: str, _messages: list[dict], **_kw: Any) -> dict[str, Any]:
        return {
            "id": "inne",
            "nazwa": "Faktura VAT",
            "opis": "Faktura sprzedaży VAT z pozycjami i kwotą łączną.",
            "cechy": ["nagłówek FAKTURA VAT", "podsumowanie DO ZAPŁATY"],
            "nie_mylic_z": ["paragon fiskalny"],
            "czytanie": {
                "max_stron": 2,
                "znacznik": "(?i)DO\\s+ZAPŁATY",
                "stron_po_znaczniku": 0,
            },
            "pola": {
                "faktura.numer": {
                    "opis": "Numer faktury VAT.",
                    "typ": "str",
                    "normalizacja": "text",
                    "przyklady": ["FV/99/2031"],
                },
                "faktura.kwota": {
                    "opis": "Kwota brutto.",
                    "typ": "float",
                    "normalizacja": "amount",
                    "przyklady": [123.45],
                },
                "faktura.pozycje[].nazwa": {
                    "opis": "Nazwa pozycji na fakturze.",
                    "typ": "str",
                    "normalizacja": "text",
                },
                "faktura.nieistniejace_pole": {"opis": "powinno zostać usunięte"},
            },
            "instrukcje": "Czytaj wszystkie pozycje w kolejności z tabeli.",
        }

    monkeypatch.setattr(llm, "chat_json", fake_yaml_llm)

    st, res = _http_json(
        f"{server.url}/api/wizard/propose-yaml",
        method="POST",
        payload={"szablon": szablon, "typy": typy},
    )
    assert st == 200
    val = res["validation"]
    assert val["valid"] is True, val["errors"]
    assert val["id"] != "inne"

    parsed = yaml.safe_load(res["yaml_text"])
    assert parsed["szablon"] == szablon
    # Every szablon leaf has an entry in pola, and no extra keys remain
    expected_leaves = config.leaf_paths(szablon)
    assert list(parsed["pola"].keys()) == expected_leaves
    assert parsed["pola"]["faktura.pozycje[].ilosc"]["typ"] == "int"
    assert "faktura.nieistniejace_pole" not in parsed["pola"]

    # Live marker test matched page 2!
    marker = val["marker"]
    assert marker is not None
    assert marker["results"][0]["matched"] is True
    assert marker["results"][0]["first_match_page"] == 2
    assert marker["results"][0]["would_stop_after_page"] == 2


def test_validate_yaml_reports_line_numbers_for_syntax_and_config_errors(
    wizard_server: tuple[gui.GuiServer, Path, Path, Path, Path],
) -> None:
    server, _, _, _, _ = wizard_server

    # 1. Broken YAML syntax
    st_syn, res_syn = _http_json(
        f"{server.url}/api/wizard/validate",
        method="POST",
        payload={"yaml_text": "id: test_cls\nnazwa: [niezamknieta lista\n"},
    )
    assert st_syn == 200
    assert res_syn["valid"] is False
    assert res_syn["errors"][0]["line"] is not None

    # 2. Valid YAML syntax, broken config.py rule (invalid regex in format)
    bad_regex_yaml = """\
id: test_cls
nazwa: Testowa
opis: Opis klasy.
czytanie:
  max_stron: 2
szablon:
  dok:
    kod: null
pola:
  dok.kod:
    opis: Kod dokumentu.
    typ: str
    format: '^([0-9+$'
"""
    st_cfg, res_cfg = _http_json(
        f"{server.url}/api/wizard/validate",
        method="POST",
        payload={"yaml_text": bad_regex_yaml},
    )
    assert st_cfg == 200
    assert res_cfg["valid"] is False
    assert res_cfg["errors"][0]["key"] == "pola.dok.kod.format"
    assert res_cfg["errors"][0]["line"] == 13

    # 3. Missing pola entry for template leaf
    missing_leaf_yaml = """\
id: test_cls
nazwa: Testowa
opis: Opis klasy.
czytanie:
  max_stron: 1
szablon:
  dok:
    a: null
    b: null
pola:
  dok.a:
    opis: Pole A.
"""
    st_leaf, res_leaf = _http_json(
        f"{server.url}/api/wizard/validate",
        method="POST",
        payload={"yaml_text": missing_leaf_yaml},
    )
    assert st_leaf == 200
    assert res_leaf["valid"] is False
    assert "dok.b" in res_leaf["errors"][0]["message"]
    assert res_leaf["errors"][0]["line"] == 10

    # 4. Path traversal in id rejected
    traversal_yaml = bad_regex_yaml.replace("id: test_cls", "id: ../escape")
    st_tr, res_tr = _http_json(
        f"{server.url}/api/wizard/validate",
        method="POST",
        payload={"yaml_text": traversal_yaml},
    )
    assert st_tr == 200
    assert res_tr["valid"] is False
    assert res_tr["errors"][0]["key"] == "id"


def test_draft_pipeline_test_and_save_overwrite_protection(
    wizard_server: tuple[gui.GuiServer, Path, Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _, _, _, cfg_dir = wizard_server

    monkeypatch.setattr(ocr, "page_count", lambda _p: 2)
    monkeypatch.setattr(
        ocr,
        "ocr_page",
        lambda pdf, idx: (
            "NOTATKA SLUZBOWA NR NS/07/2031\nDATA: 15.05.2031"
            if pdf.name == "notatka.pdf" and idx == 0
            else "PODPIS: Jan Nowak"
            if pdf.name == "notatka.pdf"
            else "LOSOWA ULOTKA REKLAMOWA"
        ),
    )

    _upload_pdf(server, "notatka.pdf")
    _upload_pdf(server, "ulotka.pdf")
    _http_json(f"{server.url}/api/wizard/ocr", method="POST", payload={"max_pages": 2})

    draft_yaml = """\
id: notatka_sluzbowa
nazwa: Notatka służbowa
opis: Wewnętrzna notatka służbowa z numerem, datą i podpisem autora.
czytanie:
  max_stron: 2
  znacznik: '(?i)PODPIS:'
  stron_po_znaczniku: 0
szablon:
  notatka:
    numer: null
    data: null
    autor: null
pola:
  notatka.numer:
    opis: Numer notatki służbowej.
    typ: str
    normalizacja: text
    format: '^NS/\\d+/\\d{4}$'
    przyklady: ["NS/12/2031"]
  notatka.data:
    opis: Data notatki w formacie RRRR-MM-DD.
    typ: str
    normalizacja: date
    format: '^\\d{4}-\\d{2}-\\d{2}$'
    przyklady: ["2031-04-17"]
  notatka.autor:
    opis: Imię i nazwisko autora w mianowniku, bez tytułów.
    typ: str
    normalizacja: text
    przyklady: ["Anna Kowalska"]
"""

    def fake_chat_json(
        _model: str, messages: list[dict], *, role: str | None = None, **_kw: Any
    ) -> dict[str, Any]:
        user_text = messages[-1]["content"]
        if role == "decision":
            return (
                {"klasa": "notatka_sluzbowa"}
                if "NOTATKA SLUZBOWA" in user_text
                else {"klasa": "inne"}
            )
        return {
            "notatka": {
                "numer": "NS/07/2031",
                "data": "15.05.2031",  # date normalizer converts to 2031-05-15
                "autor": "Jan Nowak",
            }
        }

    monkeypatch.setattr(llm, "chat_json", fake_chat_json)

    # 1. Run real pipeline test on uploaded examples
    st_test, test_res = _http_json(
        f"{server.url}/api/wizard/test",
        method="POST",
        payload={"yaml_text": draft_yaml},
    )
    assert st_test == 200
    assert test_res["class_id"] == "notatka_sluzbowa"
    by_name = {r["filename"]: r for r in test_res["results"]}
    assert by_name["notatka.pdf"]["decision"] == "notatka_sluzbowa"
    assert by_name["notatka.pdf"]["matched_draft"] is True
    assert by_name["notatka.pdf"]["pages_read"] == 2
    assert by_name["notatka.pdf"]["data"] == {
        "notatka": {
            "numer": "NS/07/2031",
            "data": "2031-05-15",
            "autor": "Jan Nowak",
        }
    }
    assert by_name["notatka.pdf"]["nulled"] == []
    assert by_name["ulotka.pdf"]["decision"] == "inne"
    assert by_name["ulotka.pdf"]["matched_draft"] is False
    assert by_name["ulotka.pdf"]["data"] == {}

    # 2. Save new class YAML
    st_save, save_res = _http_json(
        f"{server.url}/api/wizard/save",
        method="POST",
        payload={"yaml_text": draft_yaml, "overwrite": False},
    )
    assert st_save == 201
    saved_path = cfg_dir / "notatka_sluzbowa.yaml"
    assert saved_path.is_file()
    assert save_res["id"] == "notatka_sluzbowa"

    # Verify saved file loads with the existing config loader with zero code changes!
    loaded = config.load_class(saved_path)
    assert loaded.id == "notatka_sluzbowa"
    assert list(loaded.pola.keys()) == ["notatka.numer", "notatka.data", "notatka.autor"]

    # 3. Second save without overwrite=True MUST fail with 409 Conflict and not overwrite
    modified_yaml = draft_yaml.replace("Notatka służbowa", "Zmieniona nazwa")
    st_dup, dup_res = _http_json(
        f"{server.url}/api/wizard/save",
        method="POST",
        payload={"yaml_text": modified_yaml, "overwrite": False},
    )
    assert st_dup == 409
    assert dup_res["exists"] is True
    assert "Notatka służbowa" in saved_path.read_text(encoding="utf-8")

    # 4. Explicit overwrite=True succeeds
    st_ow, ow_res = _http_json(
        f"{server.url}/api/wizard/save",
        method="POST",
        payload={"yaml_text": modified_yaml, "overwrite": True},
    )
    assert st_ow == 201
    assert ow_res["saved"] is True
    assert config.load_class(saved_path).nazwa == "Zmieniona nazwa"

    # 5. Save refuses invalid YAML
    st_bad, _ = _http_json(
        f"{server.url}/api/wizard/save",
        method="POST",
        payload={"yaml_text": "id: bad_cls\n", "overwrite": True},
    )
    assert st_bad == 400
    assert not (cfg_dir / "bad_cls.yaml").exists()


def test_target_config_dir_uses_first_entry_of_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d1 = tmp_path / "dir_one"
    d2 = tmp_path / "dir_two"
    d1.mkdir()
    d2.mkdir()
    monkeypatch.setenv("JSON4WIN_CONFIG_DIRS", f"{d1}{os.pathsep}{d2}")
    assert gui_wizard.target_config_dir() == d1.resolve()

    monkeypatch.delenv("JSON4WIN_CONFIG_DIRS", raising=False)
    assert gui_wizard.target_config_dir() == config.CONFIG_DIR.resolve()
