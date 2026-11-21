"""Field normalisers named in class configs (`normalizacja:` + `parametry:`), architecture §3.

CONTRACT STUB: the signature and the kinds are fixed; task E4 implements the body.

Kinds:
- text: collapse whitespace, strip; "" -> None
- digits: keep digits only (NIP, REGON, KRS with leading zeros, accounts); no digits -> None.
  No checksum validation (training data is synthetic).
- date: -> "YYYY-MM-DD" from common Polish forms
  ("13.10.2025 r.", "13 października 2025", "2025-10-13", ...)
- amount: -> float ("1 234,56 zł", "1.234,56 PLN", "50,00")
- int: -> int
- regex_sub: re.sub(params["pattern"], params["repl"], value); unchanged if no match
"""

from typing import Any


def normalize(value: Any, kind: str, params: dict | None = None) -> Any:
    """Normalised `value`, or None if it can't be read as `kind`; unknown kind -> ValueError."""
    raise NotImplementedError("task E4")
