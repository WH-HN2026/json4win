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

## Real scans: GLM reasoning effort (2026-11-21)

Same 30 scans, OCR from the local-OCR cache (`OCR_CACHE_ONLY=1`), zai-glm-5-3-flash, only `LLM_REASONING_EFFORT`
changed. LLM time and tokens summed over the 30 documents (decision + extraction calls), tokens from the traces.

| effort | TP / FP / FN | F1 | LLM s/doc (median / max) | run wall time | prompt / completion tokens |
|---|---|---|---|---|---|
| `low` (default) | 266 / 1 / 0 | 0.998 | 2.8 / 4.2 | 82 s | 240,763 / 8,211 |
| `high` | 266 / 1 / 0 | 0.998 | 3.3 / 9.8 | 105 s | 244,664 / 14,962 |
| `off` (model default) | 266 / 1 / 0 | 0.998 | 5.0 / 17.0 | 178 s | 240,763 / 43,393 |

Identical scores (the same single disputed miss, `pelnomocnictwa_0010` `mocodawca[0].data.nazwa`); `low` is about 2×
faster than the model default and uses about 5× fewer completion tokens, so it stays the default.

---

## Real scans: Tesseract vs Unlimited-OCR-2 (2026-11-21, task P4)

`OCR_BACKEND=tesseract make eval-skany V=1` on all 30 scans in `dane/skany/` (Ryzen 9 7900X, CPU only, single
process, cold Tesseract OCR cache), same LLM setup (`zai-glm-5-3-flash`, `LLM_REASONING_EFFORT=low`, global
Mistral endpoint), compared against the `Unlimited-OCR-2` (`OCR_BACKEND=local`) run above.

### Side-by-side summary

| Backend / config | `odwolania` (10) | `pelnomocnictwa` (10) | `potwierdzenia` (10) | **Total TP/FP/FN** | **Total F1** | OCR s/page (min / med / max) | Wall time (30 docs) | Peak RSS | Retries |
|---|---:|---:|---:|---|---:|---|---|---:|---:|
| `local` Unlimited-OCR-2 (200 dpi) | 138/0/0 (**1.000**) | 74/1/0 (**0.993**) | 54/0/0 (**1.000**) | **266 / 1 / 0** *(43/1)* | **0.998** | 24.6 / **55.9** / 102 s | 30:54¹ | **11.1 GB** | 0 |
| `tesseract` 5.5.4 `tessdata_best` (300 dpi, `pol`, default PSM 3) | 138/0/0 (**1.000**) | 74/1/0 (**0.993**) | 54/0/0 (**1.000**) | **266 / 1 / 0** *(43/1)* | **0.998** | 0.55 / **1.00** / 2.27 s² | **2:10** | **0.15 GB** | 0 |
| `tesseract` 5.5.4 `tessdata_fast` (300 dpi, `pol`, default PSM 3) | 138/0/0 (**1.000**) | 74/1/0 (**0.993**) | 54/0/0 (**1.000**) | **266 / 1 / 0** *(43/1)* | **0.998**³ | 0.51 / **0.90** / 2.01 s² | **2:19** | **0.15 GB** | 2 |
| `tesseract` 5.5.4 `tessdata_best` (300 dpi, `pol`, `PSM=6`) | 138/0/0 (**1.000**) | 74/1/0 (**0.993**) | 52/2/2 (**0.963**) | **264 / 3 / 2** *(43/1)* | **0.991** | 0.51 / **0.95** / 2.11 s² | **2:25** | **0.15 GB** | 1 |

*(Parentheses in Total TP/FP/FN: `null ok / null wrong`.)*
¹ A few pages were already cached in the local run; cold 37-page run would be ~35 min.
² Pure Tesseract subprocess time (35 pages total: odwolania 1p×5, 2p×5, 3p×0). Including `pypdfium2` 300 dpi PNG
render: `tessdata_best` PSM 3 is 0.70 / 1.58 / 3.07 s/page (56.9 s OCR+render + 72.4 s LLM = 2:10 wall).
³ Same `evaluate.py` F1, but `tessdata_fast` introduced 3 silent digit/code errors masked by `SequenceMatcher >= 0.55`
(see below).

### Wrong fields (`evaluate.py -v`)

