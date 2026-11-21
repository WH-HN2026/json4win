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

---

## Model comparison (ideal OCR, partial)

Dev-only ideal-OCR comparison of GA open-weight Mistral API models against the `zai-glm-5-3-flash` baseline
(task M1, partial: all 4 homogeneous runs complete; mixed decision+extraction runs paused on coordinator/user
request — see [`docs/models.md`](models.md) for primary-source metadata, per-field misses, and next steps).

- **Date:** 2026-11-21
- **Mode:** `make eval IDEAL=1 NEG=1 V=1 JOBS=4` (`LLM_BASE_URL=https://api.mistral.ai/v1`)
- **Dataset:** `dane/przyklad_01..39` (39 cases, 1,172 assertions: 1,135 valued + 37 null) + 16 negative PDFs

| Decision + Extract model | Params (total / active) | `odwolanie` F1 | `pelnomocnictwo` F1 | `przelew` F1 | **Total F1** | TP / FP / FN | null ok / zle | Negatives FP | Wall time | Failures |
|---|---|---:|---:|---:|---:|---|---:|---:|---:|---|
| `ministral-3b-latest` (`ministral-3b-2512`) | 3.85B / 3.85B | 0.973 | 0.995 | 0.944 | **0.973** | 1085 / 11 / 50 | 30 / 7 | 0 / 16 | 99.4s | 1 `finish_reason='length'` (`przyklad_22/odwolanie.pdf`) |
| `ministral-8b-latest` (`ministral-8b-2512`) | 8.92B / 8.92B | 0.988 | 0.969 | 0.969 | **0.980** | 1110 / 21 / 25 | 22 / 15 | 0 / 16 | 130.5s | 0 |
| `ministral-14b-latest` (`ministral-14b-2512`) | 13.95B / 13.95B | 0.998 | 0.980 | 0.985 | **0.991** | 1120 / 5 / 15 | 37 / 0 | 0 / 16 | 189.3s | 0 |
| `mistral-small-latest` (`mistral-small-2603`) | 119B / 6.5B | 0.994 | 1.000 | 0.996 | **0.996** | 1131 / 6 / 4 | 33 / 4 | 0 / 16 | 70.9s | 0 |
| `zai-glm-5-3-flash` *(ref. baseline above)* | 320B / 18B | 0.999 | 1.000 | 0.987 | **0.997** | 1128 / 0 / 7 | 37 / 0 | 0 / 16 | *n/a* | 1 `finish_reason='length'` (`przyklad_31/potwierdzenie_przelewu.pdf`) |

## Real scans, local OCR (2026-11-21)

`make eval-skany V=1` on all 30 scans in `dane/skany/`: local Unlimited-OCR-2 on CPU (Ryzen 9 7900X, 12 threads),
zai-glm-5-3-flash with `LLM_REASONING_EFFORT=low`, global Mistral endpoint.

| kind | TP | FP | FN | null ok / wrong | F1 |
|---|---|---|---|---|---|
| odwolania (10) | 138 | 0 | 0 | 36 / 0 | 1.000 |
| pelnomocnictwa (10) | 74 | 1 | 0 | 1 / 1 | 0.993 |
| potwierdzenia (10) | 54 | 0 | 0 | 6 / 0 | 1.000 |
| **total (30)** | **266** | **1** | **0** | 43 / 1 | **0.998** |

- The only miss: `pelnomocnictwa_0010` `mocodawca[0].data.nazwa`. The ground truth is null for a sole trader
  (osoba_fizyczna); we output the business name. The training JSONs disagree here: 4 of 5 sole traders in `przyklad_*`
  have the business name filled in (noted in E2).
- Pages OCR'd per odwolanie: 1 page ×4, 2 pages ×5, 3 pages ×1. OCR time per page: min 24.6 s, median 55.9 s, max
  102 s. Wall time 30:54 for 30 documents (a few pages were already cached). Peak RSS 11.1 GB.
- LLM time per document: 1.5–10.3 s.
