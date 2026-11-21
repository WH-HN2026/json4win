# Architecture: json4win (Odwołania2json)

The brief is the root [`README.md`](../README.md) (Polish; [`task.pdf`](../task.pdf) is our copy).
Organizers' material: [`oczekiwane-json/`](../oczekiwane-json) (target shapes, JSONC with comments),
[`dane/`](../dane) (60 training cases + `negatywne/`), [`szablon-aplikacja/`](../szablon-aplikacja).
Ours: [`ewaluacja/`](../ewaluacja), an approximation of the organizers' F1 metric with ground truth for
`przyklad_01`–`przyklad_39` only.

## 1. Scoring facts that drive every decision

- Stage 1: **F1 = 100%** on a hidden test set of complete cases. Stage 2: F1 50%, plus up to 20 pts
  for a *smaller* LLM (fewer parameters = more points), 20 pts for adding document classes/fields via
  config only, 10 pts for extras (GUI). Transparency of extraction is a bonus.
- Our evaluator (`ewaluacja/evaluate.py`, an approximation of the hidden metric): string fields match by
  `SequenceMatcher` ratio ≥ 0.55 after whitespace/case normalisation; numbers match exactly; expected `null`
  vs. a non-empty prediction is a **false positive**. So: return `null` when unsure, don't guess. A slightly
  wrong string still matches, so keep near-misses rather than nulling them.
- Target machine: office laptop, 16 GB RAM, Intel i7, **no GPU**, Python 3.13+, `pip install -r
  requirements.txt`. Open-source components and open-weight models only; an LLM is used over an API hosted by a
  company in the **EU/EEA**, and the jury gets an API key with the delivery.
- The training PDFs mostly have a text layer, but the hidden test set and real documents are **scans**
  (user's decision): the text layer is never used.
- Training data is synthetic: 74 of 189 NIPs and 39 of 60 account numbers fail their checksums. Validate
  formats (digit counts), never checksums.

## 2. Settled decisions

- **D1** Python 3.13+, standard library first. CLI `python -m json4win` (wrappers `start.bat`,
  `start.sh`) is the execution interface. A GUI, if any, calls the same pipeline.
- **D2** The app root is `json4win/`: `input/` and `output/` live there, and so do
  `requirements.txt`, `config/` and the start scripts. Repo-root files (Makefile, `scripts/`,
  `pyproject.toml`, `requirements-dev.txt`, CI) are dev tooling only.
- **D3** Output mirrors input: `input/<case>/<name>.pdf` → `output/<case>/<name>.json`. Names
  may contain spaces and Polish characters. Nothing else is written to `output/`.
- **D4** Classify by **content**, never by file name. A document that matches no class (negatives,
  BZP/TED notices, decisions, brochures...) → `{}`.
- **D5** Output JSON follows the shapes of `dane/*/{odwolanie,pelnomocnictwo,przelew}.json`
  exactly (key names, object vs. list, int vs. float vs. string). Where `oczekiwane-json/` and the
  training JSONs differ (e.g. `pesel`), the training JSONs win.
- **D6** Document classes are data: one YAML file per class in `json4win/config/` (format:
  [`json4win/config/README.md`](../json4win/config/README.md)) describes the class for the decision model,
  how far to read, the output template and per-field rules. Adding a class or a field must not require code
  changes. Code is generic (§3).
- **D7** Every document is independent: a failure gives `{}` for that file and the batch goes on.
- **D8** Quality is measured only with `ewaluacja/evaluate.py`, via `make eval`
  (`scripts/eval_training.py`, which maps our files to the evaluator's fixed names by top-level key).
- **D9** The runtime never reads `dane/`, `ewaluacja/` or ground truth. No per-case lookup tables;
  examples in config are short and invented (right format, not copied training values).
- **D10 OCR:** `baidu/Unlimited-OCR-2` (3B VLM, MIT) runs **locally on CPU**, page by page, for every page the
  pipeline reads. Never the PDF text layer. Pinned model revision; weights downloaded from Hugging Face on first
  run. Results are cached by (PDF sha256, page, model revision, render settings) in a per-user cache dir shared
  by all worktrees (`JSON4WIN_CACHE_DIR` overrides). `OCR_CACHE_ONLY=1` turns a cache miss into an error (dev/eval).
  Contract: `json4win/json4win/ocr.py`.
- **D11 LLM:** Mistral La Plateforme (Mistral AI, France), OpenAI-compatible chat completions, **EU regional
  endpoint** `https://api.eu.mistral.ai/v1` (inference in EU/EFTA data centers; the default `api.mistral.ai`
  is global with no location commitment, see [`compliance.md`](compliance.md)). Only GA models: Public Preview
  models (e.g. DeepSeek V4.1 Flash) allow no training opt-out or ZDR. Decision model and extraction model are both `zai-glm-5-3-flash`
  (GLM-5.3-Flash, MIT, 320B MoE / 18B active), set separately in env (`LLM_MODEL_DECISION`, `LLM_MODEL_EXTRACT`)
  so others (smaller GA open-weight models) can be compared. GLM is a reasoning model: on
  this API `message.content` is a list of `thinking` and `text` blocks, and reasoning tokens count against
  `max_tokens`.
- **D12 Config-driven prompts:** a generic base prompt is filled in from the class config (fields, types, formats,
  hints, template). The LLM builds the output JSON **and fixes OCR typos** using the expected formats (e.g. `0`/`O`,
  `1`/`l`); deterministic normalisers then canonicalise values (`json4win/json4win/normalize.py`).
- **D13 Env:** settings come from environment variables, with `json4win/.env.local` loaded at start
  (`json4win/json4win/env.py`); every variable is listed in `json4win/.env.example`.

## 3. Pipeline

```
PDF
 │
 ▼
[1] OCR page 1 (local Unlimited-OCR-2, cached)
 │
 ▼
[2] DECISION MODEL: "what document is this?"   (prompt built from every class config's description)
     <class id> | "inne" ───────────────────────────────────────────► {}  END
 │
 ▼
[3] load that class's config
 │
 ▼
[4] "is the document complete?"  = config marker regex matched in the text read so far,
     else (if configured) the decision model answers the config's completeness question
     NO ──► OCR the next page (never beyond max pages) ──► back to [4]
 │ YES (+ the configured number of pages after the marker)
 ▼
[5] base prompt + class config  ──►  [6] EXTRACTION LLM  ──►  JSON
 │
 ▼
[7] normalise each field (config `normalizacja` kind, normalize.py)
 │
 ▼
[8] validate against the config (template keys, types, `format` regex, allowed values)
     errors ──► back to [6] with the list of errors (at most 2 retries) ──► still invalid: that field = null
 │
 ▼
output/<case>/<name>.json        (+ trace outside output/, task X2)
```

Normaliser kinds (contract for configs and `normalize.py`): `text`, `digits`, `date` (→ `YYYY-MM-DD`),
`amount` (→ float), `int`, `regex_sub` (params `pattern`, `repl`). Details in the `normalize.py` docstring.

## 4. Open decisions

- **O3** Jury API key: the dev key lives in `json4win/.env.local`; before delivery the user generates a separate
  key with a spending limit for the jury and we decide how it is handed over (not in git) [D1].
- **O5** GUI: yes/no and form [G1].
- **O6** Model size vs. F1: GLM-5.3-Flash (320B total, 18B active) scores low on the size
  criterion; compare F1 with smaller open-weight models once the pipeline works end to end [M1].
- **O7** OCR speed on the jury laptop (CPU only, possibly no AVX-512): measured by P1; reading only the pages a
  class needs is the main lever.
