# Model Comparison (Stage-2 LLM Size vs. F1)

> [!NOTE]
> **Status: Partial (2026-11-21).** Candidate verification from primary sources and all four homogeneous
> ideal-OCR runs (`przyklad_01..39` + 16 negatives) are complete. Mixed decision+extraction runs were
> paused before completion on coordinator/user request; see [Next steps](#6-next-steps) for the remaining
> evaluations. No defaults in `json4win/.env.example` or class configs were changed.

## 1. Scoring & compliance context

- **Stage 1:** F1 = 100% on the hidden test set ([`README.md`](../README.md) §7).
- **Stage 2:** F1 = 50% + flexibility/extensibility = 50%, including **1–20 pts for LLM size** (*"Im mocniejszy
  model liczony w bilionach parametrów, tym mniejsza ilość punktów"* — smaller parameter count = more points).
- **Hard rules** ([`docs/architecture.md`](architecture.md) §1 & D11, [`docs/compliance.md`](compliance.md)):
  - Open-weight model with an OSI-compatible open-source licence (e.g. Apache 2.0 / MIT).
  - **GA** lifecycle only on Mistral La Plateforme (Public Preview / Labs models prohibit training opt-out and ZDR).
  - Available on Mistral's EU regional endpoint (`https://api.eu.mistral.ai/v1`) for delivery (task D1).
  - Supports JSON mode (`response_format: {"type": "json_object"}`) on `/v1/chat/completions`.

---

## 2. Candidate models (primary-source metadata)

Verified on **2026-11-21** against `GET https://api.mistral.ai/v1/models`, `GET https://api.eu.mistral.ai/v1/models`,
Mistral model documentation (`docs.mistral.ai/models/*`), Hugging Face model API/READMEs, and live JSON-mode
smoke checks (`temperature=0`, `response_format={"type": "json_object"}`) on both global and EU endpoints.

| Alias | Resolved API ID | Model | Params (total / active) | Arch. | Licence | Lifecycle | JSON mode | EU endpoint (`api.eu.mistral.ai`) | Global price (USD / 1M in / out) | Rule check |
|---|---|---|---|---|---|---|---|---|---|---|
| `ministral-3b-latest` | `ministral-3b-2512` | Ministral 3 3B Instruct | **3.85B / 3.85B** *(3.4B LM + 0.4B vision; HF: 3,849,090,048)* | Dense VLM | **Apache 2.0** | **GA** *(2025-12-02)* | Yes *(verified)* | Yes *(verified)* | $0.10 / $0.10 | **Pass** |
| `ministral-8b-latest` | `ministral-8b-2512` | Ministral 3 8B Instruct | **8.92B / 8.92B** *(8.4B LM + 0.4B vision; HF: 8,918,026,240)* | Dense VLM | **Apache 2.0** | **GA** *(2025-12-02)* | Yes *(verified)* | Yes *(verified)* | $0.15 / $0.15 | **Pass** |
| `ministral-14b-latest` | `ministral-14b-2512` | Ministral 3 14B Instruct | **13.95B / 13.95B** *(13.5B LM + 0.4B vision; HF: 13,945,031,680)* | Dense VLM | **Apache 2.0** | **GA** *(2025-12-02)* | Yes *(verified)* | Yes *(verified)* | $0.20 / $0.20 | **Pass** |
| `mistral-small-latest` | `mistral-small-2603` | Mistral Small 4 | **119B / 6.5B** *(128 experts, 4 active; HF: 119,401,317,376)* | Hybrid MoE *(instant default)* | **Apache 2.0** | **GA** *(2026-03-16)* | Yes *(verified)* | Yes *(verified)* | $0.15 / $0.60 | **Pass** |
| `zai-glm-5-3-flash` *(ref.)* | `zai-glm-5-3-flash` | Z.ai GLM 5.3 Flash | **320B / 18B** *(HF: 321,323,031,390)* | Reasoning MoE | **MIT** | **GA** *(Third-party, 2026-10-22)* | Yes *(verified)* | Yes *(verified in D3)* | $0.15 / $0.50 | **Pass (ref.)** |

Primary sources:
- Ministral 3 3B: [docs.mistral.ai](https://docs.mistral.ai/models/ministral-3-3b-25-12), [HF `mistralai/Ministral-3-3B-Instruct-2512`](https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512) *(note: `/v1/models` reports `max_context_length: 131072`, docs list 256k; both far exceed our prompts)*.
- Ministral 3 8B: [docs.mistral.ai](https://docs.mistral.ai/models/ministral-3-8b-25-12), [HF `mistralai/Ministral-3-8B-Instruct-2512`](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512).
- Ministral 3 14B: [docs.mistral.ai](https://docs.mistral.ai/models/ministral-3-14b-25-12), [HF `mistralai/Ministral-3-14B-Instruct-2512`](https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512).
- Mistral Small 4: [docs.mistral.ai](https://docs.mistral.ai/models/mistral-small-4-0-26-03), [HF `mistralai/Mistral-Small-4-119B-2603`](https://huggingface.co/mistralai/Mistral-Small-4-119B-2603) *(runs in fast non-reasoning instant mode by default when `reasoning_effort` is omitted: `reasoning_tokens=0` in live smoke check; returns plain string `content`)*.
- Z.ai GLM 5.3 Flash: [docs.mistral.ai](https://docs.mistral.ai/models/zai-glm-5-3-flash), [HF `zai-org/GLM-5.3-Flash`](https://huggingface.co/zai-org/GLM-5.3-Flash) (see [`docs/compliance.md`](compliance.md)).

All five models pass every compliance criterion (open-weight Apache 2.0/MIT, GA, EU endpoint, JSON mode). No candidate was disqualified.

---

## 3. Homogeneous evaluation results (ideal OCR, partial)

All candidate runs used `LLM_MODEL_DECISION=<model> LLM_MODEL_EXTRACT=<model> make eval IDEAL=1 NEG=1 V=1 JOBS=4`
against `https://api.mistral.ai/v1` on the full `dane/przyklad_01..39` ground-truth set (39 cases, 1,172 assertions:
1,135 valued + 37 null) plus 16 negative PDFs (12 in `dane/negatywne/` + 4 extra case PDFs). The reference row is
the baseline recorded on the same day in [`docs/quality.md`](quality.md).

| Decision + Extract model | Params (total / active) | Licence | Lifecycle | `odwolanie` F1 | `pelnomocnictwo` F1 | `przelew` F1 | **Total F1** | TP / FP / FN | null ok / zle | Negatives FP | Wall time | Failures / retries |
|---|---|---|---|---:|---:|---:|---:|---|---:|---:|---:|---|
| `ministral-3b-latest` (`ministral-3b-2512`) | 3.85B / 3.85B | Apache 2.0 | GA | 0.973 | 0.995 | 0.944 | **0.973** | 1085 / 11 / 50 | 30 / 7 | **0 / 16** | 99.4s | 1 doc failed (`finish_reason='length'` on `przyklad_22/odwolanie.pdf`); 5 docs val-retried (8 retries), 1 nulled |
| `ministral-8b-latest` (`ministral-8b-2512`) | 8.92B / 8.92B | Apache 2.0 | GA | 0.988 | 0.969 | 0.969 | **0.980** | 1110 / 21 / 25 | 22 / 15 | **0 / 16** | 130.5s | 0 LLM errors; 11 docs val-retried (11 retries), 0 nulled |
| `ministral-14b-latest` (`ministral-14b-2512`) | 13.95B / 13.95B | Apache 2.0 | GA | 0.998 | 0.980 | 0.985 | **0.991** | 1120 / 5 / 15 | **37 / 0** | **0 / 16** | 189.3s | 0 LLM errors; 25 docs val-retried (30 retries), 2 nulled |
| `mistral-small-latest` (`mistral-small-2603`) | 119B / 6.5B | Apache 2.0 | GA | 0.994 | **1.000** | **0.996** | **0.996** | 1131 / 6 / 4 | 33 / 4 | **0 / 16** | **70.9s** | 0 LLM errors; 3 docs val-retried (4 retries), 1 nulled |
| `zai-glm-5-3-flash` *(ref., `quality.md`)* | 320B / 18B | MIT | GA | **0.999** | **1.000** | 0.987 | **0.997** | 1128 / 0 / 7 | **37 / 0** | **0 / 16** | *n/a (baseline)* | 1 doc failed (`finish_reason='length'` on `przyklad_31/potwierdzenie_przelewu.pdf`) |

Key observations:
- **Classification is 100% accurate at every size (including 3.85B):** all four models classified 133/133 PDFs
  correctly (39 `odwolanie`, 39 `pelnomocnictwo`, 39 `przelew`, 16/16 `inne` with 0 false positives on negatives;
  `ministral-3b-latest` also classified `przyklad_22/odwolanie.pdf` correctly and only hit `finish_reason='length'`
  during extraction). *(Caveat from `quality.md`: 3 of 12 files in `dane/negatywne/` have no embedded text layer and
  must still be verified on real OCR in T4.)*
- **Zero HTTP 429 or invalid-JSON failures** occurred across all four runs (532+ document executions).
- **Mistral Small 4 (`mistral-small-2603`)** reaches **F1 = 0.996** (within 0.001 of GLM-5.3-Flash, beating GLM on
  `przelew` and matching 1.000 on `pelnomocnictwo`), with **0 LLM errors** and the fastest wall time (**70.9s**), at
  2.7× fewer total parameters (2.8× fewer active) than GLM-5.3-Flash.
- **Ministral 3 14B (`ministral-14b-2512`)** reaches **F1 = 0.991** as a **13.95B dense** model (**23× smaller total**
  than GLM-5.3-Flash, **8.5× smaller total** than Mistral Small 4), with **0 LLM errors**, **37/37 null accuracy**
  (`null zle=0`), and **0.998 F1 on `odwolanie`**.

---

## 4. Field-level failure patterns (inputs for tuning tasks T1–T3)

No configs or prompts were modified in M1. The misses of the smaller models cluster into a few concrete fields that
appear addressable in tuning tasks T1–T3:

### `ministral-14b-latest` (15 misses total: 5 FP, 15 FN; 0 null errors)
- **`pelnomocnictwo`: `mocodawca[0].data.krs` (5 misses: `przyklad_08, 15, 23, 24, 32`):** on **4 of the 5** cases,
  14B echoed the config example value `'0000123456'` from `json4win/config/pelnomocnictwo.yaml` (`przyklady: ["0000123456"]`,
  with wording *"zachowaj wiodące zera"*) instead of copying the printed `999...` KRS; on `przyklad_23` it returned `None`.
  Fixing example echoing in T2 alone could recover 4–5 fields (~+0.004 F1).
- **`przelew`: `z_rachunku` (3: `przyklad_14, 19, 25`) & `na_rachunek` (2: `przyklad_14, 25`):** returned `None`
  (some nulled after 2 validation retries on 26-digit `PL..` space-grouped account numbers).
- **`przelew`: `numer_transakcji` (2: `przyklad_17, 38`):** returned `None` on receipt-style layouts with dot leaders
  (`NR REF. .... CEN...`).
- **`odwolanie`: `ZamowieniePubliczne.numer_ted` (2: `przyklad_05, 23`):** returned `None` on `TED: 2026/S239-999475`
  (no space between `S` and issue number).
- **`pelnomocnictwo`: `mocodawca[0].data.nazwa` (1: `przyklad_09`):** expanded `'sp. z o.o.'` to
  `'spółka z ograniczoną odpowiedzialnością'`.

### `mistral-small-latest` (8 misses total: 6 FP, 4 FN; 4 null errors)
- **`odwolanie`: `OdwolanieKIO.data` & `miejscowosc` (2 cases each: `przyklad_01, 36`):** hallucinated city/date when
  no header date line existed (4 `null zle` FPs — pulled city from Odwołujący's address / invented date).
- **`odwolanie`: `OdwolanieKIO.czynnosc_powod_id` (2: `przyklad_05, 17`):** predicted `1` (*Decyzja o odrzuceniu oferty*)
  instead of `7` (*Zaniechanie odrzucenia oferty*) on *"nie odrzucił oferty"*.
- **`przelew`: `na_rachunek` (1: `przyklad_08`) & `z_rachunku` (1: `przyklad_16`):** returned `None` (1 nulled after
  validation retries).

### `ministral-8b-latest` (40 misses total: 21 FP, 25 FN; 15 null errors)
- **`przelew`: `numer_transakcji` (14 misses):** systematically returned `None` (over-applied the cautious null hint in
  `przelew.yaml` on `NR REF.` / `Numer referencyjny` layouts).
- **`odwolanie`: `OdwolanieKIO.data` (8) & `miejscowosc` (7):** 15 `null zle` FPs when no header line was present
  (pulled from party addresses / challenged act date). Note: 100% recall (`626/626 TP`, `0 FN`) on `odwolanie`!
- **`pelnomocnictwo`: `mocodawca[0].data.krs` (9) & `nip` (2):** hallucinated `'0000000000'` on 5 KRS and 1 NIP cases,
  and returned `None` on the rest.

### `ministral-3b-latest` (57 misses total: 11 FP, 50 FN; 7 null errors)
- **`przelew`: `numer_transakcji` (21 misses):** returned `None` on over half of transfers.
- **`odwolanie`: `przyklad_22/odwolanie.pdf` complete failure (16 FN):** exhausted `LLM_MAX_TOKENS=16000`
  (`finish_reason='length'`, degenerate repetition loop in JSON generation).
- **`odwolanie`: `data` (5), `miejscowosc` (2), `czynnosc_powod_id` (6), `czynnosc_dzien`/`czynnosc_opis` (2 each)** and
  `pelnomocnictwo`: `mocodawca_podpisujacy` (3 misses; otherwise **0.995 F1** on `pelnomocnictwo`!).

---

## 5. Preliminary recommendation & Stage-2 trade-off

*(Preliminary — pending mixed-setup runs and real-OCR validation. Do not change `.env.example` defaults until the
coordinator and user decide.)*

- **Decision model (`LLM_MODEL_DECISION`):** **`ministral-3b-latest` (`ministral-3b-2512`, 3.85B)** is the top
  candidate so far — 133/133 (100%) classification accuracy and 0/16 negative FPs at 3.85B parameters and $0.10/M tokens.
  *(Keep `ministral-8b-latest` as the fallback if 3B misclassifies noisy real OCR in T4.)*
- **Extraction model (`LLM_MODEL_EXTRACT`):** two Pareto-optimal options depending on how aggressively we target
  Stage-2 model-size points vs. raw zero-tuning F1:
  1. **Maximum Stage-2 size-points option (recommended if T1–T2 recover its config-driven misses):**
     **`ministral-14b-latest` (`ministral-14b-2512`, 13.95B dense)**.
     - **Trade-off:** 23× smaller total than GLM-5.3-Flash (13.95B vs 320B) and 8.5× smaller than Mistral Small 4 (119B)
       — strongly favoured under the brief's *"liczonych w bilionach parametrów"* criterion (potential major gain in the
       1–20 pt LLM-size bucket) — at a current ideal-OCR cost of only **−0.006 F1** (0.991 vs 0.997, ≈ −0.3 pts out of 50
       in Stage 2), with 4–5 of its 15 misses caused by echoing `'0000123456'` from `pelnomocnictwo.yaml`.
  2. **Safest Stage-1 / highest zero-tuning F1 option:**
     **`mistral-small-latest` (`mistral-small-2603`, 119B total / 6.5B active)**.
     - **Trade-off:** matches baseline F1 (**0.996** vs 0.997) with **0 LLM errors** and **70.9s** runtime (2.7× faster
       than 14B), while cutting total params 2.7× and active params 2.8× vs GLM-5.3-Flash. However, if the jury scores
       strictly by *total* parameters (119B), it yields noticeably fewer Stage-2 size points than 14B.

---

## 6. Next steps

Before closing task M1 and selecting final delivery defaults (task D1):
1. **Mixed ideal-OCR runs (`make eval IDEAL=1 NEG=1 V=1 JOBS=4`):**
   - `ministral-3b-latest` (decision) + `ministral-14b-latest` (extract)
   - `ministral-3b-latest` (decision) + `mistral-small-latest` (extract)
   - `ministral-8b-latest` (decision) + `ministral-14b-latest` (extract) *(if needed as a larger-classifier check)*
2. **Real-OCR validation (after P2 & T1–T4):**
   - Re-evaluate the top 1–2 setups with `OCR_CACHE_ONLY=1 make eval` and `OCR_CACHE_ONLY=1 make eval-skany` (including
     the 3 scanned negatives in `dane/negatywne/` that had empty text layers under `IDEAL=1`) — small models may degrade
     differently under real OCR noise than on clean PDF text layers.
   - Verify end-to-end latency and stability on the delivery EU endpoint (`https://api.eu.mistral.ai/v1`) before
     locking `LLM_MODEL_DECISION` and `LLM_MODEL_EXTRACT` in `.env.example` (task D1).
