# OCR engine: Unlimited-OCR-2 on CPU (task P1)

Code: [`json4win/json4win/ocr.py`](../json4win/json4win/ocr.py) (contract, rendering, cache, text cleaning),
[`ocr_engine.py`](../json4win/json4win/ocr_engine.py) (model load + inference),
[`ocr_fast.py`](../json4win/json4win/ocr_fast.py) (opt-in faster decode). Dev tools:
[`scripts/ocr_cache.py`](../scripts/ocr_cache.py) (`make ocr-cache`), [`scripts/ocr_probe.py`](../scripts/ocr_probe.py) (gate bench + quality probe).

## How it works

- **Model:** `baidu/Unlimited-OCR-2`, pinned revision `cb16b920ec2249c4b280f3aa67942e00b5099122` (2026-11-16),
  MIT, ~6.7 GB of bf16 safetensors downloaded by `transformers`/`huggingface_hub` on first use into the HF cache
  (`~/.cache/huggingface/hub`, `HF_HOME` overrides). Loaded lazily, once per process.
- **Rendering:** pypdfium2 (pip wheel, Windows/Linux), 200 dpi RGB. The model resizes to a 1024 px global view +
  640 px tiles (gundam mode: 2×3 tiles for A4, 903 image tokens), so more dpi buys nothing.
- **Inference:** the model's own `infer()` with the only documented prompt (`Multi page parsing.`), one page per
  call, greedy, no-repeat-ngram 35 / window 128 (model card values), max 3000 output tokens per page
  (dense A4 ≈ 1300–1600).
- **CPU patches (no fork of the remote code):** (1) transformers' import check refuses the remote code because one
  file imports `triton`; `triton` is filtered out of that check (the code uses it only on CUDA tensors);
  (2) `Tensor.cuda` becomes a no-op when CUDA is absent (the vision merge calls `.cuda()` on a mask);
  (3) the model's debug `print()`s are swallowed.
- **dtype:** vision encoder (SAM + CLIP) in **fp32**, decoder in **bf16** (`OCR_DTYPE=mixed`, default). bf16
  convolutions are ~5× slower on CPUs without AVX512-BF16 (prefill 52 s → 9 s); fp32 for everything needs ~14 GB.
- **Output → text:** the model emits layout markup (`<BLOCK>text[x1, y1, x2, y2]<FORK>…`, markdown links, `**`).
  The **raw** output is cached and cleaned on read by `clean_text()` (one block per line, link labels kept,
  e.g. `[DA.ZP.242.50.2026](mailto:…)` → `DA.ZP.242.50.2026`), so a cleaner change never needs a re-OCR.
- **Cache:** `json4win.env.cache_dir()/ocr/<settings id>/<sha256 of PDF>/<page>.json`, written atomically.
  The settings id hashes model, revision, prompt, dpi, mode, max tokens, n-gram, dtype, fast-decode level and a
  format version (`settings.json` in each settings dir lists them). Changing any `OCR_*` setting below starts a
  new, empty cache. `OCR_CACHE_ONLY=1` → `OcrCacheMiss` on a miss.
