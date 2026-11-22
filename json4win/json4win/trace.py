"""Extraction trace (transparency): how every output value of one PDF was obtained.

For each processed PDF, `<trace_dir>/<case>/<name>.trace.json` (machine-readable) and
`<name>.trace.md` (a Polish table for people) record the PDF hash, the OCR pages read, every LLM
call (attempts, finish reasons, token usage, time), the decision, the reading loop, the extraction
rounds and, per output field, the final value, the raw LLM value, the normaliser and the value's
provenance: the page and a snippet of the OCR text where the raw value was found by a
deterministic fuzzy search (difflib), or "not found in text".

The recorder lives in a contextvar set by `document()`; the hooks below are no-ops without one, so
the pipeline runs unchanged when tracing is off. Traces never go into output/ (architecture D3) and
never contain the API key; OCR snippets are fine (the trace stays local).
"""

import hashlib
import json
import logging
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from json4win import env, ocr, validate
from json4win.config import DocClass, FieldRule

log = logging.getLogger(__name__)

SNIPPET = 60  # chars of context on each side of a match
MIN_SCORE = {"text": 0.75, "digits": 0.85}  # fuzzy matches below this are "not found in text"
MIN_LEN = 3  # shorter needles would match anywhere

NOT_FOUND = "not found in text"
TOO_SHORT = "too short to locate"
FROM_LIST = "chosen from allowed values"

METHOD_LLM = "llm"
METHOD_NORM = "llm+normalizacja"
METHOD_NULLED = "walidacja→null"


class Trace:
    """The record of one document; `data` is what goes into the .trace.json."""

    def __init__(self, pdf: Path, name: str) -> None:
        self.data: dict[str, Any] = {
            "pdf": name,
            "sha256": None,
            "started": datetime.now().astimezone().isoformat(timespec="seconds"),
            "status": "ok",
            "class": None,
            "steps_s": {},
            "ocr_pages": [],
        }
        self.pdf = pdf
        self.failed_step: str | None = None


_active: ContextVar[Trace | None] = ContextVar("json4win_trace", default=None)


# --- hooks used by the pipeline (no-ops when no trace is active) -------------------------------


def put(key: str, value: Any) -> None:
    if t := _active.get():
        t.data[key] = value


def add(key: str, item: Any) -> None:
    """Append `item` to the list `key`."""
    if t := _active.get():
        t.data.setdefault(key, []).append(item)


def count(key: str) -> None:
    if t := _active.get():
        t.data[key] = t.data.get(key, 0) + 1


@contextmanager
def step(name: str) -> Iterator[None]:
    """Time a pipeline step; if it raises, remember it as the step where the document failed."""
    t = _active.get()
    t0 = time.perf_counter()
    try:
        yield
    except BaseException:
        if t and t.failed_step is None:
            t.failed_step = name
        raise
    finally:
        if t:
            t.data["steps_s"][name] = round(time.perf_counter() - t0, 3)


def ocr_page(pdf: Path, index: int) -> str:
    """ocr.ocr_page(), with the page's backend, size and time recorded."""
    t0 = time.perf_counter()
    text = ocr.ocr_page(pdf, index)
    add(
        "ocr_pages",
        {
            "page": index + 1,
            "backend": ocr.page_backend(index),
            "chars": len(text),
            "seconds": round(time.perf_counter() - t0, 3),
        },
    )
    return text


def extraction(c: DocClass, ex: Any, pages: list[str]) -> None:
    """Record an extract.Extraction: the rounds, and every field with its provenance."""
    t = _active.get()
    if t is None:
        return
    t.data["extraction"] = {
        "model": ex.model,
        "llm_calls": ex.calls,
        "retries": ex.retries,
        "validation_errors": ex.rounds,  # per round: still-invalid fields after that round
        "nulled": ex.nulled,
    }
    t.data["fields"] = field_records(c, ex.data, ex.raw, ex.nulled, pages)
    t.data["result"] = ex.data


