# Document classes

One YAML file per document class (`odwolanie.yaml`, `pelnomocnictwo.yaml`, `przelew.yaml`, ...). A file
describes how the class is recognised, how far to read it and which fields it produces, so a new class or field
is added here **without touching code** (architecture D6). Files in this directory that are not class files
(this README, prompt templates such as `prompt_*.md`) are ignored by the class loader.

Text meant for the models (descriptions, hints, instructions) is written in **Polish**, like the documents.
Examples are short and **invented**: the right format, never values copied from `dane/` (D9).

## Format

```yaml
id: przelew                 # REQUIRED. Class id = file name without .yaml. The decision model answers with it.
nazwa: Potwierdzenie przelewu bankowego          # REQUIRED. Human-readable name.

opis: >-                    # REQUIRED. What the document is (1–4 sentences), for the decision model.
  Potwierdzenie wykonania przelewu z banku: ...
cechy:                      # optional. Typical content and layout: hints for the decision model, not rules.
  - "nagłówek 'Potwierdzenie wykonania przelewu' / 'Potwierdzenie transakcji'"
nie_mylic_z:                # optional. Similar documents that are NOT this class.
  - "faktura, nota księgowa"

czytanie:                   # REQUIRED. How many pages to OCR (OCR is the slow part).
  max_stron: 2              # REQUIRED, >= 1. Never OCR more pages than this.
  znacznik: '(?i)zarzuca'   # optional regex (Python `re.search`) on the OCR text read so far. Once it matches,
  stron_po_znaczniku: 1     #   read this many more pages (default 0) and stop.
  kompletny_gdy: >-         # optional. Used when `znacznik` is absent or did not match: the decision model is
    Tekst zawiera ...       #   asked whether the text read so far already contains this. Yes → stop.
                            # With neither key, pages are read up to max_stron.

szablon:                    # REQUIRED. The exact output shape (D5): key names and order, object vs. list.
  przelew_bankowy:          #   Leaves are null. A list holds exactly ONE item: the shape of every element
    data_operacji: null     #   (the output list may have 1..n elements). Objects are never null in output.
    kwota: null
    tytul: null

pola:                       # REQUIRED. One entry per leaf of `szablon`, keyed by its path; `[]` marks list items:
  przelew_bankowy.kwota:    #   "Odwolujacy[].pelnomocnik.mail", "mocodawca[].podpisujacy[].imie_nazwisko".
    opis: >-                # REQUIRED. What the value is, where it usually is in the document, when it is null.
      Kwota przelewu w złotych.
    typ: float              # optional: str (default) | int | float. JSON type of a non-null value.
    normalizacja: amount    # optional normaliser kind: text | digits | date | amount | int | regex_sub
    parametry:              # optional params of the normaliser (regex_sub: pattern, repl)
      pattern: '(\d{4})/S\s*\d{1,3}-(\d{6})'
      repl: '\2-\1'
    format: '^\d+(\.\d+)?$' # optional HARD rule: `re.fullmatch` on str(value) after normalisation. A violation
                            #   is sent back to the LLM (at most 2 retries); still invalid → null. The LLM is
                            #   told the format and may fix OCR typos to fit it. Leave it out for free-form
                            #   values whose real-world format varies (soft hints go in `opis`/`przyklady`).
    wartosci:               # optional closed set: allowed value → meaning. Shown to the LLM and validated.
      osoba_prawna: "spółka, fundacja, stowarzyszenie, jednostka samorządu"
      osoba_fizyczna: "człowiek, także przedsiębiorca jednoosobowy"
    przyklady: ["2031-04-17"]   # optional invented examples of the right format.
    poprawki_ocr: >-        # optional: OCR confusions the LLM may fix in this field.
      W cyfrach O→0, l/I→1.

instrukcje: >-              # optional. Class-level instructions appended to the extraction prompt
  ...                       #   (e.g. which section wins when values repeat, how to split multiple parties).
```

Rules the loader enforces (task C1): required keys present; `id` equals the file name; every leaf of `szablon`
has exactly one entry in `pola` and every `pola` key is a leaf of `szablon`; `typ`, `normalizacja` are known
values; every regex compiles; keys of `wartosci` match `typ` (e.g. ints for `typ: int`).

## Files

| File | Owner task | What |
|---|---|---|
| `przelew.yaml` | E1 | bank-transfer confirmation → `przelew_bankowy` |
| `pelnomocnictwo.yaml` | E2 | power of attorney → `mocodawca[]`, `pelnomocnicy[]` |
| `odwolanie.yaml` | E3 | appeal to KIO → `OdwolanieKIO`, `Odwolujacy[]`, `Zamawiajacy[]`, `ZamowieniePubliczne` |
| `prompt_*.md` | C1 | generic decision and extraction prompt templates, filled in from the class files |
