"""Extraction with validation and retries (architecture §3, steps 5-8)."""

import logging
from dataclasses import dataclass, field

from json4win import env, llm, prompts, validate
from json4win.config import DocClass

log = logging.getLogger(__name__)


@dataclass
class Extraction:
    data: dict
    retries: int = 0
    nulled: list[str] = field(default_factory=list)  # fields set to null because still invalid
    # For the trace: the template-shaped LLM values before normalisation (from the round each
    # field was taken from), the still-invalid fields after each round, the model and its calls.
    raw: dict = field(default_factory=dict)
    rounds: list[list[str]] = field(default_factory=list)
    model: str = ""
    calls: int = 0


def max_retries() -> int:
    raw = env.get("LLM_VALIDATION_RETRIES", "2")
    try:
        return max(0, int(raw))
    except ValueError as e:
        raise ValueError(f"LLM_VALIDATION_RETRIES must be an integer, got {raw!r}") from e


def extract(c: DocClass, pages: list[str]) -> Extraction:
    """Fill the class template from the OCR pages; invalid fields are retried, then nulled.

    The first LLM call failing raises; a failing retry keeps the result so far.
    """
    model = llm.model("extract")
    messages = [
        {"role": "system", "content": prompts.extraction_prompt(c)},
        {"role": "user", "content": f"Tekst dokumentu (OCR):\n\n{prompts.document_text(pages)}"},
    ]
    calls = 1
    answer = llm.chat_json(model, messages)
    out, errors = validate.check(c, answer)
    raw = validate.coerce(c.szablon, answer)
    rounds = [validate.error_lines(errors)]

    retries = 0
    while errors and retries < max_retries():
        retries += 1
        calls += 1
        log.debug("%s: retry %d, invalid: %s", c.id, retries, validate.error_lines(errors))
        messages += [
            {"role": "assistant", "content": llm.answer_text(answer)},
            {"role": "user", "content": prompts.correction_prompt(validate.error_lines(errors))},
        ]
        try:
            answer = llm.chat_json(model, messages)
        except llm.LlmError as e:
            log.warning("%s: retry %d failed: %s", c.id, retries, e)
            break
        new_out, new_errors = validate.check(c, answer)
        new_raw = validate.coerce(c.szablon, answer)
        # Take only the fields that were wrong: a retry must not disturb fields that passed.
        still = {}
        for path, reason in errors.items():
            try:
                value = validate.get_at(new_out, path)
            except (KeyError, IndexError, TypeError):
                still[path] = reason
                continue
            validate.set_at(raw, path, validate.get_at(new_raw, path))
            if path in new_errors:
                still[path] = new_errors[path]
            else:
                validate.set_at(out, path, value)
        errors = still
        rounds.append(validate.error_lines(errors))

    for path in errors:
        validate.set_at(out, path, None)
    nulled = [validate.show_path(p) for p in errors]
    return Extraction(out, retries, nulled, raw, rounds, model, calls)
