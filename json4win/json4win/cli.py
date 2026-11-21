"""CLI: mirror input/<case>/<name>.pdf to output/<case>/<name>.json."""

import argparse
import json
import logging
from collections.abc import Callable
from pathlib import Path

from json4win import env, trace
from json4win.pipeline import process_document

APP_ROOT = env.APP_ROOT
log = logging.getLogger("json4win")

ProgressCallback = Callable[[Path, str, Exception | None], None]


def find_pdfs(input_dir: Path) -> list[Path]:
    return sorted(p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")


def output_path_for(pdf: Path, input_dir: Path, output_dir: Path) -> Path:
    """Return the mirrored output JSON path for a PDF under input_dir."""
    return output_dir / pdf.relative_to(input_dir).with_suffix(".json")


def process_one(
    pdf: Path, input_dir: Path, output_dir: Path, trace_dir: Path | None = None
) -> tuple[Path, dict, Exception | None]:
    """Process one PDF and write its mirrored JSON. Returns (out_path, result, error).

    trace_dir: write <case>/<name>.trace.json and .trace.md there (json4win.trace); None = off.
    """
    out = output_path_for(pdf, input_dir, output_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    rel = pdf.relative_to(input_dir)
    tpath = trace.trace_path(trace_dir, rel) if trace_dir else None
    error: Exception | None = None
    try:
        with trace.document(pdf, tpath, rel.as_posix()):
            result = process_document(pdf)
    except Exception as exc:
        # One bad document must not stop the batch; it gets an empty (unclassified) JSON.
        log.exception("failed: %s", pdf)
        result = {}
        error = exc
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log.info("%s -> %s", pdf.relative_to(input_dir), out.relative_to(output_dir))
    return out, result, error


def run(
    input_dir: Path,
    output_dir: Path,
    pdfs: list[Path] | None = None,
    on_progress: ProgressCallback | None = None,
    trace_dir: Path | None = None,
) -> int:
    """Process PDFs under input_dir (all of them when pdfs is None). Returns failed count."""
    targets = find_pdfs(input_dir) if pdfs is None else list(pdfs)
    if not targets:
        log.warning("no PDFs found in %s", input_dir.resolve())
    failed = 0
    for pdf in targets:
        if on_progress is not None:
            on_progress(pdf, "ocr", None)
        _, _, error = process_one(pdf, input_dir, output_dir, trace_dir)
        if error is not None:
            failed += 1
            if on_progress is not None:
                on_progress(pdf, "error", error)
        elif on_progress is not None:
            on_progress(pdf, "done", None)
    return failed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="json4win", description=__doc__)
    ap.add_argument("--input", type=Path, default=APP_ROOT / "input")
    ap.add_argument("--output", type=Path, default=APP_ROOT / "output")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--gui", action="store_true", help="Uruchom lokalny interfejs webowy (GUI)")
    ap.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port dla GUI na 127.0.0.1 (domyślnie 0 = losowy wolny port)",
    )
    ap.add_argument(
        "--no-browser",
        action="store_true",
        help="Nie otwieraj przeglądarki automatycznie przy uruchamianiu GUI",
    )
    ap.add_argument(
        "--trace",
        type=Path,
        metavar="DIR",
        help="extraction traces dir (default: JSON4WIN_TRACE_DIR or json4win/traces)",
    )
    ap.add_argument("--no-trace", action="store_true", help="write no extraction traces")
    a = ap.parse_args(argv)
    env.load_env()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(message)s")
    trace_dir = None if a.no_trace else (a.trace or trace.default_dir())
    if trace_dir and trace_dir.resolve().is_relative_to(a.output.resolve()):
        ap.error(f"the trace dir must be outside the output dir: {trace_dir}")
    if a.gui:
        from json4win.gui import serve

        return serve(
            a.input,
            a.output,
            port=a.port,
            open_browser=not a.no_browser,
            trace_dir=trace_dir,
        )
    return 1 if run(a.input, a.output, trace_dir=trace_dir) else 0
