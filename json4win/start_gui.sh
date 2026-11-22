#!/usr/bin/env sh
# Starts the local json4win web GUI on 127.0.0.1 and opens it in a browser.
PYTHONPATH="$(cd "$(dirname "$0")" && pwd)${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m json4win --gui "$@"
