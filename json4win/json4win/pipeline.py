"""Per-document pipeline: text -> document class -> extracted fields -> canonical JSON.

Stub: every document is treated as unclassified, which is the correct output for negatives.
Text extraction, classification and extraction land in roadmap tasks P*, C*, E*.
"""

from pathlib import Path


def process_document(pdf: Path) -> dict:
    """Return the canonical JSON object for one PDF, or {} if it matches no document class."""
    return {}