- **`tessdata_best` (default PSM 3):** 1 miss — `pelnomocnictwa_0010` `mocodawca[0].data.nazwa` (GT `None`,
  predicted `'Paweł Brzozowski Asterion Usługi Techniczne'`), identical to `Unlimited-OCR-2` (sole-trader GT
  ambiguity).
- **`tessdata_fast` (default PSM 3):** same 1 miss (`'Paweł Brzózowski Asterion Usługi Techniczne'`, with an
  extra `o→ó` diacritic error).
- **`tessdata_best` (`PSM=6`):** 3 misses — the same `pelnomocnictwa_0010` miss plus `potwierdzenia_0010`
  `z_rachunku` and `na_rachunek` swapped (2 FP, 2 FN, `potwierdzenia` F1 0.963).

### Where Tesseract loses (raw OCR quality & error analysis)

With a strong reasoning extractor (`zai-glm-5-3-flash`) and `evaluate.py`'s fuzzy string threshold
(`SequenceMatcher >= 0.55`), `tessdata_best` matches Unlimited-OCR-2 on headline F1 (**0.998**) while running
**~56× faster per page** (median 1.00 s vs 55.9 s; 14× faster end-to-end wall time) and using **~74× less RAM**
(0.15 GB vs 11.1 GB). Inspecting the raw OCR output (`scripts/ocr_probe.py quality` and exact field-level diffs
against ground truth) reveals where Tesseract is noticeably weaker and relies on the LLM to repair errors:

1. **Special symbols & e-mail `@` (`odwolania`):** Tesseract corrupted `@` in **every** appeal e-mail
   (`0/5` verbatim on `ocr_probe`, vs `6/6` for Unlimited-OCR-2) — e.g. `a.rybakGrybak-kancelaria.example`,
   `s.sikora(olszewski-kancelaria.example`, `d.kubiak()kubiak-kancelaria.example`,
   `r.malinowski(a cieslak-kancelaria.example`, `kjodlowskiDjodlowski-kancelaria.example` (where the LLM repaired
   `@` but dropped the missing dot in `k.jodlowski`). Similarly `&` in all-caps became `£`
   (`OLSZEWSKI £ PARTNERZY SP.K.` → LLM wrote `i`), and `Sp. z o.o.` routinely read as `Sp. z 0.0.`.
2. **Stamps, noise & low-contrast scans (`odwolania`, `potwierdzenia`):**
   - `odwolania_0001` `tytul`: over a noisy region Unlimited-OCR-2 read `odpadów kómunalnych z nieruchomości
     zamieszkłych` (recoverable), whereas Tesseract output `odpadów k munalnych z ypsi zamieszkałych`, causing the
     LLM to guess `od mieszkańców niezamieszkałych` (opposite meaning; only counted as TP because
     `SequenceMatcher = 0.842 >= 0.55`).
   - `potwierdzenia_0008` (low-contrast scan): Tesseract garbled labels (`Rat hunex Ziecenadawcy`,
     `©.. 17.00 PLN`), dropped dots in the date (`20 04 2026`, raw date probe `9/10` vs `10/10` for local OCR),
     and mangled the transfer title (`pełnomocnectwa dia adw Rafal Maknowski`).
   - `potwierdzenia_0009` `tytul`: `DA.ZP.242.13.2026` → `DA.ZP:242.13.2026`; `odwolania_0005` picked up a
     spurious `4` from a logo before the law firm name.
3. **Diacritics & letter confusions:** `odwolania_0003` `Żaneta` → `Zaneta` (`Ż→Z`), `odwolania_0004`
   `Brzozowcu` → `Brzozewcu` (`o→e`); `tessdata_fast` also hallucinated `Brzózowski`. Overall `ocr_probe`
   loose-name recall was **91.2%** (62/68) for `tessdata_best` vs **100.0%** (73/73) for Unlimited-OCR-2.
