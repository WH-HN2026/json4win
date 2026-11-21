"""Local web GUI for json4win (standard library only, localhost only)."""

from __future__ import annotations

import json
import logging
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from json4win import cli, env, gui_wizard

log = logging.getLogger("json4win.gui")

STATIC_DIR = Path(__file__).resolve().parent / "gui_static"
STATIC_FILES: dict[str, tuple[str, str]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/wizard": ("wizard.html", "text/html; charset=utf-8"),
    "/wizard.html": ("wizard.html", "text/html; charset=utf-8"),
    "/static/ui.css": ("ui.css", "text/css; charset=utf-8"),
    "/static/ui.js": ("ui.js", "application/javascript; charset=utf-8"),
    "/static/docs.js": ("docs.js", "application/javascript; charset=utf-8"),
    "/static/wizard.js": ("wizard.js", "application/javascript; charset=utf-8"),
}

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MiB
MAX_JSON_BODY_BYTES = 1 * 1024 * 1024  # 1 MiB
_FORBIDDEN_NAME_CHARS = set('<>:"|?*')


def _validate_segment(raw: str, *, label: str) -> str:
    """Validate a single path segment (case name or filename), keeping Polish chars and spaces."""
    if not isinstance(raw, str):
        raise ValueError(f"Nieprawidłowa {label}.")
    if "\x00" in raw or "/" in raw or "\\" in raw:
        raise ValueError(f"Niedozwolony znak ścieżki w polu: {label}.")
    name = raw.strip()
    if not name or name in {".", ".."}:
        raise ValueError(f"Nieprawidłowa {label}.")
    if name.endswith("."):
        raise ValueError(f"{label.capitalize()} nie może kończyć się kropką.")
    if any(ord(ch) < 32 or ch in _FORBIDDEN_NAME_CHARS for ch in name):
        raise ValueError(f"Niedozwolony znak w polu: {label}.")
    return name


def validate_case_name(raw: str) -> str:
    """Validate a case directory name (single segment, no path traversal)."""
    return _validate_segment(raw, label="nazwa sprawy")


def validate_pdf_filename(raw: str) -> str:
    """Validate an uploaded PDF filename (single segment, .pdf suffix, no path traversal)."""
    name = _validate_segment(raw, label="nazwa pliku")
    if not name.lower().endswith(".pdf") or len(name) <= 4:
        raise ValueError("Dozwolone są wyłącznie pliki z rozszerzeniem .pdf.")
    return name


def resolve_input_pdf(input_dir: Path, rel_path: str) -> Path:
    """Resolve a relative PDF path strictly inside input_dir."""
    if not isinstance(rel_path, str) or not rel_path or "\x00" in rel_path or "\\" in rel_path:
        raise ValueError("Nieprawidłowa ścieżka pliku.")
    posix = PurePosixPath(rel_path)
    if posix.is_absolute() or not posix.parts:
        raise ValueError("Ścieżka musi być względna.")
    for part in posix.parts:
        if part in {"", ".", ".."} or any(ord(ch) < 32 for ch in part):
            raise ValueError("Niedozwolony segment ścieżki.")
    root = input_dir.resolve()
    candidate = (root / Path(*posix.parts)).resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        raise ValueError("Ścieżka poza katalogiem wejściowym.")
    if candidate.suffix.lower() != ".pdf":
        raise ValueError("Ścieżka musi wskazywać na plik PDF.")
    return candidate


def resolve_output_json(pdf_path: Path, input_dir: Path, output_dir: Path) -> Path:
    """Resolve the mirrored output JSON path strictly inside output_dir."""
    in_root = input_dir.resolve()
    out_root = output_dir.resolve()
    pdf_resolved = pdf_path.resolve()
    if not pdf_resolved.is_relative_to(in_root):
        raise ValueError("Plik poza katalogiem wejściowym.")
    out = cli.output_path_for(pdf_resolved, in_root, out_root).resolve()
    if not out.is_relative_to(out_root) or out == out_root:
        raise ValueError("Ścieżka wyniku poza katalogiem wyjściowym.")
    return out


