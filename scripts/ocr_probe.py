#!/usr/bin/env python3
"""OCR gate measurements (dev tool, task P1; results in docs/ocr.md). The runtime never reads dane/.

  scripts/ocr_probe.py bench [--dtype D] [--mode M] [--max-tokens N] [--save DIR] PDF:PAGE ...
      Runs the model directly (no cache) on the given pages (PAGE is 1-based) and prints, per page,
      seconds, tokens and peak RSS (Linux VmHWM, reset before each page), and the cold load time.
      Run it under jury-like limits, e.g.
        OCR_THREADS=8 ATEN_CPU_CAPABILITY=avx2 ONEDNN_MAX_CPU_ISA=AVX2 \\
        MKL_ENABLE_INSTRUCTIONS=AVX2 systemd-run --user --scope -p MemoryMax=12G \\
        -p MemorySwapMax=0 .venv/bin/python scripts/ocr_probe.py bench ...

  scripts/ocr_probe.py quality [--pages 3] [-v]
      For the scans in dane/skany/<kind>/<NNNN>/ (ground truth in <NNNN>.json): OCR the first pages
      through json4win.ocr (cached; fill it first: scripts/ocr_cache.py --pages 3 --paths ...) and
      report, per field, the share of non-null ground-truth values found verbatim in the text
      (case- and whitespace-insensitive). Identifiers are also matched with separators (-./)
      removed; dates and amounts are matched against common written forms, reported separately.
"""

import argparse
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "json4win"))

from json4win import env, ocr, ocr_engine  # noqa: E402

IDS = {"nip", "regon", "krs", "pesel", "na_rachunek", "z_rachunku", "numer_transakcji"}
IDS_REF = {"numer_bzp", "numer_ted", "numer_postepowania"}
NAMES = {"nazwa", "imie_nazwisko", "miejscowosc", "prowadzacy_postepowanie"}
GROUPS = (("id", IDS), ("ref", IDS_REF), ("name", NAMES))
MONTHS = (
    "stycznia lutego marca kwietnia maja czerwca lipca sierpnia"
    " września października listopada grudnia"
).split()


# ---- bench -------------------------------------------------------------------------------------


def _hwm_gb() -> float | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1e6
    except OSError:
        return None
    return None


def _reset_hwm() -> None:
    try:
        Path("/proc/self/clear_refs").write_text("5")
    except OSError:
        pass


def bench(a) -> int:
    import torch

    s = ocr_engine.InferSettings(
        mode=a.mode, max_tokens=a.max_tokens, dtype=a.dtype, fast_decode=a.fast_decode
    )
    print(
        f"torch {torch.__version__}, cpu capability {torch.backends.cpu.get_cpu_capability()}, "
        f"settings {s}"
    )
    t0 = time.time()
    ocr_engine.load(s.dtype)
    load_s, threads = time.time() - t0, torch.get_num_threads()
    print(f"LOAD {load_s:.1f}s, peak RSS {_hwm_gb():.2f} GB, threads {threads}")
    rows = []
    for item in a.items:
        pdf, _, page = item.rpartition(":")
        image = ocr.render_page(Path(pdf), int(page) - 1)
        _reset_hwm()
        r = ocr_engine.run(image, s)
        hwm = _hwm_gb()
        dec = r["tokens"] / max(r["seconds"] - r["prefill_seconds"], 1e-6)
        rows.append((item, r["seconds"], hwm))
        print(
            f"PAGE {item}: {r['seconds']:.1f}s (prefill {r['prefill_seconds']:.1f}s, "
            f"{r['tokens']} tok, {dec:.1f} tok/s, {r['finish']}), "
            f"prompt {r['prompt_tokens']} tok, peak RSS {hwm:.2f} GB",
            flush=True,
        )
        if a.save:
            out = Path(a.save)
            out.mkdir(parents=True, exist_ok=True)
            q = Path(pdf)
            name = re.sub(
                r"[^\w.-]+", "_", f"{q.parent.parent.name}_{q.parent.name}_{q.stem}_p{page}"
            )
            (out / f"{name}.raw.txt").write_text(r["raw"], encoding="utf-8")
            (out / f"{name}.txt").write_text(ocr.clean_text(r["raw"]), encoding="utf-8")
    secs = [r[1] for r in rows]
    print(
        f"SUMMARY {len(rows)} pages: mean {sum(secs) / len(secs):.1f}s, max {max(secs):.1f}s, "
        f"peak RSS max {max(r[2] for r in rows):.2f} GB"
    )
    return 0


# ---- quality -----------------------------------------------------------------------------------


