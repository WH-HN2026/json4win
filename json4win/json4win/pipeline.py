"""Per-document pipeline (architecture §3): OCR page 1 -> decision -> read more pages -> extract.

Generic: everything class-specific comes from the class files in json4win/config/. Any failure
raises; cli.py turns it into {} for that document and goes on with the batch.
"""

import logging
from functools import cache
from pathlib import Path

from json4win import config, decide, extract, ocr

log = logging.getLogger(__name__)


@cache
def classes() -> dict[str, config.DocClass]:
    return config.load_classes()


def process_document(pdf: Path) -> dict:
    """Return the canonical JSON object for one PDF, or {} if it matches no document class."""
    known = classes()
    first = ocr.ocr_page(pdf, 0)
    cid = decide.classify(first, known)
    if cid is None:
        log.info("%s: class=inne pages=1", pdf.name)
        return {}
    c = known[cid]
    pages = decide.read_pages(pdf, c, first)
    result = extract.extract(c, pages)
    log.info(
        "%s: class=%s pages=%d retries=%d nulled=%s",
        pdf.name,
        cid,
        len(pages),
        result.retries,
        ",".join(result.nulled) or "-",
    )
    return result.data