- **Env:** `OCR_THREADS` (default: torch's default = physical cores), `OCR_MODE` (`gundam`|`base`),
  `OCR_MAX_TOKENS`, `OCR_DTYPE` (`mixed`|`bf16`|`mixed-int8head`), `OCR_FAST_DECODE` (`0`|`1`|`2`), `OCR_CACHE_ONLY`.
- **Install:** `json4win/requirements.txt` pins torch `2.13.0+cpu` from `--extra-index-url
  https://download.pytorch.org/whl/cpu` (no CUDA on Linux). The index has both wheels for Python 3.13:
  `torch-2.13.0+cpu-cp313-cp313-win_amd64.whl` and `torch-2.13.0+cpu-cp313-cp313-manylinux_2_28_x86_64.whl`
  (and `torchvision-0.28.0+cpu-cp313-cp313-win_amd64.whl` / `…manylinux_2_28_x86_64.whl`), checked 2026-11-21.
  pip resolves it as is (31 packages, ~1 GB venv). uv needs `--index-strategy unsafe-best-match` (added to
  `scripts/wt-env.sh`), because the torch index also serves old numpy/pillow.

## Gate measurements (2026-11-21, dev box: Ryzen 9 7900X, no GPU)

Jury-like limits for every row: `OCR_THREADS=8`, `ATEN_CPU_CAPABILITY=avx2 ONEDNN_MAX_CPU_ISA=AVX2
MKL_ENABLE_INSTRUCTIONS=AVX2`, `systemd-run --user --scope -p MemoryMax=12G -p MemorySwapMax=0`. The cap takes
effect: `torch.backends.cpu.get_cpu_capability()` reports `AVX2`, oneDNN verbose shows `jit:avx2` for fp32 convs,
and bf16 matmuls no longer use oneDNN's `avx512_core_bf16` (900×1280×896 bf16 GEMM 1.05 ms → 8.7 ms, the same as
with oneDNN disabled, i.e. the path a CPU without AVX512-BF16 takes). Command:
`scripts/ocr_probe.py bench [--dtype …] [--mode …] [--fast-decode …] PDF:PAGE …`. Seconds per page include
vision + prefill + decode; peak RSS is VmHWM per page (includes the mmapped weights).

**Default (`mixed`, gundam, fast-decode 0):** cold model load 2.7 s (weights cached; mmapped, RSS 3.5 GB after load).

| Page | s/page | prefill s | out tokens | tok/s | peak RSS GB |
|---|---:|---:|---:|---:|---:|
| `dane/skany/odwolania/0001` p1 | 67.4 | 9.1 | 1269 | 21.8 | 8.58 |
| `dane/skany/odwolania/0001` p2 (dense text) | 86.2 | 8.7 | 1609 | 20.7 | 9.53 |
| `dane/skany/pelnomocnictwa/0001` p1 | 49.5 | 8.4 | 916 | 22.3 | 9.56 |
| `dane/skany/potwierdzenia/0001` p1 | 40.5 | 8.5 | 734 | 23.0 | 9.56 |
| `dane/przyklad_03/odwolanie.pdf` p1 | 57.2 | 8.6 | 1076 | 22.1 | 9.57 |
| `dane/negatywne/Decyzja-Ministra-Sportu-i-Turystyki1.pdf` p1 | 42.8 | 8.5 | 793 | 23.1 | 9.58 |
| **mean / max** | **57.3 / 86.2** | | | | **max 9.58** |

**Variants** (on the two odwolanie pages, same limits):

| Setting | p1 s | p2 s | peak RSS GB | Output vs default |
|---|---:|---:|---:|---|
| default (`mixed`, gundam) | 67.4 | 86.2 | 9.53 | — |
| `OCR_DTYPE=bf16` (all bf16) | 110.8 | – | 7.0 | prefill 52 s instead of 9 s |
| fp32 everywhere | – | – | ~14 (est.) | not run: does not fit 12 GB |
| `OCR_MODE=base` (1 view, 279 prompt tokens) | 46.6 | 67.6 | 9.28 | a few more diacritics errors (`prowadżonego`, `DOWOLANIE`) |
| `OCR_FAST_DECODE=1` (single-token MoE) | 65.6 | 83.2 | 9.54 | identical (p2 byte-identical) |
| `OCR_FAST_DECODE=2` (+ dense decode attention) | 54.3 | 68.2 | 9.54 | p2: 15 word diffs out of ~1000 |
| `OCR_FAST_DECODE=2` + `OCR_DTYPE=mixed-int8head`¹ | 61.4 | 64.7 | 10.36 | clean text near-identical to fast-2 (3 word diffs), but p1 emitted 1538 instead of 1253 raw tokens (cause unknown), so p1 got slower |

¹ measured with per-tensor int8; the code now uses per-channel int8 for the head (only smoke-tested: 60 tokens, correct text).

Without the cap (12 threads, AVX-512) the default runs 45–50 s/page on the 1-page documents (cache fill demo).

**Gate verdict:** RAM **pass** (≤ 9.6 GB peak, 12 GB cap). Speed **fails** on dense pages: mean 57 s, but the
two pages with ≥ 1269 output tokens take 67–86 s (limit 60 s). Quality: **not measured on the full set** (below).

### Why decode is slow, and the laptop estimate