def _leaves(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _leaves(v, f"{path}[]")
    else:
        yield path, obj


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def _nosep(s: str) -> str:
    return re.sub(r"[\s\-./]+", "", s).lower()


def _ascii(s: str) -> str:
    s = s.replace("ł", "l").replace("Ł", "L")
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _date_forms(v: str) -> list[str]:
    y, m, d = v.split("-")
    return [
        v,
        f"{d}.{m}.{y}",
        f"{int(d)}.{m}.{y}",
        f"{d}-{m}-{y}",
        f"{d}/{m}/{y}",
        f"{int(d)} {MONTHS[int(m) - 1]} {y}",
        f"{d} {MONTHS[int(m) - 1]} {y}",
    ]


def _amount_forms(v: float) -> list[str]:
    whole, frac = f"{v:.2f}".split(".")
    grouped = f"{int(whole):,}".replace(",", " ")
    return [
        f"{whole},{frac}",
        f"{grouped},{frac}",
        f"{whole}.{frac}",
        f"{grouped.replace(' ', '.')},{frac}",
        f"{int(whole):,}.{frac}",
    ]


def quality(a) -> int:
    env.load_env()
    stats = defaultdict(lambda: [0, 0, 0])  # field -> [found strict, found loose, total]
    misses = []
    for gt_file in sorted((ROOT / "dane" / "skany").glob("*/*/*.json")):
        pdf = gt_file.with_suffix(".pdf")
        n = min(a.pages, ocr.page_count(pdf))
        try:
            text = "\n".join(ocr.ocr_page(pdf, i) for i in range(n))
        except ocr.OcrCacheMiss as e:
            print(f"skip {pdf.relative_to(ROOT)}: {e}", file=sys.stderr)
            continue
        kind = gt_file.parent.parent.name
        gt = json.loads(gt_file.read_text(encoding="utf-8"))
        nt, ns, na = _norm(text), _nosep(text), _norm(_ascii(text))
        for path, v in _leaves(gt):
            key = path.rsplit(".", 1)[-1]
            if v is None or isinstance(v, bool) or (isinstance(v, int) and key != "kwota"):
                continue
            if key == "typ":  # enum (osoba_prawna / osoba_fizyczna), not text on the page
                continue
            field = f"{kind}:{path}"
            if isinstance(v, float) or key == "kwota":
                forms, group = _amount_forms(float(v)), "amount"
            elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v)):
                forms, group = _date_forms(v), "date"
            else:
                forms = [str(v)]
                group = next((g for g, keys in GROUPS if key in keys), "text")
            strict = any(_norm(f) in nt for f in forms)
            loose = strict or (group in ("id", "ref") and _nosep(str(v)) in ns)
            loose = loose or (group == "name" and _norm(_ascii(str(v))) in na)
            st = stats[(group, field)]
            st[0] += strict
            st[1] += loose
            st[2] += 1
            if not strict:
                doc = gt_file.parent.relative_to(ROOT / "dane" / "skany")
                misses.append((group, str(doc), path, v, loose))

    print(f"{'group':6} {'field':55} {'verbatim':>9} {'loose':>9}")
    totals = defaultdict(lambda: [0, 0, 0])
    for (group, field), (s, lo, t) in sorted(stats.items()):
        print(f"{group:6} {field:55} {s:>4}/{t:<4} {lo:>4}/{t:<4}")
        for g in (group, "gate" if group in ("id", "name") else None):
            if g:
                totals[g] = [x + y for x, y in zip(totals[g], (s, lo, t), strict=True)]
    print()
    for g, (s, lo, t) in sorted(totals.items()):
        print(f"TOTAL {g:6} verbatim {s}/{t} = {s / t:.1%}   loose {lo}/{t} = {lo / t:.1%}")
    print("(loose: ids/refs with separators removed, names with diacritics removed)")
    if a.verbose:
        print("\nmisses (verbatim):")
        for group, doc, path, v, loose in misses:
            print(f"  {group:6} {doc:22} {path:45} {v!r}{'  [loose ok]' if loose else ''}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bench")
    d = ocr_engine.InferSettings()
    b.add_argument("--dtype", default=d.dtype, choices=ocr_engine.DTYPES)
    b.add_argument("--mode", default=d.mode, choices=("gundam", "base"))
    b.add_argument("--max-tokens", type=int, default=d.max_tokens)
    b.add_argument("--fast-decode", type=int, default=d.fast_decode, choices=(0, 1, 2))
    b.add_argument("--save", help="write raw and cleaned text of each page here")
    b.add_argument("items", nargs="+", metavar="PDF:PAGE")
    q = sub.add_parser("quality")
    q.add_argument("--pages", type=int, default=3)
    q.add_argument("-v", "--verbose", action="store_true", help="list the misses")
    a = ap.parse_args()
    return bench(a) if a.cmd == "bench" else quality(a)


if __name__ == "__main__":
    sys.exit(main())
