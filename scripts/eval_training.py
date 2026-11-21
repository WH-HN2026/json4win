#!/usr/bin/env python3
"""Run json4win on the training cases in dane/ and score it with ewaluacja/evaluate.py.

Usage:
  scripts/eval_training.py [--cases przyklad_01,przyklad_02] [--ideal-ocr] [--jobs 4]
                           [--negatives] [--negatives-only] [--keep] [-v]

1. Copies only the PDFs of dane/<case>/ to a temp input/ tree (the expected JSONs stay behind).
2. Runs `python -m json4win --input ... --output ...` (or, with --ideal-ocr, runs json4win.cli.run
   in-process with a dev-only PDF text-layer monkeypatch over json4win.ocr).
3. Maps each output JSON to odwolanie/pelnomocnictwo/przelew.json by its top-level key (our output
   is named after the input PDF, the evaluator wants fixed names), then runs a copy of
   ewaluacja/evaluate.py restricted to the selected cases. The scoring code is not modified.
4. With --negatives, also checks dane/negatywne/*.pdf and extra PDFs inside dane/przyklad_*/ and
   lists any document that produced a non-empty JSON (false positive).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ideal_ocr import BANNER as IDEAL_OCR_BANNER  # noqa: E402
from ideal_ocr import run_app_ideal_ocr  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DANE, EVAL, APP = ROOT / "dane", ROOT / "ewaluacja", ROOT / "json4win"
TARGET = {
    "OdwolanieKIO": "odwolanie.json",
    "mocodawca": "pelnomocnictwo.json",
    "pelnomocnicy": "pelnomocnictwo.json",
    "przelew_bankowy": "przelew.json",
}
EXPECTED_CASE_PDFS = frozenset(
    {
        "odwolanie.pdf",
        "pelnomocnictwo.pdf",
        "przelew.pdf",
        "potwierdzenie_przelewu.pdf",
    }
)
CLASS_PREFIXES = (
    ("odwolanie", "files[0]."),
    ("pelnomocnictwo", "files[1]."),
    ("przelew", "files[2]."),
)


def run_app(inp: Path, out: Path, *, trace_dir: Path | None = None) -> int:
    cmd = [sys.executable, "-m", "json4win", "--input", str(inp), "--output", str(out)]
    if trace_dir is not None:
        cmd += ["--trace", str(trace_dir)]
    run = subprocess.run(cmd, cwd=APP)
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


def discover_negatives() -> list[tuple[str, Path]]:
    """Return sorted (relative_label, pdf_path) for every PDF that must produce {}."""
    items: list[tuple[str, Path]] = []
    neg_dir = DANE / "negatywne"
    if neg_dir.is_dir():
        for pdf in sorted(neg_dir.iterdir()):
            if pdf.is_file() and pdf.suffix.lower() == ".pdf":
                items.append((f"negatywne/{pdf.name}", pdf))
    for case_dir in sorted(p for p in DANE.glob("przyklad_*") if p.is_dir()):
        for pdf in sorted(case_dir.iterdir()):
            if (
                pdf.is_file()
                and pdf.suffix.lower() == ".pdf"
                and pdf.name not in EXPECTED_CASE_PDFS
            ):
                items.append((f"{case_dir.name}/{pdf.name}", pdf))
    return sorted(items, key=lambda pair: pair[0])


def print_per_class_summary(ev: Path, pred: Path, cases: list[str]) -> None:
    """Run the unmodified evaluator per class (files[0]/files[1]/files[2]) for TP/FP/FN totals."""
    print("Per-class summary:")
    for class_name, prefix in CLASS_PREFIXES:
        class_ev = ev / "_by_class" / class_name
        gt_dir = class_ev / "ground_truth"
        gt_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(EVAL / "evaluate.py", class_ev / "evaluate.py")
        has_any = False
        for c in cases:
            raw = yaml.safe_load((EVAL / "ground_truth" / f"{c}.yaml").read_text(encoding="utf-8"))
            filtered = {k: v for k, v in raw["assert"].items() if k.startswith(prefix)}
            if not filtered:
                continue
            has_any = True
            subset = {**raw, "assert": filtered}
            (gt_dir / f"{c}.yaml").write_text(
                yaml.safe_dump(subset, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        if not has_any:
            continue
        proc = subprocess.run(
            [sys.executable, class_ev / "evaluate.py", "--pred-root", pred],
            capture_output=True,
            text=True,
        )
        summary = " | ".join(line.strip() for line in proc.stdout.splitlines() if line.strip())
        print(f"  {class_name:<15} {summary}")


def report_negatives(neg_outputs: list[tuple[str, Path]]) -> int:
    """Inspect negative outputs in sorted order and print any false positives."""
    fps: list[tuple[str, list[str]]] = []
    missing: list[str] = []
    for label, out_json in sorted(neg_outputs, key=lambda pair: pair[0]):
        if not out_json.is_file():
            missing.append(label)
            continue
        doc = json.loads(out_json.read_text(encoding="utf-8"))
        if doc:
            keys = sorted(doc.keys()) if isinstance(doc, dict) else [type(doc).__name__]
            fps.append((label, keys))

    total = len(neg_outputs)
    ok = total - len(fps) - len(missing)
    print(f"Negatives: {ok}/{total} empty {{}}, {len(fps)} false positive(s)")
    for label, keys in fps:
        print(f"  FP: {label} -> keys={keys}")
    for label in missing:
        print(f"  MISSING: {label}")
    return len(fps) + len(missing)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", help="comma-separated case dirs (default: all with ground truth)")
    ap.add_argument(
        "--ideal-ocr",
        action="store_true",
        help="dev-only: replace OCR with PDF text layer (pdftotext -layout) in-process",
    )
    ap.add_argument(
        "--jobs",
        type=int,
        default=4,
        help="parallel worker threads for --ideal-ocr (default: 4)",
    )
    ap.add_argument(
        "--negatives",
        action="store_true",
        help="also verify dane/negatywne/*.pdf and extra PDFs in dane/przyklad_*/ produce {}",
    )
    ap.add_argument(
        "--negatives-only",
        action="store_true",
        help="run only the negative PDF check (skip case F1 scoring)",
    )
    ap.add_argument("--keep", action="store_true", help="keep and print the temp dir")
    ap.add_argument("-v", "--verbose", action="store_true", help="list every wrong field")
    a = ap.parse_args()

    if a.jobs < 1:
        sys.exit(f"--jobs must be >= 1, got {a.jobs}")

    all_cases = sorted(p.stem for p in (EVAL / "ground_truth").glob("*.yaml"))
    if a.negatives_only:
        cases: list[str] = []
    else:
        cases = a.cases.split(",") if a.cases else all_cases
        if unknown := sorted(set(cases) - set(all_cases)):
            sys.exit(f"no ground truth for: {', '.join(unknown)}")

    check_negatives = a.negatives or a.negatives_only

    if a.ideal_ocr:
        print(f"=== {IDEAL_OCR_BANNER} ===", flush=True)

    tmp = Path(tempfile.mkdtemp(prefix="json4win-eval-"))
    try:
        inp, out, pred, ev, traces = (
            tmp / "input",
            tmp / "output",
            tmp / "pred",
            tmp / "ewaluacja",
            tmp / "traces",
        )
        inp.mkdir(parents=True)
        selected_set = set(cases)
        for c in cases:
            (inp / c).mkdir(parents=True)
            for pdf in sorted((DANE / c).glob("*.pdf")):
                shutil.copy2(pdf, inp / c / pdf.name)

        neg_outputs: list[tuple[str, Path]] = []
        if check_negatives:
            for label, src_pdf in discover_negatives():
                case_name, pdf_name = label.split("/", 1)
                if case_name in selected_set:
                    # Already copied as part of the selected case; reuse its output JSON.
                    out_json = out / case_name / Path(pdf_name).with_suffix(".json")
                else:
                    dest_pdf = inp / "_negatives" / case_name / pdf_name
                    dest_pdf.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_pdf, dest_pdf)
                    out_json = out / "_negatives" / case_name / Path(pdf_name).with_suffix(".json")
                neg_outputs.append((label, out_json))

        if a.ideal_ocr:
            run_app_ideal_ocr(inp, out, jobs=a.jobs, trace_dir=traces)
        else:
            run_app(inp, out, trace_dir=traces)

        rc = 0
        if cases:
            (ev / "ground_truth").mkdir(parents=True)
            shutil.copy2(EVAL / "evaluate.py", ev / "evaluate.py")
            for c in cases:
                shutil.copy2(EVAL / "ground_truth" / f"{c}.yaml", ev / "ground_truth" / f"{c}.yaml")
            for c in cases:
                map_case_outputs(out / c, pred / c, c)

            score = subprocess.run(
                [sys.executable, ev / "evaluate.py", "--pred-root", pred]
                + (["-v"] if a.verbose else [])
            )
            rc = score.returncode
            print_per_class_summary(ev, pred, cases)

        if check_negatives:
            report_negatives(neg_outputs)

        return rc
    finally:
        if a.keep:
            print(f"kept: {tmp} (traces: {traces})")
        else:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    sys.exit(main())
