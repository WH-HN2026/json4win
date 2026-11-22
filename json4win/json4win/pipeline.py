"""Per-document pipeline (architecture §3): OCR page 1 -> decision -> read more pages -> extract.

Generic: everything class-specific comes from the class files in json4win/config/. Any failure
raises; cli.py turns it into {} for that document and goes on with the batch.
"""

import logging
from functools import cache
from pathlib import Path

from json4win import config, decide, extract, trace

log = logging.getLogger(__name__)


@cache
def classes() -> dict[str, config.DocClass]:
    return config.load_classes()


def process_document(pdf: Path) -> dict:
    """Return the canonical JSON object for one PDF, or {} if it matches no document class."""
    known = classes()
    with trace.step("ocr"):
        first = trace.ocr_page(pdf, 0)
    with trace.step("decyzja"):
        cid = decide.classify(first, known)
    trace.put("class", cid or config.OTHER)
    if cid is None:
        log.info("%s: class=inne pages=1", pdf.name)
        trace.put("result", {})
        return {}
    c = known[cid]
    with trace.step("czytanie"):
        pages = decide.read_pages(pdf, c, first)
    with trace.step("ekstrakcja"):
        result = extract.extract(c, pages)
    with trace.step("pochodzenie"):
        trace.extraction(c, result, pages)
    log.info(
        "%s: class=%s pages=%d retries=%d nulled=%s",
        pdf.name,
        cid,
        len(pages),
        result.retries,
        ",".join(result.nulled) or "-",
    )
    return result.data
