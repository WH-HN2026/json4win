"""Prompts: generic templates in json4win/config/prompt_*.md, filled from the class configs (D12).

Placeholders are `{{NAME}}` (plain replacement: templates contain JSON and regexes with braces).
"""

import json
from pathlib import Path
from typing import Any

from json4win.config import CONFIG_DIR, OTHER, DocClass, FieldRule


def _template(name: str, config_dir: Path | None) -> str:
    return ((config_dir or CONFIG_DIR) / f"prompt_{name}.md").read_text(encoding="utf-8")


def fill(template: str, **values: str) -> str:
    for k, v in values.items():
        template = template.replace("{{" + k + "}}", v)
    return template


def _show(v: Any) -> str:
    """A config value as shown to the model (YAML may give dates, numbers...)."""
    return json.dumps(v, ensure_ascii=False) if isinstance(v, str | int | float) else str(v)


def _class_block(c: DocClass) -> str:
    lines = [f"- `{c.id}`: {c.nazwa}.", f"  Opis: {c.opis}"]
    if c.cechy:
        lines.append("  Typowe cechy:")
        lines += [f"    - {x}" for x in c.cechy]
    if c.nie_mylic_z:
        lines.append("  Nie mylić z (to NIE jest ta klasa):")
        lines += [f"    - {x}" for x in c.nie_mylic_z]
    return "\n".join(lines)


def decision_prompt(classes: dict[str, DocClass], config_dir: Path | None = None) -> str:
    ids = ", ".join(f'"{i}"' for i in [*classes, OTHER])
    blocks = "\n\n".join(_class_block(c) for c in classes.values())
    return fill(_template("decyzja", config_dir), KLASY=blocks, IDENTYFIKATORY=ids)


def completeness_prompt(question: str, config_dir: Path | None = None) -> str:
    return fill(_template("kompletnosc", config_dir), WARUNEK=question.strip())


def _field_block(f: FieldRule) -> str:
    lines = [f"- `{f.path}` (typ: {f.typ}): {f.opis}"]
    if f.format:
        lines.append(
            f"  Format (wyrażenie regularne, wartość musi pasować w całości): `{f.format}`"
        )
    if f.wartosci:
        lines.append("  Dozwolone wartości:")
        lines += [f"    - {_show(k)}: {v}" for k, v in f.wartosci.items()]
    if f.przyklady:
        lines.append("  Przykłady: " + ", ".join(_show(x) for x in f.przyklady))
    if f.poprawki_ocr:
        lines.append(f"  Poprawki OCR: {f.poprawki_ocr}")
    return "\n".join(lines)


def extraction_prompt(c: DocClass, config_dir: Path | None = None) -> str:
    instr = f"\nInstrukcje dla tego rodzaju dokumentu:\n{c.instrukcje}\n" if c.instrukcje else ""
    return fill(
        _template("ekstrakcja", config_dir),
        NAZWA=c.nazwa,
        OPIS=c.opis,
        SZABLON=json.dumps(c.szablon, ensure_ascii=False, indent=2),
        POLA="\n".join(_field_block(f) for f in c.pola.values()),
        INSTRUKCJE=instr,
    )


def correction_prompt(errors: list[str], config_dir: Path | None = None) -> str:
    return fill(_template("poprawka", config_dir), BLEDY="\n".join(f"- {e}" for e in errors))


def document_text(pages: list[str]) -> str:
    """OCR pages joined with page markers, as sent to the models."""
    return "\n\n".join(f"=== strona {i} ===\n{p.strip()}" for i, p in enumerate(pages, 1))
