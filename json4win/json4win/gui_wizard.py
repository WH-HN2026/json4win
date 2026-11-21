"""Backend for the GUI config wizard ("Nowa klasa"): PDFs -> szablon -> YAML -> test -> save.

Stdlib + existing app dependencies only (PyYAML). Never reads dane/, ewaluacja/ or ground truth.
Uploads stay in a dedicated work/temp directory outside output/ and input/. Every page OCR goes
through json4win.ocr (never the PDF text layer).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from json4win import config, decide, env, extract, llm, ocr, pipeline, prompts, validate

log = logging.getLogger("json4win.gui_wizard")

MAX_WIZARD_FILES = 5
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MiB
DEFAULT_MAX_PAGES = 2
MAX_PAGES_LIMIT = 20
MAX_CHARS_PER_DOC = 8000
MAX_TOTAL_CHARS = 24000
MAX_HINT_CHARS = 600

_FORBIDDEN_NAME_CHARS = set('<>:"|?*')
_VALID_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_MARKER_SNIPPET_RADIUS = 35


class WizardError(ValueError):
    """Invalid wizard input or request."""


class WizardConflictError(RuntimeError):
    """Saving would overwrite an existing file without explicit confirmation."""

    def __init__(self, path: Path, target_dir: Path) -> None:
        super().__init__(f"Plik {path.name} już istnieje w {target_dir}.")
        self.path = path
        self.target_dir = target_dir


class WizardLlmError(RuntimeError):
    """LLM call failed or produced unusable output."""


def validate_pdf_filename(raw: str) -> str:
    """Validate an uploaded PDF filename (single segment, .pdf suffix, no path traversal)."""
    if not isinstance(raw, str):
        raise WizardError("Nieprawidłowa nazwa pliku.")
    if "\x00" in raw or "/" in raw or "\\" in raw:
        raise WizardError("Niedozwolony znak ścieżki w nazwie pliku.")
    name = raw.strip()
    if not name or name in {".", ".."}:
        raise WizardError("Nieprawidłowa nazwa pliku.")
    if name.endswith("."):
        raise WizardError("Nazwa pliku nie może kończyć się kropką.")
    if any(ord(ch) < 32 or ch in _FORBIDDEN_NAME_CHARS for ch in name):
        raise WizardError("Niedozwolony znak w nazwie pliku.")
    if not name.lower().endswith(".pdf") or len(name) <= 4:
        raise WizardError("Dozwolone są wyłącznie pliki z rozszerzeniem .pdf.")
    return name


def target_config_dir(override: Path | None = None) -> Path:
    """First directory of JSON4WIN_CONFIG_DIRS if set, else json4win/config/."""
    if override is not None:
        return override.resolve()
    raw = env.get("JSON4WIN_CONFIG_DIRS")
    if raw:
        for entry in raw.split(os.pathsep):
            entry = entry.strip()
            if not entry:
                continue
            p = Path(entry)
            if not p.is_absolute() and not p.is_dir():
                alt = env.APP_ROOT / p
                if alt.is_dir():
                    p = alt
            return p.resolve()
    return config.CONFIG_DIR.resolve()


def _load_existing_classes_safe() -> dict[str, config.DocClass]:
    try:
        return config.load_classes()
    except config.ConfigError:
        log.warning("could not load all existing classes", exc_info=True)
        return {}


# ---- template (szablon) validation & coercion --------------------------------------------------


def validate_template(template: Any, path: str = "") -> dict[str, Any]:
    """Validate a szablon object using the same rules as json4win.config."""
    if not path and not isinstance(template, dict):
        raise WizardError("Szablon musi być niepustym obiektem JSON.")
    if isinstance(template, dict):
        if not template:
            raise WizardError(f"Pusty obiekt w szablonie: {path or 'szablon'}.")
        out: dict[str, Any] = {}
        for k, v in template.items():
            if not isinstance(k, str) or not k.strip():
                raise WizardError(
                    f"Klucz w szablonie musi być niepustym tekstem ({path or 'root'})."
                )
            child_path = f"{path}.{k}" if path else k
            out[k] = _validate_template_node(v, child_path)
        return out
    raise WizardError("Szablon musi być obiektem JSON.")


def _validate_template_node(node: Any, path: str) -> Any:
    if isinstance(node, dict):
        return validate_template(node, path)
    if isinstance(node, list):
        if len(node) != 1:
            raise WizardError(
                f"Lista `{path}` musi zawierać dokładnie jeden element wzorcowy (ma {len(node)})."
            )
        return [_validate_template_node(node[0], f"{path}[]")]
    if node is not None:
        raise WizardError(f"Liść `{path}` musi mieć wartość null (otrzymano: {node!r}).")
    return None


def coerce_proposed_template(raw: Any) -> dict[str, Any]:
    """Coerce an LLM-proposed szablon into a valid template (leaves -> null, lists -> 1 item)."""
    if not isinstance(raw, dict) or not raw:
        raise WizardLlmError("Model nie zwrócił poprawnego obiektu `szablon`.")

    def _clean(node: Any, path: str) -> Any:
        if isinstance(node, dict):
            if not node:
                return None
            cleaned = {}
            for k, v in node.items():
                key = str(k).strip()
                if not key:
                    continue
                cleaned[key] = _clean(v, f"{path}.{key}" if path else key)
            return cleaned or None
        if isinstance(node, list):
            if not node:
                return None
            return [_clean(node[0], f"{path}[]")]
        return None

    result = _clean(raw, "")
    if not isinstance(result, dict) or not result:
        raise WizardLlmError("Zaproponowany `szablon` jest pusty.")
    return validate_template(result)


def normalize_typy(szablon: dict[str, Any], raw_typy: Any) -> dict[str, str]:
    """Return a typy mapping for every leaf of szablon in leaf order."""
    mapping = raw_typy if isinstance(raw_typy, dict) else {}
    out: dict[str, str] = {}
    for leaf in config.leaf_paths(szablon):
        t = mapping.get(leaf, "str")
        out[leaf] = t if t in config.TYPES else "str"
    return out


# ---- bounded OCR text formatting for LLM prompts -----------------------------------------------


def _format_examples_for_llm(files: list[WizardFile]) -> str:
    """Format OCR pages of uploaded files with strict character caps (bounded input)."""
    blocks: list[str] = []
    remaining = MAX_TOTAL_CHARS
    for f in files:
        if not f.pages or remaining <= 0:
            continue
        page_texts = [p["text"] for p in f.pages]
        joined = prompts.document_text(page_texts)
        cap = min(MAX_CHARS_PER_DOC, remaining)
        if len(joined) > cap:
            joined = joined[:cap].rstrip() + "\n[... ucięto ze względu na limit znaków ...]"
        remaining -= len(joined)
        blocks.append(f"### Plik: {f.filename}\n{joined}")
    return "\n\n".join(blocks)


def _prompt_template(name: str) -> str:
    return (config.CONFIG_DIR / f"prompt_{name}.md").read_text(encoding="utf-8")


# ---- YAML rendering & validation (via real config.load_class) ----------------------------------


def _sanitize_id(raw_id: Any, szablon: dict[str, Any], existing: set[str]) -> str:
    cand = str(raw_id or "").strip().lower()
    cand = re.sub(r"[^a-z0-9_]+", "_", cand).strip("_")
    if not cand or not cand[0].isalpha():
        first_key = next(iter(szablon.keys()), "nowa_klasa")
        cand = re.sub(r"[^a-z0-9_]+", "_", str(first_key).lower()).strip("_") or "nowa_klasa"
        if not cand[0].isalpha():
            cand = f"klasa_{cand}"
    if cand == config.OTHER:
        cand = "nowa_klasa"
    base = cand
    idx = 2
    while cand in existing or cand == config.OTHER:
        cand = f"{base}_{idx}"
        idx += 1
    return cand


def _coerce_wartosci(raw_values: Any, typ: str) -> dict[Any, str] | None:
    if not isinstance(raw_values, dict) or not raw_values:
        return None
    out: dict[Any, str] = {}
    for k, v in raw_values.items():
        if v is None:
            continue
        desc = str(v).strip()
        if not desc:
            continue
        key: Any = k
        if typ == "int":
            if isinstance(k, bool):
                continue
            try:
                key = int(k)
            except (ValueError, TypeError):
                continue
        elif typ == "float":
            if isinstance(k, bool):
                continue
            try:
                key = float(k)
            except (ValueError, TypeError):
                continue
        else:
            key = str(k)
        out[key] = desc
    return out or None


def build_yaml_from_proposal(
    proposal: dict[str, Any],
    szablon: dict[str, Any],
    typy: dict[str, str],
    existing_ids: set[str],
) -> str:
    """Assemble a clean, schema-consistent YAML document from an LLM JSON proposal."""
    if not isinstance(proposal, dict):
        raise WizardLlmError("Model nie zwrócił obiektu JSON z konfiguracją klasy.")

    leaves = config.leaf_paths(szablon)
    cid = _sanitize_id(proposal.get("id"), szablon, existing_ids)
    nazwa = str(proposal.get("nazwa") or "").strip() or cid.replace("_", " ").capitalize()
    opis = str(proposal.get("opis") or "").strip() or f"Dokument klasy {nazwa}."

    cechy_raw = proposal.get("cechy")
    cechy = (
        [str(x).strip() for x in cechy_raw if str(x).strip()] if isinstance(cechy_raw, list) else []
    )

    nie_mylic_raw = proposal.get("nie_mylic_z")
    nie_mylic = (
        [str(x).strip() for x in nie_mylic_raw if str(x).strip()]
        if isinstance(nie_mylic_raw, list)
        else []
    )

    czyt_raw = proposal.get("czytanie") if isinstance(proposal.get("czytanie"), dict) else {}
    max_stron = czyt_raw.get("max_stron", DEFAULT_MAX_PAGES)
    if isinstance(max_stron, bool) or not isinstance(max_stron, int) or max_stron < 1:
        max_stron = DEFAULT_MAX_PAGES
    czytanie: dict[str, Any] = {"max_stron": max_stron}
    znacznik = czyt_raw.get("znacznik")
    if isinstance(znacznik, str) and znacznik.strip():
        czytanie["znacznik"] = znacznik.strip()
        after = czyt_raw.get("stron_po_znaczniku", 0)
        if not isinstance(after, bool) and isinstance(after, int) and after >= 0:
            czytanie["stron_po_znaczniku"] = after
    kompletny = czyt_raw.get("kompletny_gdy")
    if isinstance(kompletny, str) and kompletny.strip():
        czytanie["kompletny_gdy"] = kompletny.strip()

    raw_pola = proposal.get("pola") if isinstance(proposal.get("pola"), dict) else {}
    pola: dict[str, dict[str, Any]] = {}
    for leaf in leaves:
        r = raw_pola.get(leaf) if isinstance(raw_pola.get(leaf), dict) else {}
        typ = typy.get(leaf, "str")
        if typ not in config.TYPES:
            typ = "str"
        field_opis = (
            str(r.get("opis") or "").strip()
            or f"Wartość pola {leaf}. Zwróć null, jeśli brak w dokumencie."
        )
        entry: dict[str, Any] = {"opis": field_opis, "typ": typ}

        norm = r.get("normalizacja")
        if isinstance(norm, str) and norm in config.NORMALIZERS:
            if norm == "regex_sub":
                params = r.get("parametry")
                if isinstance(params, dict) and "pattern" in params and "repl" in params:
                    entry["normalizacja"] = norm
                    entry["parametry"] = {
                        "pattern": str(params["pattern"]),
                        "repl": str(params["repl"]),
                    }
            else:
                entry["normalizacja"] = norm

        fmt = r.get("format")
        if isinstance(fmt, str) and fmt.strip():
            entry["format"] = fmt.strip()

        wart = _coerce_wartosci(r.get("wartosci"), typ)
        if wart:
            entry["wartosci"] = wart

        przyk = r.get("przyklady")
        if isinstance(przyk, list):
            cleaned_ex = [x for x in przyk if x is not None and x != ""]
            if cleaned_ex:
                entry["przyklady"] = cleaned_ex

        popr = r.get("poprawki_ocr")
        if isinstance(popr, str) and popr.strip():
            entry["poprawki_ocr"] = popr.strip()

        pola[leaf] = entry

    doc: dict[str, Any] = {
        "id": cid,
        "nazwa": nazwa,
        "opis": opis,
    }
    if cechy:
        doc["cechy"] = cechy
    if nie_mylic:
        doc["nie_mylic_z"] = nie_mylic
    doc["czytanie"] = czytanie
    doc["szablon"] = szablon
    doc["pola"] = pola

    instr = proposal.get("instrukcje")
    if isinstance(instr, str) and instr.strip():
        doc["instrukcje"] = instr.strip()

    return yaml.safe_dump(
        doc,
        allow_unicode=True,
        sort_keys=False,
        width=100,
        default_flow_style=False,
    )


def _yaml_line_map(yaml_text: str) -> dict[str, int]:
    """Map dotted config keys (e.g. 'czytanie.max_stron', 'pola.a.format') to 1-based lines."""
    line_map: dict[str, int] = {}
    try:
        root = yaml.compose(yaml_text)
    except yaml.YAMLError:
        return line_map
    if not isinstance(root, yaml.MappingNode):
        return line_map

    def walk(node: yaml.Node, prefix: str) -> None:
        if isinstance(node, yaml.MappingNode):
            for k_node, v_node in node.value:
                key = str(k_node.value)
                full = f"{prefix}.{key}" if prefix else key
                line_map.setdefault(full, k_node.start_mark.line + 1)
                walk(v_node, full)
        elif isinstance(node, yaml.SequenceNode):
            if node.value:
                walk(node.value[0], f"{prefix}[]")

    walk(root, "")
    return line_map


def _find_line_for_key(line_map: dict[str, int], key: str) -> int | None:
    if not key:
        return None
    if key in line_map:
        return line_map[key]
    # Try prefix fallback (e.g. 'pola.a.b.format' -> 'pola.a.b' -> 'pola')
    parts = key.split(".")
    for i in range(len(parts) - 1, 0, -1):
        cand = ".".join(parts[:i])
        if cand in line_map:
            return line_map[cand]
    # Handle szablon leaf paths (config._check_template reports paths without 'szablon.' prefix)
    if f"szablon.{key}" in line_map:
        return line_map[f"szablon.{key}"]
    return None


def _parse_config_error(
    err: config.ConfigError, stem: str, line_map: dict[str, int]
) -> dict[str, Any]:
    msg = str(err)
    prefix = f"{stem}.yaml: "
    rest = msg[len(prefix) :] if msg.startswith(prefix) else msg
    key = ""
    detail = rest
    if ": " in rest:
        cand_key, cand_detail = rest.split(": ", 1)
        if cand_key != "not valid YAML" and " " not in cand_key:
            key = cand_key
            detail = cand_detail
    line = _find_line_for_key(line_map, key)
    return {
        "line": line,
        "column": None,
        "key": key or None,
        "message": f"{key}: {detail}" if key else detail,
    }


def load_draft_class(
    yaml_text: str,
) -> tuple[config.DocClass | None, str | None, list[dict[str, Any]]]:
    """Validate draft YAML text via the real json4win.config.load_class().

    Returns (DocClass or None, class_id or None, errors list).
    """
    if not isinstance(yaml_text, str) or not yaml_text.strip():
        return (
            None,
            None,
            [{"line": 1, "column": 1, "key": None, "message": "Plik YAML jest pusty."}],
        )

    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        problem = getattr(exc, "problem", None) or str(exc)
        return (
            None,
            None,
            [
                {
                    "line": mark.line + 1 if mark is not None else None,
                    "column": mark.column + 1 if mark is not None else None,
                    "key": None,
                    "message": f"Błąd składni YAML: {problem}",
                }
            ],
        )

    line_map = _yaml_line_map(yaml_text)
    if not isinstance(raw, dict):
        return (
            None,
            None,
            [
                {
                    "line": 1,
                    "column": 1,
                    "key": None,
                    "message": "Konfiguracja musi być mapowaniem YAML.",
                }
            ],
        )

    raw_id = raw.get("id")
    cid_str: str | None = raw_id.strip() if isinstance(raw_id, str) and raw_id.strip() else None

    if cid_str is not None and not _VALID_ID_RE.fullmatch(cid_str):
        return (
            None,
            cid_str,
            [
                {
                    "line": _find_line_for_key(line_map, "id"),
                    "column": None,
                    "key": "id",
                    "message": (
                        f"id: niedozwolone znaki w {cid_str!r} "
                        "(dozwolone: litery ASCII, cyfry, _ i -, bez spacji i ukośników)"
                    ),
                }
            ],
        )

    stem = cid_str if cid_str is not None else "__draft__"
    with tempfile.TemporaryDirectory(prefix="json4win-validate-") as td:
        tmp_file = Path(td) / f"{stem}.yaml"
        tmp_file.write_text(yaml_text, encoding="utf-8")
        try:
            doc_class = config.load_class(tmp_file)
        except config.ConfigError as exc:
            return None, cid_str, [_parse_config_error(exc, stem, line_map)]

    return doc_class, doc_class.id, []


def evaluate_marker(yaml_text: str, files: list[WizardFile]) -> dict[str, Any] | None:
    """Test czytanie.znacznik regex live against all OCR'd pages."""
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return None
    if not isinstance(raw, dict):
        return None
    czyt = raw.get("czytanie")
    if not isinstance(czyt, dict):
        return None
    pattern = czyt.get("znacznik")
    max_stron = czyt.get("max_stron")
    after = czyt.get("stron_po_znaczniku", 0)
    if not isinstance(after, int) or isinstance(after, bool) or after < 0:
        after = 0

    if pattern is None or (isinstance(pattern, str) and not pattern.strip()):
        return {
            "pattern": None,
            "stron_po_znaczniku": after,
            "max_stron": max_stron if isinstance(max_stron, int) else None,
            "error": None,
            "results": [],
        }
    if not isinstance(pattern, str):
        return {
            "pattern": str(pattern),
            "stron_po_znaczniku": after,
            "max_stron": max_stron if isinstance(max_stron, int) else None,
            "error": "Znacznik musi być tekstem.",
            "results": [],
        }

    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return {
            "pattern": pattern,
            "stron_po_znaczniku": after,
            "max_stron": max_stron if isinstance(max_stron, int) else None,
            "error": f"Niepoprawny regex: {exc}",
            "results": [],
        }

    results: list[dict[str, Any]] = []
    for f in files:
        matched_pages: list[int] = []
        first_page: int | None = None
        first_snippet: str | None = None
        cumulative_parts: list[str] = []
        for p in f.pages:
            page_num = int(p["page"])
            text = str(p["text"])
            cumulative_parts.append(text)
            m_page = compiled.search(text)
            if m_page:
                matched_pages.append(page_num)
                if first_page is None:
                    first_page = page_num
                    a = max(0, m_page.start() - _MARKER_SNIPPET_RADIUS)
                    b = min(len(text), m_page.end() + _MARKER_SNIPPET_RADIUS)
                    first_snippet = " ".join(text[a:b].split())
            elif first_page is None:
                # Match decide.read_pages cumulative check across page boundary
                m_cum = compiled.search("\n".join(cumulative_parts))
                if m_cum:
                    first_page = page_num
                    joined = "\n".join(cumulative_parts)
                    a = max(0, m_cum.start() - _MARKER_SNIPPET_RADIUS)
                    b = min(len(joined), m_cum.end() + _MARKER_SNIPPET_RADIUS)
                    first_snippet = " ".join(joined[a:b].split())
        stop_after = (
            min(max_stron, first_page + after)
            if first_page is not None and isinstance(max_stron, int) and max_stron >= 1
            else (first_page + after if first_page is not None else None)
        )
        results.append(
            {
                "doc_id": f.doc_id,
                "filename": f.filename,
                "matched": first_page is not None,
                "first_match_page": first_page,
                "matched_pages": matched_pages,
                "snippet": first_snippet,
                "pages_checked": len(f.pages),
                "would_stop_after_page": stop_after,
            }
        )

    return {
        "pattern": pattern,
        "stron_po_znaczniku": after,
        "max_stron": max_stron if isinstance(max_stron, int) else None,
        "error": None,
        "results": results,
    }


