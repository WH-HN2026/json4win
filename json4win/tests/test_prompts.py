import re

from json4win import config, prompts


def test_templates_have_no_unfilled_placeholders(config_dir, faktura) -> None:
    rendered = [
        prompts.decision_prompt({"faktura": faktura}, config_dir),
        prompts.completeness_prompt("Czy jest suma?", config_dir),
        prompts.extraction_prompt(faktura, config_dir),
        prompts.correction_prompt(["`a`: zły"], config_dir),
    ]
    for text in rendered:
        assert not re.search(r"\{\{\w+\}\}", text), text
        assert "JSON" in text


def test_decision_prompt_lists_every_class(config_dir, faktura) -> None:
    text = prompts.decision_prompt({"faktura": faktura}, config_dir)
    assert "- `faktura`: Faktura VAT." in text
    assert "Faktura sprzedaży z numerem" in text
    assert "nagłówek 'Faktura VAT nr'" in text
    assert "paragon, nota księgowa" in text
    assert "`inne`" in text and '"faktura", "inne"' in text


def test_extraction_prompt_renders_class(config_dir, faktura) -> None:
    text = prompts.extraction_prompt(faktura, config_dir)
    # the template, as JSON, with the list item shape
    assert '"Nabywcy": [\n    {\n      "nazwa": null,' in text
    for path in faktura.pola:
        assert f"- `{path}` (typ: " in text
    assert "`^FV/\\d+/\\d{4}$`" in text  # format, braces kept
    assert '"FV/12/2031"' in text  # przyklady
    assert "W cyfrach O→0." in text  # poprawki_ocr
    assert '- "firma": spółka, przedsiębiorca' in text and "- 1: jedna pozycja" in text
    assert "Nabywców wypisz w kolejności z dokumentu." in text  # instrukcje
    assert "null" in text and "dokładnie" in text  # general rules


def test_extraction_prompt_with_yaml_typed_examples(config_dir, faktura) -> None:
    # An unquoted date in YAML becomes datetime.date: shown as text, not a crash.
    import dataclasses
    import datetime

    rule = dataclasses.replace(faktura.pola["Faktura.data"], przyklady=[datetime.date(2031, 4, 17)])
    c = dataclasses.replace(faktura, pola=faktura.pola | {"Faktura.data": rule})
    assert "Przykłady: 2031-04-17" in prompts.extraction_prompt(c, config_dir)


def test_document_text_page_markers() -> None:
    assert prompts.document_text([" a \n", "b"]) == "=== strona 1 ===\na\n\n=== strona 2 ===\nb"


def test_real_prompts_exist() -> None:
    for name in ("decyzja", "kompletnosc", "ekstrakcja", "poprawka"):
        assert (config.CONFIG_DIR / f"prompt_{name}.md").is_file()
