# Roadmap

One line = one task = one worktree = one branch `t/<id>-<slug>` = one squashed commit on `dev` (local git mode,
see AGENTS.md). `[x]` = merged into `dev`. A task may start when everything in its **deps** is `[x]`; tasks that
depend only on contract stubs already on `dev` (`ocr.py`, `normalize.py`, `env.py`, the config format) run in
parallel. Workers flip only their own line to `[x]` (in the finishing commit) and add new tasks at the end of a
track. `orca orchestration worker-list` is the claim list, not this file.

## I: infrastructure and decisions
- [x] **I1** Repo bootstrap: `json4win/` skeleton, AGENTS.md (local mode), Makefile, `scripts/wt-env.sh`, `scripts/eval_training.py`, decisions D10–D13, config format, contract stubs `env.py`, `ocr.py`, `normalize.py`.

## P: OCR
- [ ] **P1** Local OCR engine: Unlimited-OCR-2 on CPU behind `json4win.ocr` (page rendering, pinned revision, shared cache, `OCR_CACHE_ONLY`), `scripts/ocr_cache.py` + `make ocr-cache`, speed/RAM/quality gate in `docs/ocr.md`. deps: I1
- [ ] **P2** Fill the training OCR cache (coordinator runs `make ocr-cache` once, one process). deps: P1

## C: core engine
- [x] **C1** Config-driven engine: config loader/validator, base + decision prompts, LLM client (Mistral API), decision step, read-until-complete loop, extraction with validation/retry, wiring in `pipeline.py`. deps: I1

## E: classes and fields (all driven by the class config)
- [x] **E1** `przelew.yaml`: first version of the class config (`przelew_bankowy`). deps: I1
- [x] **E2** `pelnomocnictwo.yaml`: first version (`mocodawca[]`, `podpisujacy[]`, `pelnomocnicy[]`). deps: I1
- [ ] **E3** `odwolanie.yaml`: first version (`OdwolanieKIO`, `Odwolujacy[]`, `Zamawiajacy[]`, `ZamowieniePubliczne`), incl. `czynnosc_powod_id` from the first charge only. deps: I1
- [x] **E4** Normalisers in `normalize.py`: text, digits, date → ISO, amount → float, int, regex_sub. deps: I1

## T: tuning on real OCR (one class per task)
- [ ] **T1** Tune `przelew` with `OCR_CACHE_ONLY=1 make eval`: read the misses, fix config/prompt. deps: C1, P2, E1, E4
- [ ] **T2** Tune `pelnomocnictwo`. deps: C1, P2, E2, E4
- [ ] **T3** Tune `odwolanie` (incl. how many pages after the marker). deps: C1, P2, E3, E4
- [ ] **T4** Negatives and extra PDFs in cases: all give `{}` (decision prompt / class descriptions). deps: C1, P2

## V: quality
- [ ] **V1** F1 report in `docs/quality.md` (per class and per field, from `make eval V=1`), rerun after every T task. deps: T1, T2, T3
- [ ] **M1** Model comparison on the EU endpoint: GLM-5.3-Flash vs smaller GA open-weight models (e.g. ministral-8b/14b, mistral-small), F1 and size (O6). deps: V1
- [x] **V0** Eval on real scans: `make eval-skany` (`scripts/eval_skany.py` with JSON→YAML GT conversion, per-kind + total F1, `--self-test`). deps: I1

## X: extensibility and transparency (stage 2 scoring)
- [ ] **X1** Demo: add a new document class purely through `json4win/config/`, documented step by step in docs/. deps: C1
- [ ] **X2** Extraction trace (per field: page, source snippet, method, retries) written **outside** `output/`. deps: C1

## D: delivery
- [ ] **D1** Jury path: clean clone → `pip install -r json4win/requirements.txt` → `start.bat` / `start.sh` on Windows and Linux, CPU only, model download, timing on jury-like limits; jury key (O3). deps: P1, C1
- [ ] **D2** Submission docs: project title, LLM used and its size, own quality results. deps: V1
- [ ] **G1** Optional GUI: upload PDFs, show the JSON results (O5). deps: D1
- [x] **D3** LLM API compliance check (`docs/compliance.md`). deps: I1
