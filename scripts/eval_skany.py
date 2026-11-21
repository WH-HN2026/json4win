#!/usr/bin/env python3
"""Run json4win on real scans in dane/skany/ and score with a copy of ewaluacja/evaluate.py.

Usage:
  scripts/eval_skany.py [--kinds odwolania,potwierdzenia] [--ids 0001,0002]
                        [--cases odwolania_0001,potwierdzenia_0002] [--keep] [-v]
  scripts/eval_skany.py --self-test [-v]

1. Copies each selected scan PDF into a temp input/<kind>_<id>/<id>.pdf directory.
2. Runs `python -m json4win --input ... --output ...`.
3. Maps each output JSON by top-level key to odwolanie/pelnomocnictwo/przelew.json,
   converts each scan's ground-truth JSON into the evaluator's YAML format, and runs a
   copy of ewaluacja/evaluate.py per kind and for the total.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_training import DANE, EVAL, map_case_outputs, run_app  # noqa: E402

SKANY = DANE / "skany"
KINDS = ("odwolania", "pelnomocnictwa", "potwierdzenia")

ODWOLANIE_KIO_FIELDS = (
    "miejscowosc",
    "data",
    "czynnosc_dzien",
    "czynnosc_opis",
    "czynnosc_powod_id",
)
PODMIOT_FIELDS = ("nazwa", "nip", "regon", "krs")
ZAMOWIENIE_FIELDS = ("numer_postepowania", "tytul", "numer_bzp", "numer_ted")
MOCODAWCA_FIELDS = ("typ", "nazwa", "nip", "krs")
PRZELEW_FIELDS = (
    "data_operacji",
    "kwota",
    "z_rachunku",
    "na_rachunek",
    "tytul",
    "numer_transakcji",
)

SCORE_RE = re.compile(
    r"TP=(\d+) FP=(\d+) FN=(\d+) \| null ok=(\d+) zle=(\d+)\s+"
    r"precision=([0-9.]+) recall=([0-9.]+) F1=([0-9.]+)"
)


@dataclass(frozen=True)
class ScanCase:
    kind: str
    scan_id: str
    pdf: Path
    gt_json: Path

    @property
    def name(self) -> str:
        return f"{self.kind}_{self.scan_id}"


def odwolanie_assertions(doc: dict) -> dict:
    asserts: dict = {}
    okio = doc.get("OdwolanieKIO") or {}
    for field in ODWOLANIE_KIO_FIELDS:
        asserts[f"files[0].objects.OdwolanieKIO[0].data.{field}"] = okio.get(field)
    for i, item in enumerate(doc.get("Odwolujacy") or []):
        for field in PODMIOT_FIELDS:
            asserts[f"files[0].objects.Odwolujacy[{i}].data.{field}"] = item.get(field)
    for i, item in enumerate(doc.get("Zamawiajacy") or []):
        for field in PODMIOT_FIELDS:
            asserts[f"files[0].objects.Zamawiajacy[{i}].data.{field}"] = item.get(field)
    zp = doc.get("ZamowieniePubliczne") or {}
    for field in ZAMOWIENIE_FIELDS:
        asserts[f"files[0].objects.ZamowieniePubliczne[0].data.{field}"] = zp.get(field)
    return asserts


def pelnomocnictwo_assertions(doc: dict) -> dict:
    asserts: dict = {}
    for i, moc in enumerate(doc.get("mocodawca") or []):
        md = moc.get("data") or {}
        for field in MOCODAWCA_FIELDS:
            asserts[f"files[1].objects.mocodawca[{i}].data.{field}"] = md.get(field)
        if md.get("imie_nazwisko") is not None:
            asserts[f"files[1].objects.mocodawca[{i}].data.imie_nazwisko"] = md["imie_nazwisko"]
    pels = []
    for item in doc.get("pelnomocnicy") or []:
        if item.get("imie_nazwisko") is None:
            continue
        want = {"imie_nazwisko": item["imie_nazwisko"]}
        if item.get("pesel") is not None:
            want["pesel"] = item["pesel"]
        pels.append(want)
    if pels:
        asserts["files[1].objects.pelnomocnicy"] = {
            "__contains__": pels,
            "__min_count__": len(pels),
        }
    pods = [
        {"imie_nazwisko": pod["imie_nazwisko"]}
        for moc in (doc.get("mocodawca") or [])
        for pod in (moc.get("podpisujacy") or [])
        if pod.get("imie_nazwisko") is not None
    ]
    if pods:
        asserts["files[1].objects.mocodawca_podpisujacy"] = {
            "__contains__": pods,
            "__min_count__": len(pods),
        }
    return asserts


def przelew_assertions(doc: dict) -> dict:
    asserts: dict = {}
    pb = doc.get("przelew_bankowy") or {}
    for field in PRZELEW_FIELDS:
        asserts[f"files[2].objects.przelew_bankowy[0].data.{field}"] = pb.get(field)
    return asserts


def build_gt(
    *,
    odwolanie: dict | None = None,
    pelnomocnictwo: dict | None = None,
    przelew: dict | None = None,
    min_similarity: float = 0.55,
) -> dict:
    """Convert canonical JSON document(s) into ewaluacja/evaluate.py YAML ground-truth structure."""
    asserts: dict = {}
    if odwolanie is not None:
        asserts.update(odwolanie_assertions(odwolanie))
    if pelnomocnictwo is not None:
        asserts.update(pelnomocnictwo_assertions(pelnomocnictwo))
    if przelew is not None:
        asserts.update(przelew_assertions(przelew))
    return {"assert": asserts, "min_similarity": min_similarity, "version": "2"}


def build_scan_gt(case: ScanCase) -> dict:
    doc = json.loads(case.gt_json.read_text(encoding="utf-8"))
    if case.kind == "odwolania":
        return build_gt(odwolanie=doc)
    if case.kind == "pelnomocnictwa":
        return build_gt(pelnomocnictwo=doc)
    if case.kind == "potwierdzenia":
        return build_gt(przelew=doc)
    raise ValueError(f"unknown scan kind: {case.kind}")


def count_assertions(gt: dict) -> int:
    total = 0
    for val in gt["assert"].values():
        if isinstance(val, dict) and "__contains__" in val:
            total += len(val["__contains__"])
        else:
            total += 1
    return total


def discover_scans() -> list[ScanCase]:
    scans: list[ScanCase] = []
    for kind in KINDS:
        kind_dir = SKANY / kind
        if not kind_dir.is_dir():
            continue
        for item_dir in sorted(p for p in kind_dir.iterdir() if p.is_dir()):
            scan_id = item_dir.name
            pdf = item_dir / f"{scan_id}.pdf"
            gt_json = item_dir / f"{scan_id}.json"
            if pdf.is_file() and gt_json.is_file():
                scans.append(ScanCase(kind=kind, scan_id=scan_id, pdf=pdf, gt_json=gt_json))
    return scans


def select_scans(
    all_scans: list[ScanCase],
    *,
    kinds_arg: str | None,
    ids_arg: str | None,
    cases_arg: str | None,
) -> list[ScanCase]:
    selected = list(all_scans)
    if kinds_arg:
        kinds = [k.strip() for k in kinds_arg.split(",") if k.strip()]
        if unknown := sorted(set(kinds) - set(KINDS)):
            sys.exit(f"unknown kinds: {', '.join(unknown)} (valid: {', '.join(KINDS)})")
        selected = [s for s in selected if s.kind in kinds]
    if ids_arg:
        ids = [i.strip() for i in ids_arg.split(",") if i.strip()]
        known_ids = {s.scan_id for s in selected}
        if unknown := sorted(set(ids) - known_ids):
            sys.exit(f"unknown scan ids: {', '.join(unknown)}")
        selected = [s for s in selected if s.scan_id in ids]
    if cases_arg:
        tokens = [t.strip() for t in cases_arg.split(",") if t.strip()]
        by_name = {s.name: s for s in selected}
        matched: list[ScanCase] = []
        seen: set[str] = set()
        unknown_tokens: list[str] = []
        for tok in tokens:
            norm = tok.replace("/", "_")
            if norm in by_name:
                hits = [by_name[norm]]
            elif tok in KINDS:
                hits = [s for s in selected if s.kind == tok]
            else:
                hits = [s for s in selected if s.scan_id == tok]
            if not hits:
                unknown_tokens.append(tok)
                continue
            for h in hits:
                if h.name not in seen:
                    seen.add(h.name)
                    matched.append(h)
        if unknown_tokens:
            sys.exit(f"no matching scan cases for: {', '.join(unknown_tokens)}")
        selected = matched
    if not selected:
        sys.exit("no scan cases selected")
    return selected


def run_evaluate_copy(
    ev_dir: Path,
    gt_map: dict[str, dict],
    pred_root: Path,
    *,
    verbose: bool = False,
) -> tuple[int, str]:
    gt_dir = ev_dir / "ground_truth"
    gt_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EVAL / "evaluate.py", ev_dir / "evaluate.py")
    for case_name, gt_data in gt_map.items():
        (gt_dir / f"{case_name}.yaml").write_text(
            yaml.safe_dump(gt_data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    cmd = [sys.executable, str(ev_dir / "evaluate.py"), "--pred-root", str(pred_root)]
    if verbose:
        cmd.append("-v")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    output = proc.stdout
    if proc.stderr:
        output += proc.stderr
    return proc.returncode, output


def parse_score(output: str) -> dict[str, float | int]:
    m = SCORE_RE.search(output)
    if not m:
        raise ValueError(f"could not parse evaluate.py output:\n{output}")
    return {
        "tp": int(m.group(1)),
        "fp": int(m.group(2)),
        "fn": int(m.group(3)),
        "nulls_ok": int(m.group(4)),
        "nulls_bad": int(m.group(5)),
        "precision": float(m.group(6)),
        "recall": float(m.group(7)),
        "f1": float(m.group(8)),
    }


def score_scans(
    scans: list[ScanCase],
    pred_root: Path,
    ev_base: Path,
    *,
    verbose: bool,
) -> tuple[int, dict[str, dict[str, float | int]]]:
    gt_by_name = {s.name: build_scan_gt(s) for s in scans}
    scores: dict[str, dict[str, float | int]] = {}
    rc = 0
    kinds_present = [k for k in KINDS if any(s.kind == k for s in scans)]
    for kind in kinds_present:
        kind_scans = [s for s in scans if s.kind == kind]
        kind_gt = {s.name: gt_by_name[s.name] for s in kind_scans}
        k_rc, out = run_evaluate_copy(ev_base / kind, kind_gt, pred_root, verbose=verbose)
        print(f"=== {kind} ({len(kind_scans)}) ===")
        print(out, end="")
        if k_rc:
            rc = k_rc
        else:
            scores[kind] = parse_score(out)

    t_rc, total_out = run_evaluate_copy(ev_base / "total", gt_by_name, pred_root, verbose=False)
    print(f"=== TOTAL ({len(scans)}) ===")
    print(total_out, end="")
    if t_rc:
        rc = t_rc
    else:
        scores["TOTAL"] = parse_score(total_out)
    return rc, scores


def run_self_test(scans: list[ScanCase], *, keep: bool, verbose: bool) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="json4win-eval-skany-selftest-"))
    try:
        raw_scans, pred_scans = tmp / "raw_scans", tmp / "pred_scans"
        for s in scans:
            case_raw = raw_scans / s.name
            case_raw.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s.gt_json, case_raw / s.gt_json.name)
            map_case_outputs(case_raw, pred_scans / s.name, s.name)

        print("## Self-test 1: dane/skany ground-truth JSONs vs converted YAMLs")
        rc, scan_scores = score_scans(scans, pred_scans, tmp / "ev_scans", verbose=verbose)
        failed = rc != 0
        for label, sc in scan_scores.items():
            if sc["fp"] != 0 or sc["fn"] != 0 or sc["nulls_bad"] != 0 or sc["f1"] != 1.0:
                print(f"FAIL: skany {label} expected F1=1.000 FP=0 FN=0, got {sc}", file=sys.stderr)
                failed = True

        print("\n## Self-test 2: przyklad_01..39 converted YAMLs vs official YAMLs")
        official_paths = sorted((EVAL / "ground_truth").glob("*.yaml"))
        gen_gt_map: dict[str, dict] = {}
        off_gt_map: dict[str, dict] = {}
        gen_total_assertions = 0
        off_total_assertions = 0
        for off_path in official_paths:
            case = off_path.stem
            off_gt = yaml.safe_load(off_path.read_text(encoding="utf-8"))
            odw = json.loads((DANE / case / "odwolanie.json").read_text(encoding="utf-8"))
            pel = json.loads((DANE / case / "pelnomocnictwo.json").read_text(encoding="utf-8"))
            prz = json.loads((DANE / case / "przelew.json").read_text(encoding="utf-8"))
            gen_gt = build_gt(odwolanie=odw, pelnomocnictwo=pel, przelew=prz)

            off_keys, gen_keys = set(off_gt["assert"]), set(gen_gt["assert"])
            if off_keys != gen_keys:
                print(
                    f"FAIL: {case} assert keys differ: "
                    f"missing={sorted(off_keys - gen_keys)} extra={sorted(gen_keys - off_keys)}",
                    file=sys.stderr,
                )
                failed = True
            off_cnt, gen_cnt = count_assertions(off_gt), count_assertions(gen_gt)
            if off_cnt != gen_cnt:
                print(
                    f"FAIL: {case} assertion count {gen_cnt} != official {off_cnt}",
                    file=sys.stderr,
                )
                failed = True
            off_total_assertions += off_cnt
            gen_total_assertions += gen_cnt
            off_gt_map[case] = off_gt
            gen_gt_map[case] = gen_gt

        gen_rc, gen_out = run_evaluate_copy(
            tmp / "ev_przyklad_gen", gen_gt_map, DANE, verbose=verbose
        )
        off_rc, off_out = run_evaluate_copy(
            tmp / "ev_przyklad_off", off_gt_map, DANE, verbose=verbose
        )
        print(
            f"cases={len(official_paths)} assertions: "
            f"converted={gen_total_assertions} official={off_total_assertions}"
        )
        print(f"[converted] {gen_out.strip().replace(chr(10), ' | ')}")
        print(f"[official ] {off_out.strip().replace(chr(10), ' | ')}")

        if gen_rc or off_rc:
            failed = True
        else:
            gen_sc, off_sc = parse_score(gen_out), parse_score(off_out)
            if gen_sc != off_sc or gen_sc["f1"] != 1.0 or gen_sc["fp"] != 0 or gen_sc["fn"] != 0:
                print(
                    f"FAIL: przyklad cross-check mismatch: converted={gen_sc} official={off_sc}",
                    file=sys.stderr,
                )
                failed = True
            else:
                print("SELF-TEST PASSED")

        return 1 if failed else 0
    finally:
        if keep:
            print(f"kept: {tmp}")
        else:
            shutil.rmtree(tmp)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--kinds", help="comma-separated scan kinds (odwolania,pelnomocnictwa,potwierdzenia)"
    )
    ap.add_argument("--ids", help="comma-separated scan IDs (e.g. 0001,0002)")
    ap.add_argument(
        "--cases", help="comma-separated scan cases (e.g. odwolania_0001,potwierdzenia_0002)"
    )
    ap.add_argument(
        "--self-test", action="store_true", help="verify GT conversion on scans and przyklad_01..39"
    )
    ap.add_argument("--keep", action="store_true", help="keep and print the temp dir")
    ap.add_argument("-v", "--verbose", action="store_true", help="list every wrong field")
    a = ap.parse_args()

    all_scans = discover_scans()
    scans = select_scans(all_scans, kinds_arg=a.kinds, ids_arg=a.ids, cases_arg=a.cases)

    if a.self_test:
        return run_self_test(scans, keep=a.keep, verbose=a.verbose)

    tmp = Path(tempfile.mkdtemp(prefix="json4win-eval-skany-"))
    try:
        inp, out, pred = tmp / "input", tmp / "output", tmp / "pred"
        for s in scans:
            case_in = inp / s.name
            case_in.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s.pdf, case_in / s.pdf.name)

        run_app(inp, out)

        for s in scans:
            map_case_outputs(out / s.name, pred / s.name, s.name)

        rc, _ = score_scans(scans, pred, tmp / "ewaluacja", verbose=a.verbose)
        return rc
    finally:
        if a.keep:
            print(f"kept: {tmp}")
        else:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    sys.exit(main())
