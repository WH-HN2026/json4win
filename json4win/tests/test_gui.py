"""Tests for the local web GUI (json4win.gui) and shared CLI processing hooks."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest

from json4win import cli, gui


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
def gui_server(tmp_path: Path) -> Iterator[tuple[gui.GuiServer, Path, Path]]:
    inp = tmp_path / "input"
    out = tmp_path / "output"
    inp.mkdir()
    out.mkdir()
    server = gui.create_server(inp, out, port=0)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    try:
        yield server, inp, out
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_serves_static_ui_offline(gui_server: tuple[gui.GuiServer, Path, Path]) -> None:
    server, _, _ = gui_server
    assert server.server_address[0] == "127.0.0.1"
    assert server.server_address[1] > 0

    status, headers, html_bytes = _http_request(f"{server.url}/")
    assert status == 200
    assert "text/html" in headers["content-type"]
    html = html_bytes.decode("utf-8")
    assert "Przetwórz wszystko" in html
    assert "nie rozpoznano (pusty JSON)" in html
    assert "Pobierz JSON" in html
    assert "http://" not in html and "https://" not in html

    for path, expected_ct in [
        ("/static/style.css", "text/css"),
        ("/static/app.js", "application/javascript"),
    ]:
        st, hdrs, data = _http_request(f"{server.url}{path}")
        assert st == 200
        assert expected_ct in hdrs["content-type"]
        assert len(data) > 0


def test_upload_polish_and_special_filenames(gui_server: tuple[gui.GuiServer, Path, Path]) -> None:
    server, inp, _ = gui_server
    pdf_bytes = b"%PDF-1.4\n1 0 obj <<>> endobj\n%%EOF\n"

    names = [
        ("sprawa żółć", "pełnomocnictwo nr 1.pdf"),
        ("sprawa żółć", "16_komisja_ds._regulacji_wynagrodzeń.pdf"),
        ("sprawa żółć", "Minister-Sprawiedliwosci-pismo-RDSSP-z-11.03.2024-r..pdf"),
        ("sprawa żółć", "Broszura_JPK_FA(2).pdf"),
        ("sprawa_2", "SKAN.PDF"),
    ]
    for case_name, filename in names:
        url = (
            f"{server.url}/api/upload?case={quote(case_name, safe='')}"
            f"&filename={quote(filename, safe='')}"
        )
        status, _, raw = _http_request(
            url,
            method="POST",
            body=pdf_bytes,
            headers={"Content-Type": "application/pdf"},
        )
        assert status == 201, raw.decode("utf-8")
        info = json.loads(raw.decode("utf-8"))
        assert info["case"] == case_name
        assert info["filename"] == filename
        assert info["size"] == len(pdf_bytes)
        assert (inp / case_name / filename).read_bytes() == pdf_bytes

    # Header-based metadata fallback (URL-encoded Polish chars)
    status, _, raw = _http_request(
        f"{server.url}/api/upload",
        method="POST",
        body=pdf_bytes,
        headers={
            "X-Case": quote("sprawa z nagłówka", safe=""),
            "X-Filename": quote("odwołanie 2026.pdf", safe=""),
        },
    )
    assert status == 201
    assert (inp / "sprawa z nagłówka" / "odwołanie 2026.pdf").is_file()


@pytest.mark.parametrize(
    ("case_name", "filename", "body"),
    [
        ("../evil", "ok.pdf", b"%PDF-1.4\n"),
        ("a/b", "ok.pdf", b"%PDF-1.4\n"),
        ("a\\b", "ok.pdf", b"%PDF-1.4\n"),
        ("..", "ok.pdf", b"%PDF-1.4\n"),
        (".", "ok.pdf", b"%PDF-1.4\n"),
        ("", "ok.pdf", b"%PDF-1.4\n"),
        ("ok", "../evil.pdf", b"%PDF-1.4\n"),
        ("ok", "sub/evil.pdf", b"%PDF-1.4\n"),
        ("ok", "sub\\evil.pdf", b"%PDF-1.4\n"),
        ("ok", "/etc/passwd", b"%PDF-1.4\n"),
        ("ok", "notes.txt", b"plain text"),
        ("ok", ".pdf", b"%PDF-1.4\n"),
        ("ok", "bad:name.pdf", b"%PDF-1.4\n"),
        ("ok", "empty.pdf", b""),
    ],
)
def test_upload_rejects_traversal_and_invalid_inputs(
    gui_server: tuple[gui.GuiServer, Path, Path],
    case_name: str,
    filename: str,
    body: bytes,
) -> None:
    server, inp, _ = gui_server
    url = (
        f"{server.url}/api/upload?case={quote(case_name, safe='')}"
        f"&filename={quote(filename, safe='')}"
    )
    status, _, raw = _http_request(url, method="POST", body=body)
    assert status == 400
    assert "error" in json.loads(raw.decode("utf-8"))
    assert list(inp.rglob("*")) == []


def test_case_listing_and_root_pdfs(gui_server: tuple[gui.GuiServer, Path, Path]) -> None:
    server, inp, out = gui_server

    (inp / "luzem.pdf").write_bytes(b"%PDF-1.4\n")
    (inp / "sprawa_01").mkdir()
    (inp / "sprawa_01" / "przelew.pdf").write_bytes(b"%PDF-1.4\n")
    (inp / "sprawa_01" / "notatka.txt").write_text("ignored", encoding="utf-8")
    (out / "sprawa_01").mkdir()
    (out / "sprawa_01" / "przelew.json").write_text(
        json.dumps({"przelew_bankowy": {"kwota": 15000.0}}), encoding="utf-8"
    )

    status, data = _http_json(f"{server.url}/api/cases")
    assert status == 200
    by_name = {c["name"]: c for c in data["cases"]}
    assert "" in by_name
    assert [f["name"] for f in by_name[""]["files"]] == ["luzem.pdf"]
    assert "sprawa_01" in by_name
    files = by_name["sprawa_01"]["files"]
    assert len(files) == 1
    assert files[0]["name"] == "przelew.pdf"
    assert files[0]["has_result"] is True
    assert files[0]["is_empty_result"] is False
    assert files[0]["doc_type"] == "przelew_bankowy"


def test_process_case_status_polling_and_results(
    gui_server: tuple[gui.GuiServer, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, inp, out = gui_server
    case_dir = inp / "sprawa żółć"
    case_dir.mkdir()

    pdf_ok = case_dir / "01_przelew.pdf"
    pdf_empty = case_dir / "02_nieznany.pdf"
    pdf_fail = case_dir / "03_zepsuty.pdf"
    pdf_other_case = inp / "inna_sprawa" / "odwolanie.pdf"
    pdf_other_case.parent.mkdir()

    for p in (pdf_ok, pdf_empty, pdf_fail, pdf_other_case):
        p.write_bytes(b"%PDF-1.4\n%fake\n")

    started_first = threading.Event()
    release_first = threading.Event()

    def fake_process_document(pdf: Path) -> dict[str, Any]:
        if pdf.name == "01_przelew.pdf":
            started_first.set()
            release_first.wait(timeout=5)
            return {
                "przelew_bankowy": {
                    "kwota": 15000.0,
                    "numer_rachunku": None,
                    "tytul": "Wpis od odwołania",
                }
            }
        if pdf.name == "02_nieznany.pdf":
            return {}
        if pdf.name == "03_zepsuty.pdf":
            raise RuntimeError("uszkodzony skan")
        return {"unexpected": True}

    monkeypatch.setattr(cli, "process_document", fake_process_document)

    status, job = _http_json(
        f"{server.url}/api/process",
        method="POST",
        payload={"scope": "case", "case": "sprawa żółć"},
    )
    assert status == 202
    assert job["running"] is True
    assert job["total"] == 3

    # Wait until the first file is actively being processed so we can observe live states.
    assert started_first.wait(timeout=5)
    st_mid, mid = _http_json(f"{server.url}/api/status")
    assert st_mid == 200
    assert mid["running"] is True
    assert mid["files"]["sprawa żółć/01_przelew.pdf"]["status"] == "ocr"
    assert mid["files"]["sprawa żółć/02_nieznany.pdf"]["status"] == "waiting"

    # Concurrent processing request must be rejected with 409.
    st_conflict, err_body = _http_json(
        f"{server.url}/api/process", method="POST", payload={"scope": "all"}
    )
    assert st_conflict == 409
    assert "error" in err_body

    release_first.set()

    deadline = time.monotonic() + 5.0
    final_status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        st, final_status = _http_json(f"{server.url}/api/status")
        assert st == 200
        if not final_status["running"]:
            break
        time.sleep(0.02)

    assert final_status["running"] is False
    assert final_status["total"] == 3
    assert final_status["completed"] == 3
    assert final_status["failed"] == 1
    assert final_status["files"]["sprawa żółć/01_przelew.pdf"]["status"] == "done"
    assert final_status["files"]["sprawa żółć/02_nieznany.pdf"]["status"] == "done"
    assert final_status["files"]["sprawa żółć/03_zepsuty.pdf"]["status"] == "error"
    assert "uszkodzony skan" in final_status["files"]["sprawa żółć/03_zepsuty.pdf"]["error"]

    # Other case was not touched.
    assert not (out / "inna_sprawa" / "odwolanie.json").exists()
    # Failed document still produces {} just like CLI.
    assert json.loads((out / "sprawa żółć" / "03_zepsuty.json").read_text(encoding="utf-8")) == {}

    # Inspect result JSON endpoint for populated and empty results.
    st_ok, res_ok = _http_json(
        f"{server.url}/api/result?path={quote('sprawa żółć/01_przelew.pdf', safe='')}"
    )
    assert st_ok == 200
    assert res_ok["exists"] is True
    assert res_ok["is_empty"] is False
    assert res_ok["doc_type"] == "przelew_bankowy"
    assert res_ok["data"]["przelew_bankowy"]["kwota"] == 15000.0
    assert res_ok["data"]["przelew_bankowy"]["numer_rachunku"] is None
    assert res_ok["trace"] is None

    st_empty, res_empty = _http_json(
        f"{server.url}/api/result?path={quote('sprawa żółć/02_nieznany.pdf', safe='')}"
    )
    assert st_empty == 200
    assert res_empty["exists"] is True
    assert res_empty["is_empty"] is True
    assert res_empty["data"] == {}


def test_serve_pdf_and_download_json_with_polish_names(
    gui_server: tuple[gui.GuiServer, Path, Path],
) -> None:
    server, inp, out = gui_server
    pdf_bytes = b"%PDF-1.4\n%polish test\n%%EOF\n"
    rel = "sprawa ążś/pełnomocnictwo nr 1.pdf"

    (inp / "sprawa ążś").mkdir()
    (inp / rel).write_bytes(pdf_bytes)
    (out / "sprawa ążś").mkdir()
    out_payload = {"pelnomocnictwo": {"mocodawca": [{"nazwa": "Spółka ĄĘĆ"}]}}
    (out / "sprawa ążś" / "pełnomocnictwo nr 1.json").write_text(
        json.dumps(out_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    st_pdf, hdr_pdf, got_pdf = _http_request(f"{server.url}/api/pdf?path={quote(rel, safe='')}")
    assert st_pdf == 200
    assert hdr_pdf["content-type"] == "application/pdf"
    assert hdr_pdf["content-disposition"].startswith("inline;")
    assert got_pdf == pdf_bytes

    st_dl, hdr_dl, got_json = _http_request(f"{server.url}/api/download?path={quote(rel, safe='')}")
    assert st_dl == 200
    assert "application/json" in hdr_dl["content-type"]
    assert hdr_dl["content-disposition"].startswith("attachment;")
    assert json.loads(got_json.decode("utf-8")) == out_payload


def test_optional_trace_shown_only_from_outside_output(
    gui_server: tuple[gui.GuiServer, Path, Path],
) -> None:
    server, inp, out = gui_server
    rel = "case1/doc.pdf"
    (inp / "case1").mkdir()
    (inp / rel).write_bytes(b"%PDF-1.4\n")
    (out / "case1").mkdir()
    (out / "case1" / "doc.json").write_text("{}\n", encoding="utf-8")

    # Trace file placed inside output/ must be ignored.
    (out / "case1" / "doc.trace.json").write_text('{"inside_output": true}', encoding="utf-8")
    st0, res0 = _http_json(f"{server.url}/api/result?path={quote(rel, safe='')}")
    assert st0 == 200
    assert res0["trace"] is None

    # Create a trace file outside output/ (sibling traces/ directory).
    traces_dir = out.parent / "traces" / "case1"
    traces_dir.mkdir(parents=True)
    trace_payload = {"pages_read": [1], "model": "test-model", "fields": {"kwota": {"page": 1}}}
    (traces_dir / "doc.trace.json").write_text(
        json.dumps(trace_payload, ensure_ascii=False), encoding="utf-8"
    )

    st1, res1 = _http_json(f"{server.url}/api/result?path={quote(rel, safe='')}")
    assert st1 == 200
    assert res1["trace"] == trace_payload
    assert res1["trace_filename"] == "doc.trace.json"


def test_symlink_outside_input_is_rejected(
    gui_server: tuple[gui.GuiServer, Path, Path],
    tmp_path: Path,
) -> None:
    server, inp, _ = gui_server
    secret = tmp_path / "secret.pdf"
    secret.write_bytes(b"%PDF-1.4\nsecret\n")
    (inp / "case1").mkdir()
    link = inp / "case1" / "escape.pdf"
    link.symlink_to(secret)

    for endpoint in ("/api/pdf", "/api/result", "/api/download"):
        st, _, _ = _http_request(
            f"{server.url}{endpoint}?path={quote('case1/escape.pdf', safe='')}"
        )
        assert st == 400


@pytest.mark.parametrize(
    "bad_path",
    [
        "../secret.pdf",
        "/etc/passwd",
        "case1/../../secret.pdf",
        "case1\\doc.pdf",
        "case1/not_a_pdf.txt",
        "",
    ],
)
def test_read_endpoints_reject_traversal(
    gui_server: tuple[gui.GuiServer, Path, Path],
    bad_path: str,
) -> None:
    server, _, _ = gui_server
    q = quote(bad_path, safe="")
    for endpoint in ("/api/pdf", "/api/result", "/api/download"):
        st, _, raw = _http_request(f"{server.url}{endpoint}?path={q}")
        assert st == 400, f"{endpoint} accepted {bad_path!r}: {raw!r}"


def test_cli_gui_flag_delegates_to_serve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, Any] = {}

    def fake_serve(
        input_dir: Path,
        output_dir: Path,
        *,
        port: int = 0,
        open_browser: bool = True,
        trace_dir: Path | None = None,
    ) -> int:
        called["input_dir"] = input_dir
        called["output_dir"] = output_dir
        called["port"] = port
        called["open_browser"] = open_browser
        called["trace_dir"] = trace_dir
        return 0

    monkeypatch.setattr(gui, "serve", fake_serve)
    rc = cli.main(
        [
            "--input",
            str(tmp_path / "in"),
            "--output",
            str(tmp_path / "out"),
            "--gui",
            "--port",
            "8765",
            "--no-browser",
        ]
    )
    assert rc == 0
    assert called == {
        "input_dir": tmp_path / "in",
        "output_dir": tmp_path / "out",
        "port": 8765,
        "open_browser": False,
        "trace_dir": tmp_path / "traces",  # JSON4WIN_TRACE_DIR, set by conftest
    }
    rc = cli.main(["--input", str(tmp_path / "in"), "--gui", "--no-browser", "--no-trace"])
    assert rc == 0 and called["trace_dir"] is None