def find_trace(
    rel_pdf: Path, output_dir: Path, trace_dir: Path | None = None
) -> tuple[Path, Any] | None:
    """Look for an optional extraction trace file outside output_dir (future task X2)."""
    out_root = output_dir.resolve()
    bases = (
        [trace_dir]
        if trace_dir is not None
        else [out_root.parent / "traces", env.cache_dir() / "traces"]
    )
    for base in bases:
        base_resolved = base.resolve()
        if base_resolved == out_root or base_resolved.is_relative_to(out_root):
            continue
        if not base_resolved.is_dir():
            continue
        for suffix in (".trace.json", ".json"):
            candidate = (base_resolved / rel_pdf.with_suffix(suffix)).resolve()
            if not candidate.is_relative_to(base_resolved) or not candidate.is_file():
                continue
            try:
                raw = candidate.read_text(encoding="utf-8")
            except OSError:
                continue
            try:
                return candidate, json.loads(raw)
            except json.JSONDecodeError:
                return candidate, raw
    return None


def _content_disposition(disposition: str, filename: str) -> str:
    """Build an RFC 5987 Content-Disposition header safe for non-ASCII Polish filenames."""
    ascii_chars = [
        ch if 32 <= ord(ch) < 127 and ch not in {'"', "\\", ";"} else "_" for ch in filename
    ]
    ascii_fallback = "".join(ascii_chars) or "file"
    encoded = quote(filename, safe="")
    return f"{disposition}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


def _summarize_output_json(out_path: Path) -> tuple[bool, bool, str | None]:
    """Return (has_result, is_empty_result, doc_type) for an output JSON path."""
    if not out_path.is_file():
        return False, False, None
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True, False, None
    if isinstance(data, dict):
        if not data:
            return True, True, None
        first_key = next(iter(data.keys()), None)
        return True, False, str(first_key) if first_key is not None else None
    return True, False, None


