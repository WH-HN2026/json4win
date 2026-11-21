"""Page OCR with the local Unlimited-OCR-2 model on CPU (architecture D10).

CONTRACT STUB: the signatures are fixed; task P1 implements the bodies. The pipeline never uses
the PDF text layer: every page it reads comes from here. Results are cached in
json4win.env.cache_dir(); with OCR_CACHE_ONLY=1 a cache miss raises OcrCacheMiss instead of
running the model.
"""

from pathlib import Path


class OcrCacheMiss(RuntimeError):
    """OCR_CACHE_ONLY=1 and the page is not in the cache."""


def page_count(pdf: Path) -> int:
    """Number of pages in the PDF."""
    raise NotImplementedError("task P1")


def ocr_page(pdf: Path, index: int) -> str:
    """Plain text of page `index` (0-based) of `pdf`, read by OCR (cached), diacritics kept."""
    raise NotImplementedError("task P1")
