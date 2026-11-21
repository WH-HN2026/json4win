#!/usr/bin/env python3
"""Ocena wyników ekstrakcji względem ground_truth/*.yaml (przybliżenie metryki F1 organizatora).

Użycie:
  python ewaluacja/evaluate.py [--pred-root KATALOG] [-v]

KATALOG zawiera podkatalogi przyklad_NN/ z plikami odwolanie.json, pelnomocnictwo.json,
przelew.json. Domyślnie: dane/ (oczekiwane JSON-y z repo -> test poprawności ewaluatora, ~100%).
files[0]=odwolanie, files[1]=pelnomocnictwo, files[2]=przelew.
Pole oczekiwane null: trafienie, gdy predykcja też null (nie liczy się do TP/FN);
niepusta predykcja przy oczekiwanym null to FP.
"""
import argparse, json, re, sys
from difflib import SequenceMatcher
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FILES = ["odwolanie.json", "pelnomocnictwo.json", "przelew.json"]


def load(p):
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def norm(v):
    return re.sub(r"\s+", " ", str(v)).strip().lower()


def match(exp, got, thr):
    if exp is None or got is None:
        return exp is None and got is None
    if isinstance(exp, (int, float)) and not isinstance(exp, bool):
        try:
            return abs(float(exp) - float(got)) < 1e-6
        except (TypeError, ValueError):
            return False
    return SequenceMatcher(None, norm(exp), norm(got)).ratio() >= thr


def get_obj(doc, name, idx):
    o = doc.get(name)
    if isinstance(o, list):
        return o[idx] if idx < len(o) else None
    return o if idx == 0 else None


def get_field(obj, f):
    if not isinstance(obj, dict):
        return None
    if f in obj:
        return obj[f]
    if isinstance(obj.get("data"), dict):
        return obj["data"].get(f)
    return None


def collect_list(doc, name):
    if name == "pelnomocnicy":
        return doc.get("pelnomocnicy") or []
    if name == "mocodawca_podpisujacy":
        out = []
        for m in doc.get("mocodawca") or []:
            out += m.get("podpisujacy") or []
        return out
    return []


def evaluate_case(gt, case_dir, thr):
    docs = [load(case_dir / f) for f in FILES]
    results = []  # (path, expected, got, ok)
    for path, exp in gt["assert"].items():
        m = re.match(r"files\[(\d)\]\.objects\.(\w+)(?:\[(\d+)\])?(?:\.data\.(\w+))?$", path)
        fi, name, idx, field = m.group(1), m.group(2), m.group(3), m.group(4)
        doc = docs[int(fi)]
        if field is None:  # lista z __contains__
            items = collect_list(doc, name)
            for want in exp["__contains__"]:
                hit = any(all(match(v, it.get(k), thr) for k, v in want.items()) for it in items)
                results.append((f"{path}∋{list(want.values())[0]}", want, None, hit, True))
            continue
        got = get_field(get_obj(doc, name, int(idx or 0)), field)
        results.append((path, exp, got, match(exp, got, thr), exp is not None))
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred-root", default=str(ROOT / "dane"))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    tp = fp = fn = nulls_ok = nulls_bad = 0
    for gtp in sorted((Path(__file__).parent / "ground_truth").glob("*.yaml")):
        gt = yaml.safe_load(gtp.read_text(encoding="utf-8"))
        thr = gt.get("min_similarity", 0.55)
        for path, exp, got, ok, has_val in evaluate_case(gt, Path(a.pred_root) / gtp.stem, thr):
            if has_val:
                if ok:
                    tp += 1
                else:
                    fn += 1
                    if got is not None:
                        fp += 1
            else:
                nulls_ok, nulls_bad = nulls_ok + ok, nulls_bad + (not ok)
                fp += not ok
            if a.verbose and not ok:
                print(f"{gtp.stem} {path}\n   oczekiwano: {exp!r}\n   otrzymano:  {got!r}")
    p = tp / (tp + fp) if tp + fp else 0
    r = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * p * r / (p + r) if p + r else 0
    print(f"TP={tp} FP={fp} FN={fn} | null ok={nulls_ok} zle={nulls_bad}")
    print(f"precision={p:.3f} recall={r:.3f} F1={f1:.3f}")


if __name__ == "__main__":
    sys.exit(main())
