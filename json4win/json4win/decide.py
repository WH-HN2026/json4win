"""Decision model and the read-until-complete loop (architecture §3, steps 1-4)."""

import logging
import re
from pathlib import Path

from json4win import llm, ocr, prompts, trace
from json4win.config import OTHER, DocClass

log = logging.getLogger(__name__)


def _ask(system: str, text: str) -> dict:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Tekst dokumentu (OCR):\n\n{text}"},
    ]
    trace.count("decision_llm_calls")
    return llm.chat_json(llm.model("decision"), messages)


def classify(text: str, classes: dict[str, DocClass]) -> str | None:
    """The class id of a document from its first page text; None for "inne" or an unknown id."""
    if not classes:
        return None
    answer = _ask(prompts.decision_prompt(classes), text).get("klasa")
    if isinstance(answer, str):
        answer = answer.strip().strip("`\"'")
    cid = answer if answer in classes else None
    if cid is None and answer != OTHER:
        log.warning("decision model answered unknown class %r -> %s", answer, OTHER)
    trace.put("decision", {"model": llm.model("decision"), "answer": answer, "class": cid or OTHER})
    return cid


def is_complete(text: str, question: str) -> bool:
    """The decision model's answer to the class's `kompletny_gdy` question for the text so far."""
    answer = _ask(prompts.completeness_prompt(question), text).get("kompletny")
    if isinstance(answer, str):
        return answer.strip().lower() in ("true", "tak", "yes")
    return answer is True


def read_pages(pdf: Path, c: DocClass, first_page: str) -> list[str]:
    """OCR pages of `pdf` after the first, as far as the class's `czytanie` asks.

    Stop once `znacznik` has matched the text read so far plus `stron_po_znaczniku` more pages;
    otherwise ask `kompletny_gdy` (if set) after each page; never beyond `max_stron` or the PDF.
    """
    r = c.czytanie
    info = {"max_pages": r.max_stron, "marker": r.znacznik, "question": r.kompletny_gdy}
    trace.put("reading", info)
    limit = min(r.max_stron, ocr.page_count(pdf))
    pages = [first_page]
    marker_at = None  # number of pages read when the marker first matched
    while len(pages) < limit:
        text = "\n".join(pages)
        if r.znacznik and marker_at is None and re.search(r.znacznik, text):
            marker_at = len(pages)
            trace.put("reading", info | {"marker_after_pages": marker_at})
        if marker_at is not None:
            if len(pages) >= marker_at + r.stron_po_znaczniku:
                break
        elif r.kompletny_gdy:
            done = is_complete(prompts.document_text(pages), r.kompletny_gdy)
            trace.add("completeness", {"pages_read": len(pages), "complete": done})
            if done:
                break
        pages.append(trace.ocr_page(pdf, len(pages)))
    return pages