Time = ~9 s vision + prefill, then ~22 tok/s decode. Decode is **memory-bandwidth-bound**: each token reads
~575 M active parameters (12 layers × (attention + 2 shared + 6 of 64 routed experts) + a 129k-vocab lm_head),
i.e. ~1.15 GB of bf16 weights, ≈ 30–45 ms at 30–40 GB/s. It barely scales past 4 threads (1 thread 14 tok/s,
4 threads 23, 8 threads 24, 12 threads 24). A laptop i7 with dual-channel DDR4/DDR5 (~30–50 GB/s achievable)
and a slower vision prefill (~1.5× on 8 cores) should land at **~15–22 tok/s, i.e. 45–75 s for a light page and
90–120 s for a dense A4 page** (estimate, not measured).

## Quality

`scripts/ocr_probe.py quality` (cache-only) on the scans OCR'd so far (`dane/skany/pelnomocnictwa/0001`,
`dane/skany/potwierdzenia/0001`): NIP/REGON/KRS/account/transaction ids + names **10/10 found** (9/10 verbatim:
the NIP is printed `999-295-65-50`, found with separators removed); amount and date found. Reading the 6 gate
pages by eye: all NIP/KRS/REGON, account numbers, case numbers and names are correct; diacritics are almost
always right. Errors seen: `Ł`→`L` in capitals (`WPLYNEŁO`, `ODWOLANIE`, `JANA PAWLA`), `NADWIŚLANSKI` (Ń→N),
and a few word-level slips (`nieograniczowego`, `kómunalnych`, `zamieszkłych`, `predmiotowego`). End to end
(CLI, cached OCR, LLM) the scanned potwierdzenie gave the ground-truth JSON except `z_rachunku` without its `PL`
prefix (the OCR text has it; a normaliser/extraction follow-up). The LLM step
(D12) is expected to fix such typos. The full probe on all 30 scans was not run (see next steps).

## Next steps

1. **Cache fill (P2):** `make ocr-cache` (default 4 pages, breadth-first, resumable; one process). dane/ has
   226 PDFs, 400 pages at ≤ 4 per PDF (358 at ≤ 3); at ~45–55 s/page with 12 threads that is **≈ 5–6 h**. The 30
   scans alone (≤ 3 pages: 50 pages) take ≈ 40 min: `make ocr-cache PAGES=3 PATHS="$(ls dane/skany/*/*/*.pdf)"`.
   Then `OCR_CACHE_ONLY=1 scripts/ocr_probe.py quality -v` for the full per-field table (the quality gate).
2. **Speed options** (the decision belongs to the coordinator/user; any change of default = new cache):
   - (a) `OCR_MODE=base`: −20 s on dense pages, slightly more diacritics errors. Check with the probe.
   - (b) `OCR_DTYPE=mixed-int8head`: −3 ms/token in decode (29 vs 27 tok/s with fast-decode 2), clean text nearly
     unchanged, but on one page it emitted 23 % more raw tokens and was slower overall; inconclusive.
   - (c) `OCR_FAST_DECODE=2`: −20 % decode, small text differences; needs the quality probe before becoming the
     default. Next lever after that: **int8 weights for the whole decoder** (halves the bytes read per token,
     est. 1.6–2× decode). A prototype ran out of the 12 GB cap during quantization (packed int8 weights
     ~0.38 GB/layer + fp32 conversion of embeddings/vision) and broke on `self.q_proj.weight.device` in the
     remote code; it was shelved.
   - (d) Read fewer pages per class in the pipeline (O7), e.g. odwolanie page 1 only when the markers are there.
3. **Jury run (D1):** on a real AVX2-only laptop, measure the 6 gate pages (`scripts/ocr_probe.py bench`) to replace
   the estimate above. Not yet verified: a real clean-venv `pip install -r json4win/requirements.txt` (only a pip
   dry-run was done) and a first-run download with the pinned huggingface-hub 0.36.0 (the weights on the dev box
   were fetched with huggingface-hub 2.4.0).
4. **dpi:** 200 dpi was chosen because the model downsizes to 640 px tiles / a 1024 px view; it was not compared
   with the model card's 300 dpi. dpi is in the cache key.
