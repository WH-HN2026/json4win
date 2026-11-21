# AGENTS.md: json4win (Odwołania2json)

Our solution to the UZP challenge at HackNation 2026: a Python app that takes the PDFs of a KIO appeal
case (appeal, power of attorney, bank-transfer confirmation), **classifies each document by content**,
extracts the business fields, and writes one JSON per PDF in the organizers' format. Anything else gets
an empty `{}`. Scored by F1 on a hidden test set.

Read before working:
- [`docs/architecture.md`](docs/architecture.md): scoring facts, settled decisions D1–D9, pipeline, open decisions O1–O5.
- [`docs/roadmap.md`](docs/roadmap.md): tasks, dependencies, status.
- The brief: root [`README.md`](README.md) (Polish); `task.pdf` is our PDF copy of it.
- Target shapes: the training JSONs `dane/przyklad_NN/{odwolanie,pelnomocnictwo,przelew}.json` (canonical) and
  `oczekiwane-json/` (JSONC with field-by-field rules, incl. `czynnosc_powod_id_dict.md`).
- [`json4win/README.md`](json4win/README.md): the app as the jury sees it.

## Repo layout

| Path | Owner | What |
|---|---|---|
| `json4win/` | **us** | The app root: `input/`, `output/`, `config/`, `json4win/` (code), `tests/`, `requirements.txt`, `start.bat`/`start.sh`, `.env.example`. |
| `docs/`, `scripts/`, `Makefile`, `pyproject.toml`, `requirements-dev.txt`, `.github/` | **us** | Dev tooling and docs. The jury doesn't need them. |
| `ewaluacja/`, `task.pdf` | **us, frozen** | Our approximation of the organizers' F1 metric (`evaluate.py` + `ground_truth/` for cases 01–39) and our copy of the brief. Change `ewaluacja/` only in a dedicated task, **never in the same PR as pipeline changes**: it is the yardstick. |
| `README.md`, `dane/`, `oczekiwane-json/`, `szablon-aplikacja/` | **organizers** | Merged from `upstream`. **Never edit**; on conflict take upstream's side. |

## Ground rules

- **Hackathon: choose the simplest thing that works.** No compat layers, no speculative config, no new infra.
  Decisions D1–D9 are settled; don't re-open them in code. Open decisions O1–O5 are made only by their task.
- **The brief's hard requirements:** Python **3.13+**; runtime deps only in `json4win/requirements.txt`,
  pinned, **open source only** (incl. the model: open weights); runs on a CPU-only laptop (16 GB RAM);
  an LLM only over an API hosted by a company **in the EU/EEA**.
- **F1 is the score.** Expected `null` with a non-empty prediction is a false positive, so return `null` rather than guess.
  A smaller model and config-only document classes earn stage-2 points; see architecture §1.
- **Classify by content, never by file name.** Unknown documents → `{}`.
- **No overfitting to the training set:** the runtime never reads `dane/`, `ewaluacja/` or ground truth, and
  there are no tables of training values (names, NIPs, case numbers). Patterns and instructions must generalise.
- **No secrets in git.** The LLM key lives in `json4win/.env.local` (gitignored). Keep `json4win/.env.example`
  up to date when you add a variable. Training PDFs and outputs never go to non-EU/EEA services.

## Workflow (Orca coordinator + workers, no human review)

Repo: https://github.com/WH-HN2026/json4win (`origin`), default branch **`master`**. `upstream` is the organizers'
repo (`Urzad-Zamowien-Publicznych/hacknation-2026`, branch `main`): fetch from it, **never push to it**.
One roadmap task = one worktree = one branch = one PR. No human reviews. Rules (by convention, not branch protection):
- the CI check `check` (`.github/workflows/check.yml`, which runs `make check`) must be green before merging;
- squash merge, and delete the remote branch after merge. The one exception is upstream syncs (`U<n>`, below),
  which use a merge commit so the merge base with `upstream` advances; keep both merge methods enabled in the repo settings;
- **never push to `master` directly.**

Prerequisites on every machine: `gh` (authenticated, with push access to `origin`), `git`, Python ≥ 3.13
(`uv` recommended), `make`.

Each person runs one **coordinator** agent. The coordinator doesn't write feature code itself: it dispatches
**workers** through Orca orchestration, each in its own child worktree, then **verifies** each worker's PR and
merges it. Working solo without a coordinator is also allowed; then follow the worker steps and merge yourself
after the verification checklist.

