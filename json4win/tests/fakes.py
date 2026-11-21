"""Fakes for the contracts owned by other tasks (OCR: P1, normalisers: E4) and for the LLM."""

import re
from typing import Any

from json4win import llm


def fake_normalize(value: Any, kind: str, params: dict | None = None) -> Any:
    """A tiny stand-in for json4win.normalize.normalize (task E4)."""
    s = str(value)
    if kind == "digits":
        return re.sub(r"\D", "", s) or None
    if kind == "amount":
        try:
            return float(s.replace(" ", "").replace("zł", "").replace(",", "."))
        except ValueError:
            return None
    if kind == "date":
        m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", s)
        return (
            f"{m[3]}-{m[2]}-{m[1]}" if m else (s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None)
        )
    return value


class FakeLlm:
    """Returns scripted answers in order and records the messages it got."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, list[dict]]] = []
        self.kwargs: list[dict] = []

    def __call__(self, model: str, messages: list[dict], **kwargs: Any) -> dict:
        self.calls.append((model, [dict(m) for m in messages]))
        self.kwargs.append(kwargs)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def fail() -> llm.LlmError:
    return llm.LlmError("fake failure")
