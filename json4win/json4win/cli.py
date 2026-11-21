"""CLI: mirror input/<case>/<name>.pdf to output/<case>/<name>.json."""

import argparse
import json
import logging
from pathlib import Path

from json4win.pipeline import process_document

APP_ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("json4win")


def find_pdfs(input_dir: Path) -> list[Path]:
    return sorted(p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")


def run(input_dir: Path, output_dir: Path) -> int:
    """Process every PDF under input_dir. Returns the number of files that failed."""
    pdfs = find_pdfs(input_dir)
    if not pdfs:
        log.warning("no PDFs found in %s", input_dir.resolve())
    failed = 0
    for pdf in pdfs:
        out = output_dir / pdf.relative_to(input_dir).with_suffix(".json")
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = process_document(pdf)
        except Exception:
            # One bad document must not stop the batch; it gets an empty (unclassified) JSON.
            log.exception("failed: %s", pdf)
            result, failed = {}, failed + 1
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log.info("%s -> %s", pdf.relative_to(input_dir), out.relative_to(output_dir))
    return failed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="json4win", description=__doc__)
    ap.add_argument("--input", type=Path, default=APP_ROOT / "input")
    ap.add_argument("--output", type=Path, default=APP_ROOT / "output")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(message)s")
    return 1 if run(a.input, a.output) else 0