Orca CLI: use `$ORCA_CLI_COMMAND` if it is set, otherwise `orca` inside Orca terminals. Never run bare `orca`
outside Orca on Linux (that's the GNOME screen reader). Load the version-matched guide **once per session**
before the first orchestration command: `orca skills get orchestration` (its references, e.g.
`references/coordinator-loop.md` and `references/recovery-and-cleanup.md`, via `--reference`). The flags
below come from it; if they disagree, the guide wins.

### Coordinator (the main agent, in the main checkout on `master`)

The coordinator's checkout stays on `master` and only runs `git pull`. It never edits code; every change, docs
included, goes through a worker PR.

1. **Turn the request into tasks.** If the user names a roadmap ID, use it. Otherwise find the matching roadmap
   task, or add a new roadmap line in the worker's spec. Before dispatching, check `gh pr list --state open`:
   an open PR titled `<ID>: …` means someone else has the task.
2. **Write a self-contained spec** (template below) and start the worker in a new child worktree:
   ```
   orca orchestration worker-start --worktree new-child --name t-<id>-<slug> --agent <agent> --spec "<spec>"
   ```
   `<agent>` = the agent you run as, unless the user names another. Up to ~4 workers at once, only for tasks
   whose dependencies are `[x]` and that don't touch the same files (e.g. E1/E2/E3 in parallel: each one owns
   its own class config and extractor files). Start every independent worker, then **end your turn**: Orca
   wakes you when a worker asks something or reports. Don't poll and don't type into worker terminals.
3. **Answer questions** with `orca orchestration reply --id <message_id> --body "…"` when the spec or this file
   answers them; otherwise ask the user.
4. **Verify** each `worker_done` against the checklist below. If anything fails, send a concrete list of fixes
   to the same worker (`orca orchestration send --to dispatch:<id> --subject "fixes" --body "…"`) and end your
   turn. Repeat until it passes.
5. **Merge:** `gh pr merge <n> --squash --delete-branch`, then `git pull` on `master`. If the merge conflicts
   because `master` moved, send the worker "rebase on origin/master, re-run make check, push" and verify again
   (CI green + a quick diff look).
6. **Clean up:** after the merge, remove the worker's worktree with `orca worktree rm` (see
   `orca worktree rm --help`). Report to the user per task: PR link, what was verified and how, F1 before → after,
   follow-ups.

**Verification checklist** (the coordinator does all of it; CI only covers the first item):
- [ ] `gh pr checks <n>` is green, and the PR is ready (not draft) and rebased on current `master`.
- [ ] `gh pr diff <n>` does what the spec asked, and nothing outside its scope. No unrelated refactors, no edits
  to organizers' files or (outside a dedicated task) `ewaluacja/`, no committed `input/`/`output/` contents, no secrets or `.env*` files except `.env.example`.
- [ ] AGENTS.md rules are followed:
  - classification uses content only; nothing reads `dane/`, `ewaluacja/` or ground truth at runtime; no training-value tables;
  - output shapes match the training JSONs exactly (keys, list vs. object, types), and unknown documents give `{}`;
  - class-specific behaviour (keywords, fields, prompts) lives in `json4win/config/`, not in `if class == …` code;
  - new deps are open source, pinned in the right requirements file, and install on Windows without a compiler or GPU;
  - LLM calls go only to the configured EU/EEA endpoint, with timeouts; failures degrade to `null`/`{}`, never crash the batch;
  - delivery files (`json4win/requirements.txt`, `start.bat`, `start.sh`, `.env.example`, `json4win/README.md`) are updated if the task needs it;
  - the task is marked `[x]` in the roadmap.
- [ ] The worker's evidence is real and matches the claims: test names and output, the `make eval` lines
  (`TP/FP/FN`, `F1`) **before and after** on the same cases, and the files it inspected.
- [ ] **No F1 regression** on the full training set, unless the spec accepted one and the PR body says why.
- [ ] **One hands-on check by the coordinator itself**, picked to hit the riskiest claim. Run it in the worker's
  worktree (`make setup` first if it has no `.venv`):
  - extraction/classification: `make eval` (or `make eval CASES=… V=1` for the touched area) and compare with the reported numbers;
  - negatives: put `dane/negatywne/*.pdf` and an extra case PDF (e.g. `dane/przyklad_37/2025_BZP 00143067_01.pdf`) in a temp input dir,
    run `python -m json4win --input … --output …`, and confirm every result is `{}`;
  - delivery: from a fresh clone of the branch, `pip install -r json4win/requirements.txt` in a clean venv, then `json4win/start.sh`.

