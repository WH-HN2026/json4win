"""Unlimited-OCR-2 on CPU: lazy one-time model load and single-page inference (task P1).

The model ships custom code (trust_remote_code) written for CUDA. Three small runtime patches make
it run on a CPU-only torch without forking that code (docs/ocr.md):
- transformers refuses to load the remote code because one file imports `triton` (GPU only; the
  code only uses it on CUDA tensors), so `triton` is dropped from transformers' import check;
- the vision merge calls `.cuda()` on a mask tensor: `Tensor.cuda` is a no-op when CUDA is absent;
- the model prints debug lines with print(); stdout is swallowed during load and inference.
The vision encoder (SAM + CLIP, ~0.4B params) runs in fp32 and the decoder in bf16: bf16
convolutions are ~5x slower on CPUs without AVX512-BF16, and fp32 for the whole model needs ~14 GB.
"""

import contextlib
import io
import logging
import threading
import time
from dataclasses import dataclass

from json4win import env, ocr_fast

log = logging.getLogger(__name__)

MODEL_ID = "baidu/Unlimited-OCR-2"
MODEL_REVISION = "cb16b920ec2249c4b280f3aa67942e00b5099122"  # HF commit of 2026-11-16
PROMPT = "Multi page parsing."  # the only prompt the model card documents

DTYPES = ("mixed", "bf16", "mixed-int8head")


@dataclass(frozen=True)
class InferSettings:
    """Everything that changes the model output; part of the OCR cache key."""

    mode: str = "gundam"  # gundam = global view + 640px tiles; base = one 1024px view
    max_tokens: int = 3000  # per page; dense A4 pages need ~1300
    ngram: int = 35  # no-repeat n-gram guard against loops (model card values)
    ngram_window: int = 128
    dtype: str = "mixed"  # mixed = vision fp32 + decoder bf16; see DTYPES
    fast_decode: int = (
        0  # 0 = model code as is; 1 = single-token MoE; 2 = + dense decode (ocr_fast)
    )


_lock = threading.Lock()
_loaded: dict = {}


@contextlib.contextmanager
def _quiet():
    with contextlib.redirect_stdout(io.StringIO()):
        yield


def _cast_inputs(dtype):
    import torch

    def hook(_module, args):
        return tuple(
            a.to(dtype) if torch.is_tensor(a) and a.is_floating_point() else a for a in args
        )

    return hook


def _int8_head(lin):
    """lm_head as an int8 Linear (fp32 in/out); keeps `.weight.device`, which the model reads."""
    import torch

    class Int8Head(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.q = _int8_linear(lin)
            self.register_buffer("weight", torch.empty(0), persistent=False)

        def forward(self, x):
            return self.q(x.float())

    return Int8Head()


def _int8_linear(lin):
    """nn.Linear (any float dtype) -> dynamic int8 Linear, per-output-channel symmetric weights."""
    import torch
    from torch.ao.nn.quantized.dynamic import Linear

    w = lin.weight.detach().float()
    scale = (w.abs().amax(dim=1) / 127.0).clamp(min=1e-8).double()
    qw = torch.quantize_per_channel(
        w, scale, torch.zeros_like(scale, dtype=torch.long), 0, torch.qint8
    )
    q = Linear(lin.in_features, lin.out_features, bias_=lin.bias is not None, dtype=torch.qint8)
    q.set_weight_bias(qw, None if lin.bias is None else lin.bias.detach().float())
    return q


def _load(dtype: str):
    import torch
    import transformers
    from transformers import AutoModel, AutoTokenizer, dynamic_module_utils

    if dtype not in DTYPES:
        raise ValueError(f"OCR dtype {dtype!r} not in {DTYPES}")
    if threads := env.get("OCR_THREADS"):
        torch.set_num_threads(int(threads))
    if not torch.cuda.is_available():
        torch.Tensor.cuda = lambda self, *a, **k: self
    transformers.utils.logging.disable_progress_bar()
    transformers.utils.logging.set_verbosity_error()

    log.info("loading OCR model %s (first run downloads ~6.7 GB from Hugging Face)", MODEL_ID)
    t0 = time.time()
    get_imports = dynamic_module_utils.get_imports
    dynamic_module_utils.get_imports = lambda f: [m for m in get_imports(f) if m != "triton"]
    try:
        with _quiet():
            tok = AutoTokenizer.from_pretrained(
                MODEL_ID, revision=MODEL_REVISION, trust_remote_code=True
            )
            model = AutoModel.from_pretrained(
                MODEL_ID,
                revision=MODEL_REVISION,
                trust_remote_code=True,
                use_safetensors=True,
                torch_dtype=torch.bfloat16,
            ).eval()
    finally:
        dynamic_module_utils.get_imports = get_imports

    if dtype.startswith("mixed"):
        inner = model.model
        for enc in (inner.sam_model, inner.vision_model):
            enc.float()
            enc.register_forward_pre_hook(_cast_inputs(torch.float32))
        inner.projector.register_forward_pre_hook(_cast_inputs(torch.bfloat16))
    if dtype == "mixed-int8head":
        model.lm_head = _int8_head(model.lm_head)
    ocr_fast.install(model)
    log.info(
        "OCR model %s@%s loaded in %.1fs (%s, %d threads)",
        MODEL_ID,
        MODEL_REVISION[:8],
        time.time() - t0,
        dtype,
        torch.get_num_threads(),
    )
    return model, tok


def load(dtype: str = "mixed"):
    """The (model, tokenizer) pair, loaded once per process (downloads the weights on first use)."""
    with _lock:
        if dtype not in _loaded:
            _loaded.clear()
            _loaded[dtype] = _load(dtype)
        return _loaded[dtype]


def run(image, s: InferSettings) -> dict:
    """OCR one page image (PIL). Returns raw model text plus timing/token stats."""
    model, tok = load(s.dtype)
    with _lock, _quiet():
        ocr_fast.LEVEL["value"] = s.fast_decode
        t0 = time.time()
        r = model.infer(
            tok,
            prompt=PROMPT,
            image_file=image,
            crop_mode=s.mode == "gundam",
            max_new_tokens=s.max_tokens,
            no_repeat_ngram_size=s.ngram,
            ngram_window=s.ngram_window,
            eval_mode=True,
            return_dict=True,
        )
    return {
        "raw": r["text"],
        "seconds": round(time.time() - t0, 2),
        "prefill_seconds": round(r["prefill_time"] or 0.0, 2),
        "tokens": len(r["token_ids"]),
        "prompt_tokens": len(r["prompt_token_ids"]),
        "finish": r["finish_reason"],
    }
