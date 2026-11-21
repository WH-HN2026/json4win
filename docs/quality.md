# Quality measurements (`json4win`)

Append new evaluation runs as new sections below; do not overwrite earlier baselines.

---

## Ideal-OCR baseline

Dev-only upper bound using PDF text-layer extraction (`pdftotext -layout`) monkeypatched over
`json4win.ocr` inside `scripts/eval_training.py --ideal-ocr` (the app itself never uses the PDF
text layer). Serves as the pre-OCR baseline for tuning tasks T1–T4.

- **Date:** 2026-11-21
- **Mode:** `IDEAL OCR (text layer, dev-only upper bound)` (`scripts/eval_training.py --ideal-ocr --negatives -v --jobs 4`)
- **Models:** decision `zai-glm-5-3-flash`, extract `zai-glm-5-3-flash` (`LLM_BASE_URL=https://api.mistral.ai/v1`)
- **Dataset:** `dane/przyklad_01..39` (39 cases, 1,172 assertions: 1,135 valued + 37 null) + 16 negative PDFs
- **Traces:** when invoked with `--keep`, per-document extraction traces (`*.trace.json`, `*.trace.md`) are written to `<tmp>/traces/`

### Totals and per-class F1

| Class | TP | FP | FN | null ok | null zle | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `odwolanie` | 625 | 0 | 1 | 37 | 0 | 1.000 | 0.998 | **0.999** |
| `pelnomocnictwo` | 275 | 0 | 0 | 0 | 0 | 1.000 | 1.000 | **1.000** |
| `przelew` | 228 | 0 | 6 | 0 | 0 | 1.000 | 0.974 | **0.987** |
| **TOTAL** | **1128** | **0** | **7** | **37** | **0** | **1.000** | **0.994** | **0.997** |

### Wrong fields (grouped by class and field)

Only 7 assertions failed across all 39 cases (0 false positives, 7 false negatives):

| Class | Field | Misses | Cases | Expected → Got | Notes |
|---|---|---:|---|---|---|
| `odwolanie` | `Zamawiajacy[0].data.krs` | 1 | `przyklad_32` | `'9996418450'` → `None` | KRS is printed on page 1 (`KRS: 9996418450, NIP: ...`); single LLM omission |
| `przelew` | `przelew_bankowy[0].data.data_operacji` | 1 | `przyklad_31` | `'2026-03-28'` → `None` | Whole doc returned `{}` due to `LlmError` (`finish_reason='length'`) |
| `przelew` | `przelew_bankowy[0].data.kwota` | 1 | `przyklad_31` | `34.0` → `None` | Same `przyklad_31` `finish_reason='length'` failure |
| `przelew` | `przelew_bankowy[0].data.z_rachunku` | 1 | `przyklad_31` | `'93865881321456168889527298'` → `None` | Same `przyklad_31` `finish_reason='length'` failure |
| `przelew` | `przelew_bankowy[0].data.na_rachunek` | 1 | `przyklad_31` | `'33112511501590528916014892'` → `None` | Same `przyklad_31` `finish_reason='length'` failure |
| `przelew` | `przelew_bankowy[0].data.tytul` | 1 | `przyklad_31` | `'opłata skarbowa od pełnomocnictwa dla Halina Ostrowczyk i Grzegorz Dudek w postępowaniu przed KIO w przetargu ZS.568.2026 CEN2604095639258'` → `None` | Same `przyklad_31` `finish_reason='length'` failure |
| `przelew` | `przelew_bankowy[0].data.numer_transakcji` | 1 | `przyklad_31` | `'CEN2604095639258'` → `None` | Same `przyklad_31` `finish_reason='length'` failure |

> [!NOTE]
> 6 of the 7 misses come from a single document (`przyklad_31/potwierdzenie_przelewu.pdf`) where
> `zai-glm-5-3-flash` exhausted `LLM_MAX_TOKENS=16000` in reasoning tokens (`finish_reason='length'`),
> causing `cli.py` to degrade that file to `{}`. All 38 other transfers scored 100%, and all 39
> powers of attorney scored 100%.

### Negatives check (`--negatives`)

- **Result:** `16/16 empty {}, 0 false positive(s)`
- **Scope:** 12 PDFs in `dane/negatywne/` + 4 extra PDFs in `dane/przyklad_*/`
  (`przyklad_04/2025_S 112-383751.pdf`, `przyklad_10/2025-OJS107-00364525-pl-ts.pdf`,
  `przyklad_24/prowadzenie_postepowania_odwolawczego.pdf`, `przyklad_37/2025_BZP 00143067_01.pdf`)
- **False positives:** none.
- **Caveat (scanned negatives):** 3 of the 12 files in `dane/negatywne/` have no embedded text layer
  (0 characters returned by `pdftotext` on page 1):
  - `dane/negatywne/1648041143_1647951357decyzja-ministrasportu-pzn.pdf`
  - `dane/negatywne/Decyzja-Ministra-Sportu-i-Turystyki1.pdf`
  - `dane/negatywne/Minister-Sprawiedliwosci-pismo-RDSSP-z-11.03.2024-r..pdf`
  Under `--ideal-ocr` they trivially classify as `inne`; they must be re-tested on real cached OCR in task T4.