# --- per-field provenance ---------------------------------------------------------------------


def field_records(
    c: DocClass, data: dict, raw: dict, nulled: list[str], pages: list[str]
) -> list[dict]:
    out = []
    for rule_path, path, value in validate.leaves(data):
        rule = c.pola[rule_path]
        try:
            raw_value = validate.get_at(raw, path)
        except (KeyError, IndexError, TypeError):
            raw_value = None
        name = validate.show_path(path)
        if name in nulled:
            method = METHOD_NULLED
        elif rule.normalizacja and value is not None and value != raw_value:
            method = METHOD_NORM
        else:
            method = METHOD_LLM
        shown = raw_value if raw_value is not None else value
        out.append(
            {
                "field": name,
                "value": value,
                "raw": raw_value,
                "normalizer": rule.normalizacja,
                "method": method,
                "provenance": provenance(rule, shown, value, pages),
            }
        )
    return out


def provenance(rule: FieldRule, raw: Any, value: Any, pages: list[str]) -> dict | None:
    """Where in the OCR pages the raw value (or else the final one) was found; None if no value."""
    if raw is None or isinstance(raw, bool):
        return None
    if rule.wartosci is not None:
        return {"status": FROM_LIST}
    best = locate(raw, pages, _digit_mode(rule, raw))
    if value is not None and value != raw and best.get("status") != "found":
        other = locate(value, pages, _digit_mode(rule, value))
        if other.get("score", 0) > best.get("score", 0):
            best = other
    return best


def _digit_mode(rule: FieldRule, v: Any) -> bool:
    if rule.normalizacja in ("digits", "amount", "int") or rule.typ in ("int", "float"):
        return True
    s = str(v)
    return bool(re.search(r"\d", s)) and re.fullmatch(r"[\d\s.,:;/()+\-]+", s) is not None


def locate(needle: Any, pages: list[str], digits: bool = False) -> dict:
    """Best match of `needle` in the pages: {page, snippet, score, status="found"} or a status.

    Text: case- and whitespace-insensitive, exact first, then the best SequenceMatcher window.
    Digits: only the digits are compared, inside runs of digits and separators of the page.
    """
    flatten = _digit_runs if digits else _flatten
    want = flatten(str(needle))[0].strip(" |")
    if len(want) < MIN_LEN:
        return {"status": TOO_SHORT}
    best = (0.0, -1, 0, 0)  # score, page index, start, end (in the page's original text)
    for i, page in enumerate(pages):
        hay, pos = flatten(page)
        score, s, e = _best_window(want, hay)
        if score > best[0] and e > s:
            best = (score, i, pos[s], pos[e - 1] + 1)
        if best[0] == 1.0:
            break
    score, i, s, e = best
    if score < MIN_SCORE["digits" if digits else "text"]:
        return {"status": NOT_FOUND}
    return {
        "status": "found",
        "page": i + 1,
        "score": round(score, 3),
        "snippet": snippet(pages[i], s, e),
    }


def snippet(text: str, start: int, end: int) -> str:
    a, b = max(0, start - SNIPPET), min(len(text), end + SNIPPET)
    s = " ".join(text[a:b].split())
    return ("…" if a > 0 else "") + s + ("…" if b < len(text) else "")


def _flatten(text: str) -> tuple[str, list[int]]:
    """Lowercased text with whitespace runs collapsed, and each char's index in `text`."""
    chars: list[str] = []
    pos: list[int] = []
    space = True
    for i, ch in enumerate(text):
        if ch.isspace():
            if not space:
                chars.append(" ")
                pos.append(i)
            space = True
            continue
        space = False
        for low in ch.lower():
            chars.append(low)
            pos.append(i)
    return "".join(chars), pos


_RUN = re.compile(r"\d(?:[ \t.,/\-]{0,3}\d)*")


