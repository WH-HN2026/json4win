# Architecture: json4win (Odwołania2json)

The brief is the root [`README.md`](../README.md) (Polish; [`task.pdf`](../task.pdf) is our copy).
Organizers' material: [`oczekiwane-json/`](../oczekiwane-json) (target shapes, JSONC with comments),
[`dane/`](../dane) (60 training cases + `negatywne/`), [`szablon-aplikacja/`](../szablon-aplikacja).
Ours: [`ewaluacja/`](../ewaluacja), an approximation of the organizers' F1 metric with ground truth for
`przyklad_01`–`przyklad_39` only.

## 1. Scoring facts that drive every decision

- Stage 1: **F1 = 100%** on a hidden test set of complete cases. Stage 2: F1 50%, plus up to 20 pts
  for a *smaller* LLM, 20 pts for adding document classes/fields via config only, 10 pts for extras
  (GUI). Transparency of extraction is a bonus.
- Our evaluator (`ewaluacja/evaluate.py`, an approximation of the hidden metric): string fields match by `SequenceMatcher` ratio ≥ 0.55 after
  whitespace/case normalisation; numbers match exactly; expected `null` vs. a non-empty prediction
  is a **false positive**. So: return `null` when unsure, don't guess.
- Target machine: office laptop, 16 GB RAM, i7, **no GPU**, Python 3.13+, `pip install -r
  requirements.txt`. Open-source components and open-weight models only; an LLM is used over an
  API hosted by a company in the **EU/EEA**, and the jury gets an API key with the delivery.

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
- **D6** Document classes are data: one file per class in `json4win/config/` describes detection,
  output fields and extraction instructions. Adding a class or a field must not require code
  changes. Code is generic: text → classify → extract → normalise → validate → write.
- **D7** Every document is independent: a failure gives `{}` for that file and the batch goes on.
- **D8** Quality is measured only with `ewaluacja/evaluate.py`, via `make eval`
  (`scripts/eval_training.py`, which maps our files to the evaluator's fixed names by top-level key).
- **D9** The runtime never reads `dane/`, `ewaluacja/` or ground truth. No per-case lookup tables;
  few-shot examples in config must be generic and short.

## 3. Pipeline (target)

```
PDF ─► text per page (text layer; OCR fallback for scans; first N pages)
    ─► classify (config: keywords/patterns first, LLM only if ambiguous)  ─► none → {}
    ─► extract fields for the class (config: regex for structured fields, LLM for the rest)
    ─► normalise (dates, NIP/REGON/KRS, accounts, BZP/TED, amounts) ─► validate against class shape
    ─► output/<case>/<name>.json   (+ trace outside output/, task X2)
```

Regex-first keeps the LLM small and cheap (stage 2 points) and makes the result explainable.

## 4. Open decisions (owner: the task in brackets)

- **O1** LLM provider and model: open-weight, EU/EEA-hosted API, as small as F1 allows [I2].
- **O2** PDF text and OCR libraries (must be pip-installable, CPU, Windows-friendly) [P1, P2].
- **O3** Shipping the API key: the brief requires delivering a key, AGENTS.md forbids secrets in
  git. Decide how the key reaches the jury (e.g. outside the repo, in the submission form) [I2].
- **O4** Class config format and field schema [C1].
- **O5** GUI: yes/no and form [G1].
