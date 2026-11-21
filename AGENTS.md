# AGENTS.md: json4win (Odwołania2json)

Our solution to the UZP challenge at HackNation 2026: a Python app that takes the PDFs of a KIO appeal
case (appeal, power of attorney, bank-transfer confirmation), **classifies each document by content**,
extracts the business fields, and writes one JSON per PDF in the organizers' format. Anything else gets
an empty `{}`. Scored by F1 on a hidden test set.

Read before working:
- [`docs/architecture.md`](docs/architecture.md): scoring facts, settled decisions D1–D13, pipeline, open decisions.
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
| `ewaluacja/`, `task.pdf` | **us, frozen** | Our approximation of the organizers' F1 metric (`evaluate.py` + `ground_truth/` for cases 01–39) and our copy of the brief. Change `ewaluacja/` only in a dedicated task, **never in the same task as pipeline changes**: it is the yardstick. |
| `README.md`, `dane/`, `oczekiwane-json/`, `szablon-aplikacja/` | **organizers** | Merged from `upstream`. **Never edit**; on conflict take upstream's side. |

## Ground rules

- **Hackathon: choose the simplest thing that works.** No compat layers, no speculative config, no new infra.
  Decisions D1–D13 are settled; don't re-open them in code. Open decisions are made only by their task or the user.
- **The brief's hard requirements:** Python **3.13+**; runtime deps only in `json4win/requirements.txt`,
  pinned, **open source only** (incl. the model: open weights); runs on a CPU-only laptop (16 GB RAM);
  an LLM only over an API hosted by a company **in the EU/EEA**.
- **OCR always, locally:** test documents and real ones are scans, so the PDF text layer is **never** used. Every
  page the pipeline reads goes through the local Unlimited-OCR-2 (`json4win.ocr`), on CPU. Read only as many pages as
  the class config needs.
- **F1 is the score.** Expected `null` with a non-empty prediction is a false positive, so return `null` rather than guess.
  A smaller model and config-only document classes earn stage-2 points; see architecture §1.
- **Classify by content, never by file name.** Unknown documents → `{}`.
- **Person names in the nominative case** (requirement): every `imie_nazwisko`-type value is output in the
  nominative ("Mateusz Szymański", not "Mateusza Szymańskiego"), without titles or functions. Everything else is
  copied as written. The rule lives in the base extraction prompt and in each name field's `opis`.
- **No overfitting to the training set:** the runtime never reads `dane/`, `ewaluacja/` or ground truth, and
  there are no tables of training values (names, NIPs, case numbers). Patterns and instructions must generalise.
- **No secrets in git.** The LLM key lives in `json4win/.env.local` (gitignored). Keep `json4win/.env.example`
  up to date when you add a variable. Training PDFs and outputs never go to non-EU/EEA services.

## Workflow (Orca coordinator + workers, local git only)

Repo: https://github.com/WH-HN2026/json4win (`origin`). **Local mode:** agents never push, never open PRs and
need no `gh`; **the user pushes**. The integration branch is the local **`dev`** (the user merges it into `master`
on GitHub). `upstream` is the organizers' repo (`Urzad-Zamowien-Publicznych/hacknation-2026`, branch `main`).
One roadmap task = one worktree = one branch `t/<id>-<slug>` = one squashed commit on `dev`. No human reviews;
the coordinator's verification replaces them, and a local `make check` replaces CI.

Prerequisites: `git`, Python ≥ 3.13 (`uv` recommended; `make setup` creates a 3.13 venv), `make`.

Each person runs one **coordinator** agent. It doesn't write feature code itself: it dispatches **workers**
through Orca orchestration, each in its own child worktree branched from `dev`, then **verifies** each worker's
branch and squash-merges it into `dev`. Working solo is also allowed: follow the worker steps, then the
verification checklist, then merge yourself.

**Models:** mix models to get independent eyes (`agy models` lists the Antigravity ids):
- Claude Opus 5.5, split about half and half between `--agent claude --model claude-opus-5-5` and
  `--agent antigravity --model claude-opus-5-5-high`;
- Gemini 4 Neon: `--agent antigravity --model gemini-4-neon-high`;
- very simple tasks (mechanical edits, small docs): Gemini 4 Hydrogen, `--agent antigravity --model gemini-4-hydrogen-high`.
Put critical-path or hard-debugging tasks on the one that has proven itself in this repo; when a task is
verified, prefer a different model than the one that wrote it for any follow-up fix or review.

