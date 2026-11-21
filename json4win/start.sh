#!/usr/bin/env sh
# Converts every PDF in input/ into a JSON file in output/ (same tree, same names).
PYTHONPATH="$(cd "$(dirname "$0")" && pwd)${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m json4win "$@"
