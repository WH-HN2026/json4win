# Roadmap

One line = one task = one worktree = one branch `t/<id>-<slug>` = one PR titled `<ID>: <name>`.
`[x]` = merged into `master`. A task may start when everything in its **deps** is `[x]`.
Workers flip only their own line to `[x]` (in the finishing commit) and add new tasks at the end
of a track. The open PR list is the claim list, not this file.

## I: infrastructure and decisions
- [x] **I1** Repo bootstrap: `json4win/` skeleton, AGENTS.md, Makefile, CI `check`, `scripts/wt-env.sh`, `scripts/eval_training.py`.
- [ ] **I2** LLM provider and client: decide O1 and O3 (docs/architecture.md), add a minimal client with timeouts, retries and env config, update `.env.example`. deps: I1

## P: document text
- [ ] **P1** Text-layer extraction from PDFs, first N pages (N configurable), with page numbers kept for traces. deps: I1
- [ ] **P2** OCR fallback for scanned or empty-text pages, CPU only. Pick the library (O2). deps: P1

## C: classification
- [ ] **C1** Config-driven classifier: odwolanie / pelnomocnictwo / przelew / none (→ `{}`), by content only. Defines the class file format in `json4win/config/` (O4). Must pass `dane/negatywne` and the extra PDFs in cases (e.g. `przyklad_37`). deps: P1

## E: extraction (one class per task, all driven by the class config)
- [ ] **E1** `przelew` extraction (`przelew_bankowy`). deps: C1
- [ ] **E2** `pelnomocnictwo` extraction (`mocodawca[]`, `podpisujacy[]`, `pelnomocnicy[]`). deps: C1
- [ ] **E3** `odwolanie` extraction (`OdwolanieKIO`, `Odwolujacy[]`, `Zamawiajacy[]`, `ZamowieniePubliczne`), incl. `czynnosc_powod_id` from the first charge only. deps: C1
- [ ] **E4** Shared normalisers: dates → ISO, NIP/REGON/KRS digits, IBAN/account digits, BZP/TED formats, amounts → float. deps: I1

## V: quality
- [ ] **V1** Baseline F1 report in `docs/quality.md` (per-class and per-field misses from `make eval V=1`), rerun after every E task. deps: E1, E2, E3

## X: extensibility and transparency (stage 2 scoring)
- [ ] **X1** Demo: add a new document class purely through `json4win/config/`, documented step by step in docs/. deps: C1, E1
- [ ] **X2** Extraction trace (per field: page, source snippet, method) written **outside** `output/`. deps: P1

## D: delivery
- [ ] **D1** Jury path: clean clone → `pip install -r json4win/requirements.txt` → `start.bat` / `start.sh` works on Windows and Linux, CPU only; README for the jury. deps: I2
- [ ] **D2** Submission docs: project title, LLM used and its size, own quality results. deps: V1
- [ ] **G1** Optional GUI: upload PDFs, show the JSON results. deps: D1
