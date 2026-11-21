#!/usr/bin/env python3
"""Run json4win on the training cases in dane/ and score it with ewaluacja/evaluate.py.

Usage: scripts/eval_training.py [--cases przyklad_01,przyklad_02] [--keep] [-v]

1. Copies only the PDFs of dane/<case>/ to a temp input/ tree (the expected JSONs stay behind).
2. Runs `python -m json4win --input ... --output ...`.
3. Maps each output JSON to odwolanie/pelnomocnictwo/przelew.json by its top-level key (our output
   is named after the input PDF, the evaluator wants fixed names), then runs a copy of
   ewaluacja/evaluate.py restricted to the selected cases. The scoring code is not modified.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DANE, EVAL, APP = ROOT / "dane", ROOT / "ewaluacja", ROOT / "json4win"
TARGET = {
    "OdwolanieKIO": "odwolanie.json",
    "mocodawca": "pelnomocnictwo.json",
    "pelnomocnicy": "pelnomocnictwo.json",
    "przelew_bankowy": "przelew.json",
}


def run_app(inp: Path, out: Path) -> int:
    run = subprocess.run(
        [sys.executable, "-m", "json4win", "--input", inp, "--output", out], cwd=APP
    )
    if run.returncode:
        print(f"json4win exited with {run.returncode} (some documents failed)", file=sys.stderr)
    return run.returncode


def map_case_outputs(case_out: Path, case_pred: Path, label: str) -> None:
    case_pred.mkdir(parents=True, exist_ok=True)
    if not case_out.exists():
        return
    for f in sorted(case_out.glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        name = next((TARGET[k] for k in doc if k in TARGET), None)
        if name is None:
            continue
        if (case_pred / name).exists():
            print(f"{label}: {f.name} is a second {name}; evaluator only scores one, skipped")
            continue
        shutil.copy2(f, case_pred / name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", help="comma-separated case dirs (default: all with ground truth)")
    ap.add_argument("--keep", action="store_true", help="keep and print the temp dir")
    ap.add_argument("-v", "--verbose", action="store_true", help="list every wrong field")
    a = ap.parse_args()

    all_cases = sorted(p.stem for p in (EVAL / "ground_truth").glob("*.yaml"))
    cases = a.cases.split(",") if a.cases else all_cases
    if unknown := sorted(set(cases) - set(all_cases)):
        sys.exit(f"no ground truth for: {', '.join(unknown)}")

    tmp = Path(tempfile.mkdtemp(prefix="json4win-eval-"))
    inp, out, pred, ev = tmp / "input", tmp / "output", tmp / "pred", tmp / "ewaluacja"
    for c in cases:
        (inp / c).mkdir(parents=True)
        for pdf in (DANE / c).glob("*.pdf"):
            shutil.copy2(pdf, inp / c / pdf.name)
    (ev / "ground_truth").mkdir(parents=True)
    shutil.copy2(EVAL / "evaluate.py", ev / "evaluate.py")
    for c in cases:
        shutil.copy2(EVAL / "ground_truth" / f"{c}.yaml", ev / "ground_truth" / f"{c}.yaml")

    run_app(inp, out)

    for c in cases:
        map_case_outputs(out / c, pred / c, c)

    score = subprocess.run(
        [sys.executable, ev / "evaluate.py", "--pred-root", pred] + (["-v"] if a.verbose else [])
    )
    if a.keep:
        print(f"kept: {tmp}")
    else:
        shutil.rmtree(tmp)
    return score.returncode


if __name__ == "__main__":
    sys.exit(main())
