#!/usr/bin/env python3
"""Fill the shared OCR cache for the training data (dev tool, task P1; `make ocr-cache`).

Usage: scripts/ocr_cache.py [--pages 4] [--paths A.pdf B.pdf ...]

PDFs: every PDF under dane/przyklad_*/ (incl. the extra ones), dane/negatywne/ and dane/skany/**.
Pages 1..N of each, BREADTH-FIRST (page 1 of every PDF, then page 2, ...), so a partial run is
already useful. Resumable: cached pages are skipped. Runs the model in this one process; never start
two of these (the model takes ~8 GB of RAM). Ctrl+C is safe: every page is written atomically.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "json4win"))

from json4win import env, ocr  # noqa: E402


def training_pdfs() -> list[Path]:
    dane = ROOT / "dane"
    pdfs = [
        *dane.glob("przyklad_*/*.pdf"),
        *dane.glob("negatywne/*.pdf"),
        *dane.glob("skany/**/*.pdf"),
    ]
    return sorted(set(pdfs))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pages", type=int, default=4, help="pages per PDF (default 4)")
    ap.add_argument("--paths", nargs="+", type=Path, help="only these PDFs (default: all of dane/)")
    a = ap.parse_args()
    env.load_env()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    pdfs = [p.resolve() for p in a.paths] if a.paths else training_pdfs()
    counts = {p: min(a.pages, ocr.page_count(p)) for p in pdfs}
    todo = [
        (p, i)
        for i in range(a.pages)  # breadth-first
        for p in pdfs
        if i < counts[p] and not ocr.is_cached(p, i)
    ]
    total = sum(counts.values())
    print(f"{len(pdfs)} PDFs, {total} pages, {total - len(todo)} cached, {len(todo)} to OCR")
    print(f"cache: {env.cache_dir() / 'ocr' / ocr.settings_id(ocr.infer_settings())}")

    t_start, done = time.time(), 0
    for p, i in todo:
        t0 = time.time()
        try:
            e = ocr.ocr_page_entry(p, i)
        except ocr.OcrCacheMiss as err:
            print(f"error: {err}", file=sys.stderr)
            return 1
        except Exception as err:  # one bad PDF must not stop the run
            print(f"FAILED {p.relative_to(ROOT) if p.is_relative_to(ROOT) else p} p{i + 1}: {err}")
            continue
        done += 1
        rate = (time.time() - t_start) / done
        name = p.relative_to(ROOT) if p.is_relative_to(ROOT) else p
        print(
            f"[{done}/{len(todo)}] {name} p{i + 1}: {time.time() - t0:.1f}s "
            f"({e['tokens']} tok, {e['finish']}), avg {rate:.1f} s/page, "
            f"ETA {rate * (len(todo) - done) / 60:.0f} min",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