# ---- Wizard session state ----------------------------------------------------------------------


@dataclass
class WizardFile:
    doc_id: str
    filename: str
    path: Path
    size: int
    status: str = "idle"  # idle | ocr | done | error
    total_pages: int | None = None
    pages: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "filename": self.filename,
            "size": self.size,
            "status": self.status,
            "total_pages": self.total_pages,
            "pages": list(self.pages),
            "error": self.error,
        }


class WizardState:
    """In-memory + temp-dir state for the 3-stage config wizard."""

    def __init__(
        self,
        *,
        wizard_dir: Path | None = None,
        config_dir: Path | None = None,
        forbidden_dirs: tuple[Path, ...] = (),
    ) -> None:
        self._owns_dir = wizard_dir is None
        base = (
            Path(tempfile.mkdtemp(prefix="json4win-wizard-")) if wizard_dir is None else wizard_dir
        )
        base.mkdir(parents=True, exist_ok=True)
        self.wizard_dir = base.resolve()
        for forbidden in forbidden_dirs:
            f_res = forbidden.resolve()
            if self.wizard_dir == f_res or self.wizard_dir.is_relative_to(f_res):
                raise WizardError(
                    "Katalog roboczy kreatora nie może znajdować się w output/ ani input/."
                )
        self._config_dir_override = config_dir.resolve() if config_dir is not None else None
        self._lock = threading.Lock()
        self._ocr_lock = threading.Lock()
        self._files: list[WizardFile] = []
        self._max_pages: int = DEFAULT_MAX_PAGES
        self._hint: str = ""
        self._szablon: dict[str, Any] | None = None
        self._typy: dict[str, str] = {}
        self._previews: list[dict[str, Any]] = []
        self._yaml_text: str = ""
        self._last_test: dict[str, Any] | None = None

    def close(self) -> None:
        if self._owns_dir and self.wizard_dir.exists():
            shutil.rmtree(self.wizard_dir, ignore_errors=True)

    def config_dir(self) -> Path:
        return target_config_dir(self._config_dir_override)

    def snapshot(self) -> dict[str, Any]:
        existing = sorted(_load_existing_classes_safe().keys())
        with self._lock:
            return {
                "config_dir": str(self.config_dir()),
                "existing_classes": existing,
                "max_files": MAX_WIZARD_FILES,
                "max_pages": self._max_pages,
                "hint": self._hint,
                "files": [f.to_dict() for f in self._files],
                "szablon": self._szablon,
                "typy": dict(self._typy),
                "previews": list(self._previews),
                "yaml_text": self._yaml_text,
                "last_test": self._last_test,
            }

    def reset(self) -> dict[str, Any]:
        with self._lock:
            for f in self._files:
                shutil.rmtree(f.path.parent, ignore_errors=True)
            self._files = []
            self._max_pages = DEFAULT_MAX_PAGES
            self._hint = ""
            self._szablon = None
            self._typy = {}
            self._previews = []
            self._yaml_text = ""
            self._last_test = None
        return self.snapshot()

    def add_upload(self, filename_raw: str, data: bytes) -> dict[str, Any]:
        filename = validate_pdf_filename(filename_raw)
        if not data:
            raise WizardError("Plik jest pusty.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise OverflowError("Plik przekracza maksymalny dozwolony rozmiar.")

        with self._lock:
            if len(self._files) >= MAX_WIZARD_FILES:
                raise WizardError(f"Maksymalnie {MAX_WIZARD_FILES} przykładowych plików PDF.")
            doc_id = uuid.uuid4().hex[:10]
            doc_dir = (self.wizard_dir / doc_id).resolve()
            if not doc_dir.is_relative_to(self.wizard_dir) or doc_dir.parent != self.wizard_dir:
                raise WizardError("Niedozwolona ścieżka robocza.")
            target = (doc_dir / filename).resolve()
            if not target.is_relative_to(self.wizard_dir) or target.parent != doc_dir:
                raise WizardError("Niedozwolona ścieżka pliku.")
            doc_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

            entry = WizardFile(doc_id=doc_id, filename=filename, path=target, size=len(data))
            self._files.append(entry)
            log.info("wizard uploaded %s (%d bytes)", filename, len(data))
            return entry.to_dict()

    def remove_file(self, doc_id: str) -> dict[str, Any]:
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise WizardError("Brak identyfikatora pliku.")
        with self._lock:
            idx = next((i for i, f in enumerate(self._files) if f.doc_id == doc_id), None)
            if idx is None:
                raise FileNotFoundError(f"Nie znaleziono pliku: {doc_id}")
            removed = self._files.pop(idx)
            self._previews = [p for p in self._previews if p.get("doc_id") != doc_id]
        shutil.rmtree(removed.path.parent, ignore_errors=True)
        return self.snapshot()

    def run_ocr(
        self, *, doc_id: str | None = None, max_pages: int = DEFAULT_MAX_PAGES
    ) -> dict[str, Any]:
        if (
            isinstance(max_pages, bool)
            or not isinstance(max_pages, int)
            or not (1 <= max_pages <= MAX_PAGES_LIMIT)
        ):
            raise WizardError(f"Liczba stron musi być liczbą całkowitą od 1 do {MAX_PAGES_LIMIT}.")

        with self._lock:
            self._max_pages = max_pages
            if doc_id is not None:
                targets = [f for f in self._files if f.doc_id == doc_id]
                if not targets:
                    raise FileNotFoundError(f"Nie znaleziono pliku: {doc_id}")
            else:
                targets = list(self._files)
                if not targets:
                    raise WizardError("Wgraj co najmniej jeden przykładowy plik PDF.")

        # Serialize OCR so at most one OCR process/call runs at a time.
        with self._ocr_lock:
            for wf in targets:
                with self._lock:
                    wf.status = "ocr"
                    wf.error = None
                try:
                    total = ocr.page_count(wf.path)
                    limit = min(max_pages, total)
                    pages: list[dict[str, Any]] = []
                    for page_idx in range(limit):
                        text = ocr.ocr_page(wf.path, page_idx)
                        pages.append(
                            {
                                "page": page_idx + 1,
                                "text": text,
                                "chars": len(text),
                            }
                        )
                    with self._lock:
                        wf.total_pages = total
                        wf.pages = pages
                        wf.status = "done"
                        wf.error = None
                    log.info("wizard OCR %s: %d/%d pages", wf.filename, len(pages), total)
                except Exception as exc:
                    log.warning("wizard OCR %s failed: %s", wf.filename, exc)
                    with self._lock:
                        wf.status = "error"
                        wf.error = str(exc)

        with self._lock:
            if doc_id is not None:
                return {"file": targets[0].to_dict(), "max_pages": self._max_pages}
            return {"files": [f.to_dict() for f in self._files], "max_pages": self._max_pages}

    def _ready_files(self) -> list[WizardFile]:
        with self._lock:
            ready = [f for f in self._files if f.pages]
        if not ready:
            raise WizardError(
                "Najpierw odczytaj OCR dla co najmniej jednego przykładowego pliku PDF."
            )
        return ready

    def _align_previews(
        self, szablon: dict[str, Any], raw_previews: Any, ready: list[WizardFile]
    ) -> list[dict[str, Any]]:
        by_name: dict[str, Any] = {}
        ordered_list: list[Any] = []
        if isinstance(raw_previews, list):
            for item in raw_previews:
                if isinstance(item, dict):
                    dane = item.get("dane")
                    plik = item.get("plik")
                    if isinstance(plik, str) and plik.strip():
                        by_name[plik.strip()] = dane
                    ordered_list.append(dane)
        elif isinstance(raw_previews, dict):
            by_name = raw_previews

        aligned: list[dict[str, Any]] = []
        for idx, wf in enumerate(ready):
            raw_data = by_name.get(wf.filename)
            if raw_data is None and idx < len(ordered_list):
                raw_data = ordered_list[idx]
            coerced = validate.coerce(szablon, raw_data)
            aligned.append(
                {
                    "doc_id": wf.doc_id,
                    "filename": wf.filename,
                    "data": coerced,
                }
            )
        return aligned

    def propose_szablon(self, hint: str = "") -> dict[str, Any]:
        ready = self._ready_files()
        clean_hint = str(hint or "").strip()[:MAX_HINT_CHARS]
        hint_block = f"\nDodatkowa wskazówka użytkownika: {clean_hint}\n" if clean_hint else ""
        docs_text = _format_examples_for_llm(ready)
        prompt = prompts.fill(
            _prompt_template("kreator_szablon"),
            DOKUMENTY=docs_text,
            WSKAZOWKA=hint_block,
        )
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": "Zaproponuj `szablon`, `typy` oraz `podglady` jako obiekt JSON.",
            },
        ]
        try:
            answer = llm.chat_json(llm.model("extract"), messages, role="extract")
        except llm.LlmError as exc:
            raise WizardLlmError(f"Błąd modelu LLM: {exc}") from exc

        szablon = coerce_proposed_template(answer.get("szablon"))
        typy = normalize_typy(szablon, answer.get("typy"))
        previews = self._align_previews(szablon, answer.get("podglady"), ready)

        with self._lock:
            self._hint = clean_hint
            self._szablon = szablon
            self._typy = typy
            self._previews = previews

        return {"szablon": szablon, "typy": typy, "previews": previews}

    def refresh_preview(self, szablon_raw: Any, typy_raw: Any = None) -> dict[str, Any]:
        ready = self._ready_files()
        szablon = validate_template(szablon_raw)
        typy = normalize_typy(szablon, typy_raw)

        # Persist user's valid edited shape even before LLM call
        with self._lock:
            self._szablon = szablon
            self._typy = typy

        typy_lines = "\n".join(f"- `{p}`: {t}" for p, t in typy.items())
        prompt = prompts.fill(
            _prompt_template("kreator_podglad"),
            SZABLON=json.dumps(szablon, ensure_ascii=False, indent=2),
            TYPY=typy_lines,
            DOKUMENTY=_format_examples_for_llm(ready),
        )
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": "Zwróć obiekt JSON z kluczem `podglady` dla wszystkich dokumentów.",
            },
        ]
        try:
            answer = llm.chat_json(llm.model("extract"), messages, role="extract")
        except llm.LlmError as exc:
            raise WizardLlmError(f"Błąd modelu LLM: {exc}") from exc

        if not isinstance(answer, dict) or "podglady" not in answer:
            raise WizardLlmError("Odpowiedź modelu nie zawiera pola `podglady`.")

        previews = self._align_previews(szablon, answer.get("podglady"), ready)
        with self._lock:
            self._previews = previews
        return {"szablon": szablon, "typy": typy, "previews": previews}

    def propose_yaml(
        self, szablon_raw: Any, typy_raw: Any = None, hint: str = ""
    ) -> dict[str, Any]:
        ready = self._ready_files()
        szablon = validate_template(szablon_raw)
        typy = normalize_typy(szablon, typy_raw)
        clean_hint = str(hint or "").strip()[:MAX_HINT_CHARS]

        with self._lock:
            self._szablon = szablon
            self._typy = typy
            if clean_hint:
                self._hint = clean_hint
            effective_hint = clean_hint or self._hint

        existing = _load_existing_classes_safe()
        existing_ids = set(existing.keys())
        existing_text = ", ".join(sorted(existing_ids)) if existing_ids else "(brak)"
        sciezki_text = "\n".join(f"- `{p}` (typ: {t})" for p, t in typy.items())
        hint_block = (
            f"\nDodatkowa wskazówka użytkownika: {effective_hint}\n" if effective_hint else ""
        )

        prompt = prompts.fill(
            _prompt_template("kreator_yaml"),
            SZABLON=json.dumps(szablon, ensure_ascii=False, indent=2),
            SCIEZKI=sciezki_text,
            ISTNIEJACE_KLASY=existing_text,
            DOKUMENTY=_format_examples_for_llm(ready),
            WSKAZOWKA=hint_block,
        )
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": "Zwróć pełną propozycję konfiguracji klasy jako obiekt JSON.",
            },
        ]
        try:
            answer = llm.chat_json(llm.model("extract"), messages, role="extract")
        except llm.LlmError as exc:
            raise WizardLlmError(f"Błąd modelu LLM: {exc}") from exc

        yaml_text = build_yaml_from_proposal(answer, szablon, typy, existing_ids)
        with self._lock:
            self._yaml_text = yaml_text
            self._last_test = None

        validation = self.validate_yaml(yaml_text, save_draft=False)
        return {"yaml_text": yaml_text, "validation": validation}

    def validate_yaml(self, yaml_text: str, *, save_draft: bool = True) -> dict[str, Any]:
        if not isinstance(yaml_text, str):
            raise WizardError("Treść YAML musi być tekstem.")
        with self._lock:
            if save_draft:
                self._yaml_text = yaml_text
            files = list(self._files)

        doc_class, cid, errors = load_draft_class(yaml_text)
        save_dir = self.config_dir()
        filename = f"{cid}.yaml" if cid and _VALID_ID_RE.fullmatch(cid) else None
        exists = False
        warnings: list[str] = []

        if filename is not None:
            target = (save_dir / filename).resolve()
            if target.is_relative_to(save_dir) and target.parent == save_dir:
                exists = target.exists()

        if doc_class is not None:
            existing = _load_existing_classes_safe()
            if doc_class.id in existing:
                src = existing[doc_class.id].source
                if src is not None and src.parent.resolve() != save_dir:
                    warnings.append(
                        f"Klasa o id `{doc_class.id}` istnieje już w innym katalogu "
                        f"({src.parent}); loader zgłosi duplikat id, jeśli oba katalogi są aktywne."
                    )

        marker = evaluate_marker(yaml_text, files)
        return {
            "valid": doc_class is not None and not errors,
            "id": cid,
            "filename": filename,
            "target_dir": str(save_dir),
            "exists": exists,
            "errors": errors,
            "warnings": warnings,
            "marker": marker,
        }

    def test_draft(self, yaml_text: str) -> dict[str, Any]:
        doc_class, _, errors = load_draft_class(yaml_text)
        if doc_class is None or errors:
            raise WizardError(
                errors[0]["message"] if errors else "Konfiguracja YAML zawiera błędy."
            )

        with self._lock:
            self._yaml_text = yaml_text
            files = list(self._files)
        if not files:
            raise WizardError("Brak przykładowych plików PDF do przetestowania.")

        existing = _load_existing_classes_safe()
        known = {**existing, doc_class.id: doc_class}
        results: list[dict[str, Any]] = []

        with self._ocr_lock:
            for wf in files:
                try:
                    first = ocr.ocr_page(wf.path, 0)
                    cid = decide.classify(first, known)
                    if cid is None:
                        results.append(
                            {
                                "doc_id": wf.doc_id,
                                "filename": wf.filename,
                                "decision": config.OTHER,
                                "matched_draft": False,
                                "pages_read": 1,
                                "data": {},
                                "retries": 0,
                                "nulled": [],
                                "validation_rounds": [],
                                "error": None,
                            }
                        )
                        continue
                    chosen = known[cid]
                    pages = decide.read_pages(wf.path, chosen, first)
                    ex = extract.extract(chosen, pages)
                    results.append(
                        {
                            "doc_id": wf.doc_id,
                            "filename": wf.filename,
                            "decision": cid,
                            "matched_draft": cid == doc_class.id,
                            "pages_read": len(pages),
                            "data": ex.data,
                            "retries": ex.retries,
                            "nulled": list(ex.nulled),
                            "validation_rounds": list(ex.rounds),
                            "error": None,
                        }
                    )
                except Exception as exc:
                    log.warning("wizard test %s failed: %s", wf.filename, exc)
                    results.append(
                        {
                            "doc_id": wf.doc_id,
                            "filename": wf.filename,
                            "decision": None,
                            "matched_draft": False,
                            "pages_read": 0,
                            "data": {},
                            "retries": 0,
                            "nulled": [],
                            "validation_rounds": [],
                            "error": str(exc),
                        }
                    )

        payload = {"class_id": doc_class.id, "results": results}
        with self._lock:
            self._last_test = payload
        return payload

    def save_yaml(self, yaml_text: str, *, overwrite: bool = False) -> dict[str, Any]:
        doc_class, _, errors = load_draft_class(yaml_text)
        if doc_class is None or errors:
            raise WizardError(
                errors[0]["message"] if errors else "Konfiguracja YAML zawiera błędy."
            )

        cid = doc_class.id
        if not _VALID_ID_RE.fullmatch(cid) or cid == config.OTHER:
            raise WizardError(f"Nieprawidłowy identyfikator klasy: {cid!r}.")

        save_dir = self.config_dir()
        save_dir.mkdir(parents=True, exist_ok=True)
        target = (save_dir / f"{cid}.yaml").resolve()
        if not target.is_relative_to(save_dir) or target.parent != save_dir:
            raise WizardError("Niedozwolona ścieżka zapisu.")

        if target.exists() and not overwrite:
            raise WizardConflictError(target, save_dir)

        content = yaml_text if yaml_text.endswith("\n") else yaml_text + "\n"
        target.write_text(content, encoding="utf-8")

        # Verify the saved file loads cleanly with the real loader.
        try:
            config.load_class(target)
        except config.ConfigError as exc:
            raise WizardError(f"Zapisany plik nie przechodzi walidacji loadera: {exc}") from exc

        pipeline.classes.cache_clear()
        with self._lock:
            self._yaml_text = content
        log.info("wizard saved class %s -> %s", cid, target)
        return {
            "saved": True,
            "id": cid,
            "filename": target.name,
            "path": str(target),
            "target_dir": str(save_dir),
        }