class GuiState:
    """Shared state for the local GUI server (case listing, uploads, background jobs)."""

    def __init__(
        self,
        input_dir: Path,
        output_dir: Path,
        trace_dir: Path | None = None,
        *,
        wizard_dir: Path | None = None,
        config_dir: Path | None = None,
    ) -> None:
        self.input_dir = input_dir.resolve()
        self.output_dir = output_dir.resolve()
        self.trace_dir = trace_dir.resolve() if trace_dir is not None else None
        self.wizard = gui_wizard.WizardState(
            wizard_dir=wizard_dir,
            config_dir=config_dir,
            forbidden_dirs=(self.output_dir, self.input_dir),
        )
        self._lock = threading.Lock()
        self._job_seq = 0
        self._job: dict[str, Any] = {
            "id": 0,
            "running": False,
            "scope": None,
            "case": None,
            "total": 0,
            "completed": 0,
            "failed": 0,
            "files": {},
        }
        self._worker: threading.Thread | None = None

    def job_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "id": self._job["id"],
                "running": self._job["running"],
                "scope": self._job["scope"],
                "case": self._job["case"],
                "total": self._job["total"],
                "completed": self._job["completed"],
                "failed": self._job["failed"],
                "files": {k: dict(v) for k, v in self._job["files"].items()},
            }

    def list_cases(self) -> dict[str, Any]:
        job = self.job_snapshot()
        job_files = job["files"]
        cases: list[dict[str, Any]] = []

        if self.input_dir.is_dir():
            root_pdfs = sorted(
                p for p in self.input_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"
            )
            if root_pdfs:
                cases.append(
                    {
                        "name": "",
                        "files": [self._file_entry(pdf, pdf.name, job_files) for pdf in root_pdfs],
                    }
                )
            case_dirs = sorted(
                (p for p in self.input_dir.iterdir() if p.is_dir() and not p.name.startswith(".")),
                key=lambda p: p.name.casefold(),
            )
            for case_dir in case_dirs:
                pdfs = cli.find_pdfs(case_dir)
                cases.append(
                    {
                        "name": case_dir.name,
                        "files": [
                            self._file_entry(pdf, pdf.relative_to(case_dir).as_posix(), job_files)
                            for pdf in pdfs
                        ],
                    }
                )

        return {
            "input_dir": str(self.input_dir),
            "output_dir": str(self.output_dir),
            "cases": cases,
            "job": job,
        }

    def _file_entry(
        self, pdf: Path, display_name: str, job_files: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        rel_path = pdf.relative_to(self.input_dir)
        rel_key = rel_path.as_posix()
        out_path = cli.output_path_for(pdf, self.input_dir, self.output_dir)
        has_result, is_empty, doc_type = _summarize_output_json(out_path)
        trace = find_trace(rel_path, self.output_dir, self.trace_dir)
        job_info = job_files.get(rel_key)
        status = job_info["status"] if job_info else ("done" if has_result else "idle")
        error = job_info["error"] if job_info else None
        return {
            "name": display_name,
            "rel_path": rel_key,
            "size": pdf.stat().st_size,
            "has_result": has_result,
            "is_empty_result": is_empty,
            "doc_type": doc_type,
            "has_trace": trace is not None,
            "status": status,
            "error": error,
        }

    def save_upload(self, case_raw: str, filename_raw: str, data: bytes) -> dict[str, Any]:
        case_name = validate_case_name(case_raw)
        filename = validate_pdf_filename(filename_raw)
        if not data:
            raise ValueError("Plik jest pusty.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise OverflowError("Plik przekracza maksymalny dozwolony rozmiar.")

        case_dir = (self.input_dir / case_name).resolve()
        if not case_dir.is_relative_to(self.input_dir) or case_dir.parent != self.input_dir:
            raise ValueError("Niedozwolona ścieżka sprawy.")
        target = (case_dir / filename).resolve()
        if not target.is_relative_to(self.input_dir) or target.parent != case_dir:
            raise ValueError("Niedozwolona ścieżka pliku.")

        case_dir.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        rel_key = target.relative_to(self.input_dir).as_posix()
        log.info("uploaded %s (%d bytes)", rel_key, len(data))
        return {
            "case": case_name,
            "filename": filename,
            "rel_path": rel_key,
            "size": len(data),
        }

    def get_result(self, rel_path: str) -> dict[str, Any]:
        pdf_path = resolve_input_pdf(self.input_dir, rel_path)
        if not pdf_path.is_file():
            raise FileNotFoundError(f"Nie znaleziono pliku PDF: {rel_path}")
        rel_obj = pdf_path.relative_to(self.input_dir)
        out_path = resolve_output_json(pdf_path, self.input_dir, self.output_dir)
        trace_found = find_trace(rel_obj, self.output_dir, self.trace_dir)

        exists = out_path.is_file()
        data: Any = None
        raw_text: str | None = None
        parse_error: str | None = None
        is_empty = False
        doc_type: str | None = None

        if exists:
            raw_text = out_path.read_text(encoding="utf-8")
            try:
                data = json.loads(raw_text)
                if isinstance(data, dict):
                    is_empty = len(data) == 0
                    if data:
                        doc_type = str(next(iter(data.keys())))
            except json.JSONDecodeError as exc:
                parse_error = str(exc)

        return {
            "rel_path": rel_obj.as_posix(),
            "filename": pdf_path.name,
            "json_filename": out_path.name,
            "exists": exists,
            "is_empty": is_empty,
            "doc_type": doc_type,
            "data": data,
            "raw_text": raw_text,
            "parse_error": parse_error,
            "trace": trace_found[1] if trace_found is not None else None,
            "trace_filename": trace_found[0].name if trace_found is not None else None,
        }

    def start_processing(
        self,
        scope: str = "all",
        case_name: str | None = None,
        rel_path: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        targets: list[Path]
        selected_case: str | None = None

        if scope == "all":
            targets = cli.find_pdfs(self.input_dir) if self.input_dir.is_dir() else []
        elif scope == "case":
            if case_name == "":
                selected_case = ""
                targets = (
                    sorted(
                        p
                        for p in self.input_dir.iterdir()
                        if p.is_file() and p.suffix.lower() == ".pdf"
                    )
                    if self.input_dir.is_dir()
                    else []
                )
            else:
                valid_case = validate_case_name(case_name or "")
                selected_case = valid_case
                case_dir = (self.input_dir / valid_case).resolve()
                if not case_dir.is_relative_to(self.input_dir) or not case_dir.is_dir():
                    raise FileNotFoundError(f"Nie znaleziono sprawy: {valid_case}")
                targets = cli.find_pdfs(case_dir)
        elif scope == "file":
            pdf_path = resolve_input_pdf(self.input_dir, rel_path or "")
            if not pdf_path.is_file():
                raise FileNotFoundError(f"Nie znaleziono pliku: {rel_path}")
            rel_parts = pdf_path.relative_to(self.input_dir).parts
            selected_case = rel_parts[0] if len(rel_parts) > 1 else ""
            targets = [pdf_path]
        else:
            raise ValueError("Nieprawidłowy zakres przetwarzania (oczekiwano: all, case lub file).")

        with self._lock:
            if self._job["running"]:
                return HTTPStatus.CONFLICT, {"error": "Przetwarzanie jest już w toku."}
            self._job_seq += 1
            job_id = self._job_seq
            file_states = {
                pdf.relative_to(self.input_dir).as_posix(): {"status": "waiting", "error": None}
                for pdf in targets
            }
            self._job = {
                "id": job_id,
                "running": bool(targets),
                "scope": scope,
                "case": selected_case,
                "total": len(targets),
                "completed": 0,
                "failed": 0,
                "files": file_states,
            }
            snapshot = {
                "id": self._job["id"],
                "running": self._job["running"],
                "scope": self._job["scope"],
                "case": self._job["case"],
                "total": self._job["total"],
                "completed": self._job["completed"],
                "failed": self._job["failed"],
                "files": {k: dict(v) for k, v in self._job["files"].items()},
            }
            if not targets:
                return HTTPStatus.OK, snapshot

            worker = threading.Thread(
                target=self._run_job,
                args=(job_id, targets),
                name=f"json4win-job-{job_id}",
                daemon=True,
            )
            self._worker = worker
            worker.start()
            return HTTPStatus.ACCEPTED, snapshot

    def _run_job(self, job_id: int, targets: list[Path]) -> None:
        def on_progress(pdf: Path, status: str, error: Exception | None) -> None:
            rel_key = pdf.relative_to(self.input_dir).as_posix()
            with self._lock:
                if self._job["id"] != job_id:
                    return
                self._job["files"][rel_key] = {
                    "status": status,
                    "error": str(error) if error is not None else None,
                }
                if status in {"done", "error"}:
                    self._job["completed"] += 1
                if status == "error":
                    self._job["failed"] += 1

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            cli.run(
                self.input_dir,
                self.output_dir,
                pdfs=targets,
                on_progress=on_progress,
                trace_dir=self.trace_dir,
            )
        except Exception:
            log.exception("unexpected error in background processing job %d", job_id)
        finally:
            with self._lock:
                if self._job["id"] == job_id:
                    self._job["running"] = False


class GuiServer(ThreadingHTTPServer):
    """ThreadingHTTPServer bound to 127.0.0.1 holding GuiState."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        state: GuiState,
        port: int = 0,
    ) -> None:
        self.state = state
        super().__init__(("127.0.0.1", port), GuiRequestHandler)

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"

    def server_close(self) -> None:
        try:
            self.state.wizard.close()
        finally:
            super().server_close()


class GuiRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the local json4win GUI."""

    server: GuiServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        log.debug("%s - " + format, self.address_string(), *args)

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        disposition: str | None = None,
        cache_control: str = "no-store",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        if disposition is not None:
            self.send_header("Content-Disposition", disposition)
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self, max_bytes: int, *, allow_missing_length: bool = False) -> bytes:
        raw_len = self.headers.get("Content-Length")
        if raw_len is None:
            if allow_missing_length:
                return b""
            raise ValueError("Brak nagłówka Content-Length.")
        try:
            length = int(raw_len)
        except ValueError as exc:
            raise ValueError("Nieprawidłowy nagłówek Content-Length.") from exc
        if length < 0:
            raise ValueError("Nieprawidłowy nagłówek Content-Length.")
        if length > max_bytes:
            raise OverflowError("Żądanie przekracza maksymalny dozwolony rozmiar.")
        return self.rfile.read(length) if length else b""

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        params = parse_qs(parsed.query, keep_blank_values=True)

        try:
            if route in STATIC_FILES:
                filename, content_type = STATIC_FILES[route]
                data = (STATIC_DIR / filename).read_bytes()
                self._send_bytes(HTTPStatus.OK, data, content_type)
                return

            if route == "/api/wizard/state":
                self._send_json(HTTPStatus.OK, self.server.state.wizard.snapshot())
                return

            if route == "/api/cases":
                self._send_json(HTTPStatus.OK, self.server.state.list_cases())
                return

            if route == "/api/status":
                self._send_json(HTTPStatus.OK, self.server.state.job_snapshot())
                return

            if route == "/api/result":
                rel_path = params.get("path", [""])[0]
                self._send_json(HTTPStatus.OK, self.server.state.get_result(rel_path))
                return

            if route == "/api/pdf":
                rel_path = params.get("path", [""])[0]
                pdf_path = resolve_input_pdf(self.server.state.input_dir, rel_path)
                if not pdf_path.is_file():
                    raise FileNotFoundError(f"Nie znaleziono pliku PDF: {rel_path}")
                data = pdf_path.read_bytes()
                self._send_bytes(
                    HTTPStatus.OK,
                    data,
                    "application/pdf",
                    disposition=_content_disposition("inline", pdf_path.name),
                )
                return

            if route == "/api/download":
                rel_path = params.get("path", [""])[0]
                pdf_path = resolve_input_pdf(self.server.state.input_dir, rel_path)
                out_path = resolve_output_json(
                    pdf_path, self.server.state.input_dir, self.server.state.output_dir
                )
                if not out_path.is_file():
                    raise FileNotFoundError(f"Brak wygenerowanego pliku JSON dla: {rel_path}")
                data = out_path.read_bytes()
                self._send_bytes(
                    HTTPStatus.OK,
                    data,
                    "application/json; charset=utf-8",
                    disposition=_content_disposition("attachment", out_path.name),
                )
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Nie znaleziono zasobu."})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except FileNotFoundError as exc:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except Exception:
            log.exception("GET %s failed", route)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Błąd wewnętrzny serwera."})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        params = parse_qs(parsed.query, keep_blank_values=True)

        try:
            if route == "/api/upload":
                case_raw = params.get("case", [""])[0]
                if not case_raw and self.headers.get("X-Case"):
                    case_raw = unquote(self.headers.get("X-Case", ""))
                filename_raw = params.get("filename", [""])[0]
                if not filename_raw and self.headers.get("X-Filename"):
                    filename_raw = unquote(self.headers.get("X-Filename", ""))
                data = self._read_body(MAX_UPLOAD_BYTES)
                result = self.server.state.save_upload(case_raw, filename_raw, data)
                self._send_json(HTTPStatus.CREATED, result)
                return

            if route == "/api/process":
                raw = self._read_body(MAX_JSON_BODY_BYTES, allow_missing_length=True)
                payload = json.loads(raw.decode("utf-8")) if raw else {}
                if not isinstance(payload, dict):
                    raise ValueError("Oczekiwano obiektu JSON.")
                scope = str(payload.get("scope", "all"))
                case_name = payload.get("case")
                rel_path = payload.get("path")
                status, result = self.server.state.start_processing(
                    scope=scope,
                    case_name=case_name if isinstance(case_name, str) else None,
                    rel_path=rel_path if isinstance(rel_path, str) else None,
                )
                self._send_json(status, result)
                return

            if route == "/api/wizard/upload":
                filename_raw = params.get("filename", [""])[0]
                if not filename_raw and self.headers.get("X-Filename"):
                    filename_raw = unquote(self.headers.get("X-Filename", ""))
                data = self._read_body(MAX_UPLOAD_BYTES)
                result = self.server.state.wizard.add_upload(filename_raw, data)
                self._send_json(HTTPStatus.CREATED, result)
                return

            if route.startswith("/api/wizard/"):
                raw = self._read_body(MAX_JSON_BODY_BYTES, allow_missing_length=True)
                payload = json.loads(raw.decode("utf-8")) if raw else {}
                if not isinstance(payload, dict):
                    raise ValueError("Oczekiwano obiektu JSON.")
                wiz = self.server.state.wizard
                if route == "/api/wizard/reset":
                    self._send_json(HTTPStatus.OK, wiz.reset())
                    return
                if route == "/api/wizard/remove":
                    self._send_json(
                        HTTPStatus.OK, wiz.remove_file(str(payload.get("doc_id") or ""))
                    )
                    return
                if route == "/api/wizard/ocr":
                    doc_id = payload.get("doc_id")
                    max_pages = payload.get("max_pages", gui_wizard.DEFAULT_MAX_PAGES)
                    result = wiz.run_ocr(
                        doc_id=doc_id if isinstance(doc_id, str) and doc_id else None,
                        max_pages=max_pages,
                    )
                    self._send_json(HTTPStatus.OK, result)
                    return
                if route == "/api/wizard/propose-szablon":
                    result = wiz.propose_szablon(hint=str(payload.get("hint") or ""))
                    self._send_json(HTTPStatus.OK, result)
                    return
                if route == "/api/wizard/preview":
                    result = wiz.refresh_preview(payload.get("szablon"), payload.get("typy"))
                    self._send_json(HTTPStatus.OK, result)
                    return
                if route == "/api/wizard/propose-yaml":
                    result = wiz.propose_yaml(
                        payload.get("szablon"),
                        payload.get("typy"),
                        hint=str(payload.get("hint") or ""),
                    )
                    self._send_json(HTTPStatus.OK, result)
                    return
                if route == "/api/wizard/validate":
                    result = wiz.validate_yaml(
                        payload.get("yaml_text", ""),
                        save_draft=bool(payload.get("save_draft", True)),
                    )
                    self._send_json(HTTPStatus.OK, result)
                    return
                if route == "/api/wizard/test":
                    result = wiz.test_draft(payload.get("yaml_text", ""))
                    self._send_json(HTTPStatus.OK, result)
                    return
                if route == "/api/wizard/save":
                    result = wiz.save_yaml(
                        payload.get("yaml_text", ""),
                        overwrite=bool(payload.get("overwrite", False)),
                    )
                    self._send_json(HTTPStatus.CREATED, result)
                    return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Nie znaleziono zasobu."})
        except gui_wizard.WizardConflictError as exc:
            self._send_json(
                HTTPStatus.CONFLICT,
                {
                    "error": str(exc),
                    "exists": True,
                    "filename": exc.path.name,
                    "path": str(exc.path),
                    "target_dir": str(exc.target_dir),
                },
            )
        except gui_wizard.WizardLlmError as exc:
            self._send_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
        except OverflowError as exc:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": str(exc)})
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except FileNotFoundError as exc:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except Exception:
            log.exception("POST %s failed", route)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Błąd wewnętrzny serwera."})


def create_server(
    input_dir: Path,
    output_dir: Path,
    *,
    port: int = 0,
    trace_dir: Path | None = None,
    wizard_dir: Path | None = None,
    config_dir: Path | None = None,
) -> GuiServer:
    """Create a configured localhost-only GUI HTTP server."""
    state = GuiState(
        input_dir=input_dir,
        output_dir=output_dir,
        trace_dir=trace_dir,
        wizard_dir=wizard_dir,
        config_dir=config_dir,
    )
    return GuiServer(state=state, port=port)


def serve(
    input_dir: Path,
    output_dir: Path,
    *,
    port: int = 0,
    open_browser: bool = True,
    trace_dir: Path | None = None,
) -> int:
    """Start the local GUI server on 127.0.0.1 and block until Ctrl+C.

    trace_dir: where processing writes extraction traces and the GUI reads them; None = no traces.
    """
    server = create_server(input_dir, output_dir, port=port, trace_dir=trace_dir)
    url = server.url
    log.info("GUI json4win uruchomione pod adresem: %s", url)
    log.info("Katalog wejściowy: %s", server.state.input_dir)
    log.info("Katalog wyjściowy: %s", server.state.output_dir)
    log.info("Naciśnij Ctrl+C, aby zatrzymać serwer.")

    if open_browser:

        def _open() -> None:
            try:
                webbrowser.open(url)
            except Exception:
                log.debug("Nie udało się automatycznie otworzyć przeglądarki", exc_info=True)

        threading.Timer(0.2, _open).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Zatrzymywanie GUI...")
    finally:
        server.server_close()
    return 0
