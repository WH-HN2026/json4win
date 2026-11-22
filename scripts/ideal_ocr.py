"""Dev-only "ideal OCR" helper: replaces json4win.ocr with PDF text-layer extraction.

NEVER imported by the app (json4win/json4win/*). Used only by dev evaluation scripts to measure
an upper bound on extraction quality before local OCR is tuned/cached.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "json4win"
BANNER = "IDEAL OCR (text layer, dev-only upper bound)"

_PAGES_RE = re.compile(r"^Pages:\s*(\d+)\s*$", re.MULTILINE)


class TextLayerOcr:
    """Thread-safe, per-run cached PDF text-layer extractor using pdfinfo + pdftotext."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[Path, int] = {}
        self._pages: dict[tuple[Path, int], str] = {}

    def page_count(self, pdf: Path) -> int:
        key = pdf.resolve()
        with self._lock:
            cached = self._counts.get(key)
        if cached is not None:
            return cached

        proc = subprocess.run(
            ["pdfinfo", str(key)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            raise RuntimeError(f"pdfinfo failed for {pdf}: {proc.stderr.strip()}")
        match = _PAGES_RE.search(proc.stdout)
        if not match:
            raise RuntimeError(f"pdfinfo returned no page count for {pdf}")
        count = int(match.group(1))
        with self._lock:
            self._counts[key] = count
        return count

    def ocr_page(self, pdf: Path, index: int) -> str:
        if index < 0:
            raise ValueError(f"page index must be >= 0, got {index}")
        key = (pdf.resolve(), index)
        with self._lock:
            cached = self._pages.get(key)
        if cached is not None:
            return cached

        page_num = str(index + 1)
        proc = subprocess.run(
            ["pdftotext", "-layout", "-f", page_num, "-l", page_num, str(key[0]), "-"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            raise RuntimeError(f"pdftotext failed for {pdf} page {page_num}: {proc.stderr.strip()}")
        text = proc.stdout
        with self._lock:
            self._pages[key] = text
        return text


def _ensure_app_on_path() -> None:
    app_str = str(APP)
    if app_str not in sys.path:
        sys.path.insert(0, app_str)


@contextmanager
def patch_ocr(backend: TextLayerOcr | None = None) -> Iterator[TextLayerOcr]:
    """Load json4win env and monkeypatch json4win.ocr with text-layer extraction."""
    _ensure_app_on_path()
    import json4win.env as app_env
    import json4win.ocr as app_ocr

    app_env.load_env()
    impl = backend or TextLayerOcr()
    orig_page_count = app_ocr.page_count
    orig_ocr_page = app_ocr.ocr_page
    app_ocr.page_count = impl.page_count
    app_ocr.ocr_page = impl.ocr_page
    try:
        yield impl
    finally:
        app_ocr.page_count = orig_page_count
        app_ocr.ocr_page = orig_ocr_page


def run_app_ideal_ocr(
    inp: Path,
    out: Path,
    *,
    jobs: int = 4,
    trace_dir: Path | None = None,
) -> int:
    """Run json4win.cli.run in-process with monkeypatched text-layer OCR.

    Parallelises per-PDF work across a thread pool of size `jobs` while preserving deterministic
    output files and logging progress to stderr.
    """
    if jobs < 1:
        raise ValueError(f"jobs must be >= 1, got {jobs}")

    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    with patch_ocr():
        import json4win.cli as app_cli
        import json4win.pipeline as app_pipeline

        # Warm the cached class configs on the main thread before spawning workers.
        app_pipeline.classes()

        pdfs = app_cli.find_pdfs(inp)
        if jobs == 1 or len(pdfs) <= 1:
            failed = app_cli.run(inp, out, trace_dir=trace_dir)
        else:
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                futures = [
                    pool.submit(app_cli.run, inp, out, pdfs=[pdf], trace_dir=trace_dir)
                    for pdf in pdfs
                ]
                failed = sum(fut.result() for fut in futures)

    if failed:
        print(
            f"json4win ideal-ocr: {failed} document(s) failed",
            file=sys.stderr,
        )
        return 1
    return 0
