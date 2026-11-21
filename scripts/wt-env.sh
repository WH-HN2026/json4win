#!/usr/bin/env bash
# Per-worktree setup: .venv (Python 3.13, like the jury; uv downloads it if missing) with runtime + dev deps, and json4win/.env.local
# copied from the main checkout if this worktree has none. Safe to re-run.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
cd "$root"

reqs=(-r json4win/requirements.txt -r requirements-dev.txt)
if command -v uv >/dev/null; then
  [[ -d .venv ]] || uv venv --quiet --python 3.13 .venv
  uv pip install --quiet --python .venv/bin/python "${reqs[@]}"
else
  [[ -d .venv ]] || python3 -m venv .venv
  .venv/bin/python -c 'import sys; assert sys.version_info >= (3, 13), sys.version'
  .venv/bin/pip install --quiet "${reqs[@]}"
fi

main=$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')
env=json4win/.env.local
if [[ ! -f $env && $main != "$root" && -f $main/$env ]]; then
  cp "$main/$env" "$env"
  echo "copied $env from $main"
fi
[[ -f $env ]] || echo "warning: no $env (copy json4win/.env.example and fill it in)"

echo "python: $(.venv/bin/python --version)  venv: $root/.venv"
echo "next:   make check   |   make eval CASES=przyklad_01,przyklad_02"