Orca CLI: use `$ORCA_CLI_COMMAND` if it is set, otherwise `orca` inside Orca terminals. Never run bare `orca`
outside Orca on Linux (that's the GNOME screen reader). Load the version-matched guide **once per session**
before the first orchestration command: `orca skills get orchestration` (its references, e.g.
`references/coordinator-loop.md` and `references/recovery-and-cleanup.md`, via `--reference`). The flags
below come from it; if they disagree, the guide wins.

### Coordinator (the main agent, in the main checkout on `dev`)

The coordinator's checkout stays on `dev`. It only merges verified worker branches, runs long shared jobs (the
OCR precompute) and edits docs for decisions the user made; feature code always comes from a worker.

1. **Turn the request into tasks.** If the user names a roadmap ID, use it. Otherwise find the matching roadmap
   task, or add a new roadmap line in the worker's spec. `orca orchestration worker-list` shows who has what.
2. **Write a self-contained spec** (template below), commit everything the worker must see (child worktrees only
   get committed files), and start the worker:
   ```
   orca orchestration worker-start --worktree new-child --base-branch dev --name t-<id>-<slug> \
     --agent <agent> --model <model> --spec-file <spec.md>
   ```
   **Parallelise as much as possible:** start every task whose deps are `[x]` (or whose contracts are fixed by
   stubs on `dev`) and that doesn't share files with a running task, then **end your turn**: Orca wakes you when
   a worker asks or reports. Don't poll and don't type into worker terminals.
3. **Answer questions** with `orca orchestration reply --id <message_id> --body "…"` when the spec or this file
   answers them; otherwise ask the user.
4. **Verify** each `worker_done` against the checklist below. If anything fails, send a concrete list of fixes
   to the same worker (`orca orchestration send --to dispatch:<id> --subject "fixes" --body "…"`) and end your
   turn. Repeat until it passes.
5. **Merge** in the main checkout: `git merge --squash t/<id>-<slug> && git commit -m "<ID>: <task name>"`
   (body: what changed, evidence, F1 before → after). If it conflicts because `dev` moved, `git merge --abort`
   and send the worker "rebase on dev, re-run make check, report again".
6. **Clean up:** remove the worker's worktree with `orca worktree rm` (see `--help`) and delete the branch
   (`git branch -D t/<id>-<slug>`). Report to the user per task: commit, what was verified and how, F1 before →
   after, follow-ups. Remind the user that `dev` is ready to push.

**Verification checklist** (the coordinator does all of it):
- [ ] The branch is rebased on current `dev`, and `make check` passes in the worker's worktree.
- [ ] `git diff dev...t/<id>-<slug>` does what the spec asked, and nothing outside its scope. No unrelated
  refactors, no edits to organizers' files or (outside a dedicated task) `ewaluacja/`, no committed
  `input/`/`output/` contents, no secrets or `.env*` files except `.env.example`.
- [ ] AGENTS.md rules are followed:
  - classification uses content only; nothing reads `dane/`, `ewaluacja/` or ground truth at runtime; no training-value tables;
  - the PDF text layer is never used: every page goes through the local OCR (`json4win.ocr`);
  - output shapes match the training JSONs exactly (keys, list vs. object, types), and unknown documents give `{}`;
  - class-specific behaviour (keywords, fields, prompts) lives in `json4win/config/`, not in `if class == …` code;
  - new deps are open source, pinned in the right requirements file, and install on Windows without a compiler or GPU;
  - LLM calls go only to the configured EU/EEA endpoint, with timeouts; failures degrade to `null`/`{}`, never crash the batch;
  - delivery files (`json4win/requirements.txt`, `start.bat`, `start.sh`, `.env.example`, `json4win/README.md`) are updated if the task needs it;
  - the task is marked `[x]` in the roadmap.
- [ ] The worker's evidence is real and matches the claims: test names and output, the `make eval` lines
  (`TP/FP/FN`, `F1`) **before and after** on the same cases (when the spec asks for eval), and the files it inspected.
- [ ] **No F1 regression** on the full training set (once eval runs end to end), unless the spec accepted one.
- [ ] **One hands-on check by the coordinator itself**, picked to hit the riskiest claim. Run it in the worker's
  worktree (`make setup` first if it has no `.venv`):
  - extraction/classification: `OCR_CACHE_ONLY=1 make eval CASES=… V=1` and compare with the reported numbers;
  - negatives: put `dane/negatywne/*.pdf` and an extra case PDF (e.g. `dane/przyklad_37/2025_BZP 00143067_01.pdf`) in a temp input dir,
    run `python -m json4win --input … --output …`, and confirm every result is `{}`;
  - delivery: from a fresh clone of the branch, `pip install -r json4win/requirements.txt` in a clean venv, then `json4win/start.sh`.