**Worker spec template** (paste it, fill it in; a worker can't see your conversation):
```
Task <ID>: <task name>  — repo json4win, read AGENTS.md and docs/architecture.md first.
Goal: <the roadmap text for the task, plus anything the user added>.
In scope: <files/dirs the worker may edit>. Out of scope: <what not to touch>.
Contract: <functions / config keys / output fields it must provide or use>.
Done when: <concrete, checkable evidence, e.g. "make eval: przelew_bankowy fields ≥ 90% TP on przyklad_01–39,
total F1 not lower than <x>; negatives in dane/negatywne all give {}; pytest json4win/tests/test_przelew.py passes">.
Follow the worker steps in AGENTS.md; stop after the PR is ready with green CI. Do NOT merge.
Report with worker_done: PR URL, summary, evidence (commands + results, F1 before → after), known gaps.
```

### Worker (dispatched by a coordinator, or a solo session)

1. **Branch:** you start in a fresh child worktree. Rename the branch to `t/<id>-<slug>`
   (`git branch -m t/<id>-<slug>`), and make sure it's based on current `origin/master`
   (`git fetch origin && git rebase origin/master`).
2. **Claim it with a draft PR right away.** Don't edit the roadmap for the claim; the draft PR *is* the claim.
   `git commit --allow-empty -m "<ID>: start" && git push -u origin HEAD && gh pr create --draft --base master --title "<ID>: <task name>" --body "Roadmap task <ID>."`
   If another open PR for the same ID already exists, stop and tell your coordinator (`orca orchestration ask`), or the user if you're solo.
3. **Set up the env:** `make setup` (= `scripts/wt-env.sh`). It creates `.venv` in the worktree with the runtime
   and dev deps, and copies `json4win/.env.local` (LLM key) from the main checkout. Then record the baseline:
   `make eval` (or `CASES=…` for your area). Put those numbers in your report.
4. **Work in small commits:** `<ID>: <what>` (e.g. `E1: parse transfer amount`). Push often. Stay inside the
   spec's scope; if the task needs more, `ask` before widening it.
5. **Verify your own work** as described in "Verify your change" below, and save the evidence (commands, output).
6. **Finish:**
   ```bash
   # mark the task [x] in docs/roadmap.md, commit
   git fetch origin && git rebase origin/master   # resolve conflicts (table below)
   make check                                     # must pass locally
   make eval                                      # full training set; compare with your baseline
   git push --force-with-lease
   gh pr ready
   gh pr checks --watch --fail-fast               # must end green; if red, fix and push again
   ```
   Fill in the PR body: what changed, how it was verified, F1 before → after, known gaps.
   - **Dispatched worker:** report with `worker_done` (PR URL + evidence) and **don't merge**; the coordinator
     verifies and merges. If you get fixes via `send`, apply them on the same branch, repeat step 6, and report again.
   - **Solo:** go through the verification checklist above yourself, then `gh pr merge --squash --delete-branch`.
7. If a task grows too big, finish a mergeable part (behind an unused code path or a class that stays disabled
   in config if needed) and propose a new roadmap line for the rest in your report. **Something should merge at
   least once per day.**

### Syncing with the organizers (`upstream`)

When the organizers push new data or rules: a worker task `U<n>: sync upstream` runs
`git fetch upstream && git merge upstream/main` on its branch (conflicts in organizers' files: take upstream),
re-runs `make check` and `make eval`, and opens a PR like any other, but it is merged with
`gh pr merge <n> --merge --delete-branch` (**not squash**: a squashed upstream merge loses the upstream parent, and
every later sync conflicts again). Don't rebase that branch; merge `origin/master` into it instead. Mention any rule changes from the
brief in the PR body so the coordinator can update this file or the architecture doc in a follow-up task.

### Avoiding / resolving conflicts

| Hotspot | Rule |
|---|---|
| `json4win/config/` | One file per document class; a task edits only its own class files. Changing the shared config format is C1's job (or a dedicated task). |
| Pipeline core (`json4win/json4win/pipeline.py`, `cli.py`) | Keep it generic and thin; class logic lives in config, helpers in their own modules (e.g. `normalize.py`, `pdftext.py`). One small hook per area. |
| `json4win/requirements.txt`, `requirements-dev.txt` | On conflict keep both lines, keep them sorted, then `make setup`. |
| `docs/roadmap.md` | Only flip your task to `[x]` (in the finishing commit), and add new tasks at the end of a track. Adjacent-line conflicts are expected: keep both sides. |
| `docs/quality.md` (after V1) | Append your run as a new row/section; don't rewrite others' results. |
| Organizers' files | Never edited by us; take upstream's side. |

### Parallel worktrees, shared resources

- Every worktree has its **own** `.venv` (`make setup`); nothing else is shared on disk. `make eval` runs in a
  temp dir, so parallel evals don't collide. Don't write into `json4win/input/` or `json4win/output/` in tests;
  use `tmp_path`.
- The **LLM API is shared** (one key, rate limits, cost). Iterate with `make eval CASES=<a few cases>`; run the
  full set only for the baseline and the finishing step. Don't loop full evals.

## Commands

```bash
make setup        # .venv + deps + json4win/.env.local for this worktree (scripts/wt-env.sh)
make check        # ruff check, ruff format --check, pytest; same as CI
make fmt          # ruff format + ruff check --fix
make run          # json4win/input -> json4win/output   (ARGS="--input X --output Y -v")
make eval         # F1 on dane/przyklad_01..39 with ewaluacja/evaluate.py (approximates the hidden metric)
make eval CASES=przyklad_01,przyklad_37 V=1   # subset, list every wrong field
.venv/bin/python ewaluacja/evaluate.py        # evaluator self-test on the reference JSONs (F1=1.000)
cd json4win && pip install -r requirements.txt && ./start.sh   # what the jury runs (start.bat on Windows)
```

**Delivery is `json4win/`** (architecture D1–D3). It must work from a clean clone with only
`pip install -r json4win/requirements.txt` and `start.bat`/`start.sh`, on Windows and Linux, without GPU.
If your change needs a new dependency, env var, model file or system binary, update `json4win/requirements.txt`,
`json4win/.env.example` and `json4win/README.md` in the same branch, and run the clean-venv install once before
merging. System binaries (e.g. an OCR engine) must be avoided unless the task decides otherwise and documents the
Windows install.

## Verify your change

- **Unit tests:** pytest, table-driven, next to the code area in `json4win/tests/`. Normaliser and regex tests use
  real strings copied from the training PDFs (short snippets, no whole documents).
- **Extraction quality:** `make eval` before and after; for the touched class, `make eval CASES=… V=1` and read the
  misses. Use `scripts/eval_training.py --keep` to inspect the produced JSON files.
- **Negatives:** every task touching classification runs `dane/negatywne/` and the extra PDFs inside cases through the
  CLI and confirms `{}`.
- **Done** = `make check` passes, F1 has been measured and did not regress, the PR is squash-merged into `master` with
  green CI, and the task is marked `[x]`.

## Code conventions

- Python ≥ 3.13, standard library first; type hints on public functions; `pathlib`; `logging` (no `print` in the app);
  always `encoding="utf-8"`; JSON with `ensure_ascii=False`. Paths may contain spaces and Polish characters. Code must
  run on Windows (no shell-outs that assume bash, no hardcoded `/`).
- The app is run as `python -m json4win` from `json4win/` (no packaging, no `src/` layout). Tests import `json4win.*`.
- Ask before adding a dependency, or just don't. Prefer pure-Python wheels that install on Windows without a compiler.
- The pipeline is generic: text → classify → extract → normalise → validate → write. Class-specific knowledge
  (keywords, field list, regexes, LLM instructions, few-shot snippets) lives in `json4win/config/`.
- LLM use: as few calls per document as possible, bounded input (first pages only), deterministic settings, JSON
  output validated against the class shape; on error or invalid output fall back to `null` fields / `{}`, log it, go on.
- Wrap errors with context: `raise ValueError(f"przelew {pdf.name}: bad amount {raw!r}") from e`. One failing document
  never stops the batch.
- Never log full document text or the API key at INFO level.

## Don'ts

- Don't edit organizers' files (`README.md`, `dane/`, `oczekiwane-json/`, `szablon-aplikacja/`), and don't tune
  `ewaluacja/` together with the pipeline.
- Don't use the file name to decide a document's class, and don't read training answers at runtime.
- Don't write anything but the per-PDF JSON files into `output/` (traces, logs and caches go elsewhere).
- Don't add closed-source models or libraries, non-EU/EEA APIs, or GPU-only dependencies.
- Don't change the output key names or shapes to "improve" them: the evaluator matches them literally.
- Don't push to `master` or to `upstream`.
