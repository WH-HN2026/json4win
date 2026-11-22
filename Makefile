PY := $(if $(wildcard .venv/bin/python),$(CURDIR)/.venv/bin/python,python3)
SRC := json4win scripts

.PHONY: setup check lint fmt test run eval eval-skany ocr-cache

setup:            ## .venv + deps + .env.local for this worktree
	scripts/wt-env.sh

check: lint test  ## what CI runs

lint:
	$(PY) -m ruff check $(SRC)
	$(PY) -m ruff format --check $(SRC)

fmt:
	$(PY) -m ruff format $(SRC)
	$(PY) -m ruff check --fix $(SRC)

test:
	$(PY) -m pytest -q

run:              ## json4win/input -> json4win/output (ARGS=... passes extra flags)
	cd json4win && $(PY) -m json4win $(ARGS)

eval:             ## F1 on training cases (CASES=..., V=1, IDEAL=1, NEG=1, JOBS=4)
	$(PY) scripts/eval_training.py $(if $(CASES),--cases $(CASES)) $(if $(V),-v) $(if $(IDEAL),--ideal-ocr) $(if $(NEG),--negatives) $(if $(JOBS),--jobs $(JOBS))

eval-skany:       ## F1 on real scans in dane/skany (CASES=..., KINDS=..., IDS=..., V=1)
	$(PY) scripts/eval_skany.py $(if $(CASES),--cases $(CASES)) $(if $(KINDS),--kinds $(KINDS)) $(if $(IDS),--ids $(IDS)) $(if $(V),-v)

ocr-cache:        ## fill the shared OCR cache for dane/ (one process; PAGES=4, PATHS="a.pdf b.pdf")
	$(PY) scripts/ocr_cache.py $(if $(PAGES),--pages $(PAGES)) $(if $(PATHS),--paths $(PATHS))