**Worker spec template** (write it to a file, fill it in; a worker can't see your conversation):
```
Task <ID>: <task name>  — repo json4win (local git mode), read AGENTS.md and docs/architecture.md first.
Goal: <the roadmap text for the task, plus anything the user added>.
In scope: <files/dirs the worker may edit>. Out of scope: <what not to touch>.
Contract: <functions / config keys / output fields it must provide or use>.
Done when: <concrete, checkable evidence, e.g. "OCR_CACHE_ONLY=1 make eval: przelew_bankowy fields ≥ 90% TP on
przyklad_01–39, total F1 not lower than <x>; negatives all give {}; pytest json4win/tests/test_x.py passes">.
Follow the worker steps in AGENTS.md. Commit on your branch; do NOT push, do NOT merge.
Report with worker_done: branch, commit SHAs, summary, evidence (commands + results, F1 before → after), known gaps.
```

### Worker (dispatched by a coordinator, or a solo session)

1. **Branch:** you start in a fresh child worktree based on `dev`. Rename the branch to `t/<id>-<slug>`
   (`git branch -m t/<id>-<slug>`). `dev` is a local branch: there is nothing to fetch.
2. **Set up the env:** `make setup` (= `scripts/wt-env.sh`). It creates `.venv` (Python 3.13) in the worktree with
   the runtime and dev deps, and copies `json4win/.env.local` (LLM key) from the main checkout. If the spec asks
   for eval, record the baseline first: `OCR_CACHE_ONLY=1 make eval` (or `CASES=…` for your area).
3. **Work in small commits:** `<ID>: <what>` (e.g. `E1: przelew amount rule`). Stay inside the spec's scope; if
   the task needs more, `ask` before widening it. Never push.
4. **Verify your own work** as described in "Verify your change" below, and save the evidence (commands, output).
5. **Finish:**
   ```bash
   # mark the task [x] in docs/roadmap.md, commit
   git rebase dev        # resolve conflicts (table below)
   make check            # must pass
   OCR_CACHE_ONLY=1 make eval   # only if the spec asks; compare with your baseline
   ```
   - **Dispatched worker:** report with `worker_done` (branch, SHAs, evidence) and **don't merge**; the coordinator
     verifies and merges. If you get fixes via `send`, apply them on the same branch, repeat step 5, report again.
   - **Solo:** go through the verification checklist above yourself, then squash-merge into `dev` (coordinator step 5).
6. If a task grows too big, finish a mergeable part (behind an unused code path or a class that stays disabled
   in config if needed) and propose a new roadmap line for the rest in your report.

### Syncing with the organizers (`upstream`)

When the organizers push new data or rules, the user (or a `U<n>: sync upstream` task) runs
`git fetch upstream && git merge --no-ff upstream/main` **on `dev`** (conflicts in organizers' files: take upstream),
then `make check` and `make eval`. Never squash or rebase an upstream merge: it would lose the upstream parent, and
every later sync would conflict again. Note any rule changes from the brief so this file or the architecture doc
can be updated in a follow-up task.

### Avoiding / resolving conflicts

| Hotspot | Rule |
|---|---|
| `json4win/config/` | One file per document class; a task edits only its own class files. The format is fixed in `json4win/config/README.md`; changing it needs the coordinator's OK (`ask`). |
| Pipeline core (`json4win/json4win/pipeline.py`, `cli.py`) | Keep it generic and thin; class logic lives in config, helpers in their own modules (`ocr.py`, `normalize.py`, `llm.py`, …). One small hook per area. |
| Contract stubs (`ocr.py`, `normalize.py`, `env.py`) | Signatures are fixed; only the owning task implements the body. Others fake them in tests. |
| `json4win/requirements.txt`, `requirements-dev.txt` | On conflict keep both lines, keep them sorted, then `make setup`. |
| `docs/roadmap.md` | Only flip your task to `[x]` (in the finishing commit), and add new tasks at the end of a track. Adjacent-line conflicts are expected: keep both sides. |
| `docs/quality.md` (after V1) | Append your run as a new row/section; don't rewrite others' results. |
| Organizers' files | Never edited by us; take upstream's side. |

### Parallel worktrees, shared resources

- Every worktree has its **own** `.venv` (`make setup`). Shared on disk: the Hugging Face model cache and the
  **OCR cache** (`json4win.env.cache_dir()`, override with `JSON4WIN_CACHE_DIR`). `make eval` runs in a temp dir,
  so parallel evals don't collide. Don't write into `json4win/input/` or `json4win/output/` in tests; use `tmp_path`.
- **OCR is the scarce resource:** the model takes ~7 GB of RAM and minutes of CPU per document. **Never run more than
  one OCR process on the machine.** The coordinator fills the cache for the training set once (`make ocr-cache`);
  everyone else runs with `OCR_CACHE_ONLY=1`, which fails on a cache miss instead of starting OCR. Unit tests fake
  the OCR and never load the model.
- The **LLM API is shared** (one key, rate limits, cost). Iterate with `make eval CASES=<a few cases>`; run the
  full set only for the baseline and the finishing step. Don't loop full evals.

## Commands

```bash
make setup        # .venv (Python 3.13) + deps + json4win/.env.local for this worktree (scripts/wt-env.sh)
make check        # ruff check, ruff format --check, pytest
make fmt          # ruff format + ruff check --fix
make run          # json4win/input -> json4win/output   (ARGS="--input X --output Y -v")
make ocr-cache    # fill the shared OCR cache for dane/ (coordinator only, one process; task P1)
OCR_CACHE_ONLY=1 make eval    # F1 on dane/przyklad_01..39 with ewaluacja/evaluate.py, cached OCR only
OCR_CACHE_ONLY=1 make eval CASES=przyklad_01,przyklad_37 V=1   # subset, list every wrong field
make eval IDEAL=1 NEG=1       # dev-only upper bound using PDF text layer (--ideal-ocr, --negatives, JOBS=4)
OCR_CACHE_ONLY=1 make eval-skany   # F1 on real scans in dane/skany/ (KINDS=..., IDS=..., CASES=..., V=1)
.venv/bin/python ewaluacja/evaluate.py        # evaluator self-test on the reference JSONs (F1=1.000)
cd json4win && pip install -r requirements.txt && ./start.sh   # what the jury runs (start.bat on Windows)
```

**Delivery is `json4win/`** (architecture D1–D3). It must work from a clean clone with only
`pip install -r json4win/requirements.txt` and `start.bat`/`start.sh`, on Windows and Linux, without GPU.
If your change needs a new dependency, env var, model file or system binary, update `json4win/requirements.txt`,
`json4win/.env.example` and `json4win/README.md` in the same branch, and run the clean-venv install once before
merging. System binaries must be avoided unless the task decides otherwise and documents the Windows install.

## Verify your change

- **Unit tests:** pytest, table-driven, next to the code area in `json4win/tests/`. Normaliser and regex tests use
  real strings copied from the training PDFs (short snippets, no whole documents). OCR and LLM are faked in unit
  tests; live calls are opt-in smoke checks.
- **Extraction quality:** `OCR_CACHE_ONLY=1 make eval` before and after; for the touched class,
  `make eval CASES=… V=1` and read the misses. Use `scripts/eval_training.py --keep` to inspect the produced JSON files.
- **Negatives:** every task touching classification runs `dane/negatywne/` and the extra PDFs inside cases through the
  CLI and confirms `{}`.
- **Done** = `make check` passes, F1 has been measured (once the pipeline runs end to end) and did not regress, the
  branch is squash-merged into `dev` by the coordinator, and the task is marked `[x]`.

## Code conventions

- Python ≥ 3.13, standard library first; type hints on public functions; `pathlib`; `logging` (no `print` in the app);
  always `encoding="utf-8"`; JSON with `ensure_ascii=False`. Paths may contain spaces and Polish characters. Code must
  run on Windows (no shell-outs that assume bash, no hardcoded `/`).
- The app is run as `python -m json4win` from `json4win/` (no packaging, no `src/` layout). Tests import `json4win.*`.
- Ask before adding a dependency, or just don't. Prefer pure-Python wheels that install on Windows without a compiler.
- The pipeline is generic: text → classify → extract → normalise → validate → write. Class-specific knowledge
  (keywords, field list, regexes, LLM instructions, short invented examples) lives in `json4win/config/`.
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
- Don't push anything (the user pushes), don't open PRs, and never push to `upstream`.
- Don't use the PDF text layer (`pdftotext`, `pypdf` text extraction, …) in the app; dev scripts may use it only as a yardstick.
