PY := $(if $(wildcard .venv/bin/python),$(CURDIR)/.venv/bin/python,python3)
SRC := json4win scripts

.PHONY: setup check lint fmt test run eval

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

eval:             ## F1 on training cases (CASES=przyklad_01,przyklad_02 for a subset)
	$(PY) scripts/eval_training.py $(if $(CASES),--cases $(CASES)) $(if $(V),-v)