def _digit_runs(text: str) -> tuple[str, list[int]]:
    """The digits of every digit run in `text`, runs separated by "|", with char indexes."""
    chars: list[str] = []
    pos: list[int] = []
    for m in _RUN.finditer(text):
        if chars:
            chars.append("|")
            pos.append(m.start())
        for j, ch in enumerate(m.group(), m.start()):
            if ch.isdigit():
                chars.append(ch)
                pos.append(j)
    return "".join(chars), pos


def _best_window(needle: str, hay: str) -> tuple[float, int, int]:
    """(ratio, start, end) of the window of `hay` most similar to `needle`."""
    k = hay.find(needle)
    if k >= 0:
        return 1.0, k, k + len(needle)
    n = len(needle)
    if not hay:
        return 0.0, 0, 0
    sm = SequenceMatcher(None, autojunk=False)
    sm.set_seq2(needle)
    best = (0.0, 0)

    def score(start: int) -> None:
        nonlocal best
        sm.set_seq1(hay[start : start + n])
        if sm.real_quick_ratio() > best[0] and sm.quick_ratio() > best[0]:
            r = sm.ratio()
            if r > best[0]:
                best = (r, start)

    stride = max(1, n // 4)
    last = max(0, len(hay) - n)
    for start in range(0, last + 1, stride):
        score(start)
    for start in range(max(0, best[1] - stride), min(last, best[1] + stride) + 1):
        score(start)
    r, s = best
    return r, s, min(len(hay), s + n)


# --- document lifecycle and files -------------------------------------------------------------


def default_dir() -> Path:
    """JSON4WIN_TRACE_DIR, or json4win/traces/."""
    return Path(env.get("JSON4WIN_TRACE_DIR") or env.APP_ROOT / "traces")


def trace_path(trace_dir: Path, rel: Path, suffix: str = ".json") -> Path:
    """`<trace_dir>/<case>/<name>.trace.json` (or .trace.md) for input `<case>/<name>.pdf`."""
    return trace_dir / rel.parent / f"{rel.stem}.trace{suffix}"


@contextmanager
def document(pdf: Path, path: Path | None, name: str | None = None) -> Iterator[Trace | None]:
    """Trace one document into `path` (a .trace.json; the .trace.md goes next to it).

    path=None: tracing off. An exception is recorded (type, message, step) and re-raised; the
    trace is written either way, and a failure to write it is only logged.
    """
    if path is None:
        yield None
        return
    t = Trace(pdf, name or pdf.name)
    token = _active.set(t)
    t0 = time.perf_counter()
    try:
        t.data["sha256"] = _sha256(pdf)
        yield t
    except Exception as e:
        t.data["status"] = "error"
        t.data["error"] = {
            "type": type(e).__name__,
            "message": scrub(str(e)),
            "step": t.failed_step,
        }
        raise
    finally:
        _active.reset(token)
        t.data["total_s"] = round(time.perf_counter() - t0, 3)
        calls = t.data.get("llm") or []
        t.data["llm_s"] = round(sum(c["seconds"] for c in calls), 3)
        log.info(
            "%s: LLM %d calls, %d attempts, %.1f s",
            t.data["pdf"],
            len(calls),
            sum(len(c["attempts"]) for c in calls),
            t.data["llm_s"],
        )
        try:
            write(t, path)
        except (OSError, TypeError, ValueError) as e:
            log.warning("trace %s not written: %s", path, e)


def _sha256(pdf: Path) -> str:
    h = hashlib.sha256()
    with pdf.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scrub(text: str) -> str:
    """`text` without the API key, should it ever appear in an error message."""
    key = env.get("MISTRAL_API_KEY")
    return text.replace(key, "***") if key and len(key) >= 8 else text


def write(t: Trace, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(t.data, ensure_ascii=False, indent=2, default=str)
    path.write_text(scrub(body) + "\n", encoding="utf-8")
    md = path.with_name(path.name.removesuffix(".json") + ".md")
    md.write_text(scrub(markdown(t.data)), encoding="utf-8")


# --- the Polish summary -----------------------------------------------------------------------


def _cell(v: Any) -> str:
    if v is None:
        return "null"
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return " ".join(s.split()).replace("|", "\\|")


_STATUS_PL = {
    NOT_FOUND: "nie znaleziono w tekście",
    TOO_SHORT: "wartość za krótka do wyszukania",
    FROM_LIST: "wartość z listy dozwolonych (nie cytat)",
}


def markdown(d: dict) -> str:
    lines = [f"# Ślad ekstrakcji: {d['pdf']}", ""]
    lines.append(f"- sha256: `{d.get('sha256')}`")
    if d.get("status") == "error":
        err = d.get("error") or {}
        lines.append(
            f"- **Błąd** w kroku `{err.get('step') or '?'}`: {err.get('type')}: "
            f"{_cell(err.get('message'))} → wynik `{{}}`"
        )
    dec = d.get("decision") or {}
    if dec:
        lines.append(
            f"- Klasa: **{d.get('class')}** (model decyzji `{dec.get('model')}`, "
            f"odpowiedź {_cell(dec.get('answer'))})"
        )
    pages = d.get("ocr_pages") or []
    if pages:
        shown = ", ".join(
            f"{p['page']} ({p['chars']} zn., {p['seconds']} s"
            + (f", {p['backend']}" if p.get("backend") else "")
            + ")"
            for p in pages
        )
        lines.append(f"- Strony OCR: {shown}")
    reading = d.get("reading") or {}
    if reading.get("marker_after_pages"):
        lines.append(
            f"- Znacznik `{reading.get('marker')}` po {reading['marker_after_pages']} str."
        )
    for q in d.get("completeness") or []:
        verdict = "tak" if q["complete"] else "nie"
        lines.append(f"- Kompletny po {q['pages_read']} str.? {verdict}")
    ex = d.get("extraction")
    if ex:
        lines.append(
            f"- Ekstrakcja: model `{ex['model']}`, wywołań LLM {ex['llm_calls']}, "
            f"poprawek {ex['retries']}, wyzerowane przez walidację: "
            f"{', '.join(ex['nulled']) or 'brak'}"
        )
        for i, errs in enumerate(ex["validation_errors"]):
            if errs:
                lines.append(f"  - runda {i}: " + "; ".join(_cell(e) for e in errs))
    calls = (d.get("decision_llm_calls") or 0) + (ex["llm_calls"] if ex else 0)
    lines.append(f"- Wywołań LLM łącznie: {calls} ({d.get('llm_s')} s)")
    for c in d.get("llm") or []:
        if len(c["attempts"]) > 1 or c.get("error"):
            tries = "; ".join(
                f"{a['outcome']} (max_tokens {a['max_tokens']}, "
                f"reasoning_effort {a['reasoning_effort'] or 'domyślny'})"
                for a in c["attempts"]
            )
            end = f" → błąd: {_cell(c['error'])}" if c.get("error") else ""
            lines.append(f"  - ponowienia `{c['model']}`: {tries}{end}")
    steps = ", ".join(f"{k} {v} s" for k, v in (d.get("steps_s") or {}).items())
    lines.append(f"- Czasy: {steps or '-'} (razem {d.get('total_s')} s)")
    fields = d.get("fields")
    if fields:
        lines += ["", "| pole | wartość | strona | fragment | metoda |", "|---|---|---|---|---|"]
        for f in fields:
            p = f.get("provenance")
            if p is None:
                page, frag = "", ""
            elif p.get("status") == "found":
                page, frag = str(p["page"]), _cell(p["snippet"])
            else:
                page, frag = "—", _STATUS_PL.get(p["status"], p["status"])
            method = f["method"]
            if method == METHOD_NULLED:
                method += f" (LLM: {_cell(f['raw'])})"
            elif method == METHOD_NORM:
                method += f" ({f['normalizer']}: {_cell(f['raw'])})"
            lines.append(f"| {f['field']} | {_cell(f['value'])} | {page} | {frag} | {method} |")
    return "\n".join(lines) + "\n"