4. **Digits & identifiers (`tessdata_best` vs `tessdata_fast`):**
   - `tessdata_best` had **0 digit errors** across all 30 scans (100% exact NIP, REGON, KRS, PESEL, 26-digit
     IBAN/NRB, amounts, dates; `ocr_probe` loose ID recall **100.0%**, 70/70).
   - `tessdata_fast` (only ~0.1 s/page faster) introduced **3 silent digit/code corruptions** that still passed
     `evaluate.py`'s `0.55` string threshold (`potwierdzenia_0003` `na_rachunek` `...100081...` → `...10081...0`,
     `potwierdzenia_0007` `z_rachunku` `661090...` → `681090...`, `odwolania_0010` `numer_postepowania`
     `ZP/107/2026` → `2P/107/2026`) and triggered 2 validation retries. **`tessdata_fast` is not recommended**
     for financial/legal IDs.
5. **Tables & two-column layouts (`potwierdzenia`):** Unlimited-OCR-2 emits explicit pipe-separated table rows
   (`Z rachunku | 02 1090 ...`, `Na rachunek | 19 1030 ...`). Tesseract's default `PSM=3` preserved row labels well
   enough for 10/10 bank confirmations, though `tessdata_fast` dropped 2-digit prefixes on `potwierdzenia_0006`
   (caught by validation retry). Forcing `PSM=6` (single text block) dropped the left-column labels `Z rachunku`
   and `Na rachunek` on `potwierdzenia_0010`, causing the LLM to swap sender and recipient accounts (**F1 0.963**
   on `potwierdzenia`).

**Takeaway:** `OCR_BACKEND=tesseract` with `tessdata_best` (300 dpi, `pol`, default PSM 3) is a viable
high-speed, low-RAM alternative (1 s/page, 150 MB RAM, F1 0.998 with GLM-5.3-Flash), though its raw text has
materially more symbol/noise errors than Unlimited-OCR-2 — a risk if paired with a smaller extraction LLM (M1)
or stricter exact-match scoring on hidden tests. Default remains `OCR_BACKEND=local`.

## Real scans: LLM model × OCR backend (2026-11-21)

All 30 scans in `dane/skany/`, OCR only from the cache (`OCR_CACHE_ONLY=1`, no OCR re-run), the same model for decision
and extraction, configs after commit 62fa6d5 (no invented examples on digit-only fields). GLM with
`LLM_REASONING_EFFORT=low`, the others with `off`. Runs in parallel.

| model | params (total / active) | F1 Unlimited-OCR-2 | F1 Tesseract | LLM s/doc (median) |
|---|---|---|---|---|
| zai-glm-5-3-flash | 320B / 18B | **0.998** (266/1/0) | **0.998** (266/1/0) | 2.6–2.7 |
| ministral-3b-2512 | 3.85B | 0.975 (258/5/8) | 0.943 (247/11/19) | 2.4 |
| ministral-8b-2512 | 8.9B | **0.994** (264/1/2) | **0.992** (263/1/3) | 3.0–3.3 |
| ministral-14b-2512 | 14B | 0.985 (262/4/4) | 0.987 (262/3/4) | 4.2–4.6 |
| mistral-small-2603 (Small 4) | 119B / 6.5B | 0.989 (264/4/2) | 0.987 (263/4/3) | 2.3–2.5 |

Per-class F1 and the misses:
- GLM (both OCRs): only the disputed `pelnomocnictwa_0010` `mocodawca.nazwa` (sole trader). On Tesseract one call hit
  `finish_reason=length` and was recovered by the R1 retry.
- ministral-8b: the same disputed miss plus 1–2 account numbers on transfer confirmations (`z_rachunku` with a `PL`
  prefix in the ground truth returned as null; one `na_rachunek`).
- ministral-14b: writes KRS as `0000000000` / `0000009991` on 2–3 powers of attorney (pelnomocnictwa F1 0.953–0.966),
  apparently over-applying the "keep leading zeros, KRS has 10 digits" hint.
- mistral-small-2603: wrong `czynnosc_powod_id` / `czynnosc_opis` on `odwolania_0001`, one KRS, one account.
- ministral-3b: `miejscowosc` taken from the law firm's letterhead in 5–6 appeals; on Tesseract also IDs (NIP/KRS/
  REGON) and a second Zamawiający on `odwolania_0004`. Noisy OCR hurts the smallest model most.

Takeaways: ministral-8b is the best small model (−0.004 F1 vs GLM on Unlimited-OCR-2, −0.006 on Tesseract) at 36×
fewer total parameters; its misses and ministral-14b's KRS problem look fixable with config hints (tuning tasks).
