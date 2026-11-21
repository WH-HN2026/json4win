"""LightOnOCR-2-1B on CPU: benchmark-only OCR backend (`OCR_BACKEND=lighton`, task P5, docs/ocr.md).

The model needs transformers >= 5, while json4win/requirements.txt pins transformers 4.52.1 for
Unlimited-OCR-2, so it runs only in the dev venv `.venv-lighton` (requirements-lighton.txt). torch
and transformers are imported lazily inside `load()`; the cache key is built from constants only,
so the main .venv can read the LightOnOCR cache with OCR_CACHE_ONLY=1.

Pages are rendered at 200 dpi (json4win.ocr) and downscaled here to a longest side of 1540 px (model
card), decoded greedily (the model's generation_config samples at temperature 0.2; we want
deterministic output). The output is markdown; `clean_text()` turns it into plain text.
"""

from __future__ import annotations

import importlib.metadata
import logging
import re
import threading
import time
from dataclasses import dataclass

from json4win import env

log = logging.getLogger(__name__)

BACKEND = "lighton"
MODEL_ID = "lightonai/LightOnOCR-2-1B"
MODEL_REVISION = "be7c41313c30e940fe5571de59e5fabc779e00c8"
RENDER_DPI = 200
LONGEST_SIDE = 1540
RESIZE = "lanczos"  # PIL thumbnail() filter used to reach LONGEST_SIDE
DECODING = "greedy"
CACHE_FORMAT = 1  # bump when the cached raw output would change for the same settings

DTYPES = ("bf16", "fp32")
MIN_TRANSFORMERS = 5


@dataclass(frozen=True)
class LightOnSettings:
    """Everything that changes the model output; part of the OCR cache key."""

    dtype: str = "bf16"  # bf16: same text as fp32 on a test page, 1.5x faster here (AVX512-BF16)
    max_tokens: int = 4096  # per page (model card value); a dense A4 page needs ~1500


def settings_from_env() -> LightOnSettings:
    """Settings from env (OCR_LIGHTON_DTYPE, OCR_LIGHTON_MAX_TOKENS)."""
    d = LightOnSettings()
    dtype = env.get("OCR_LIGHTON_DTYPE", d.dtype).strip().lower()
    if dtype not in DTYPES:
        raise ValueError(f"OCR_LIGHTON_DTYPE must be one of {', '.join(DTYPES)}, got {dtype!r}")
    raw = env.get("OCR_LIGHTON_MAX_TOKENS", str(d.max_tokens))
    try:
        max_tokens = int(raw)
    except ValueError as e:
        raise ValueError(f"OCR_LIGHTON_MAX_TOKENS must be an integer, got {raw!r}") from e
    if max_tokens <= 0:
        raise ValueError(f"OCR_LIGHTON_MAX_TOKENS must be > 0, got {max_tokens}")
    return LightOnSettings(dtype=dtype, max_tokens=max_tokens)


def cache_key(s: LightOnSettings) -> dict:
    """Cache key dict (constants and settings only: no torch/transformers import needed)."""
    return {
        "backend": BACKEND,
        "model": MODEL_ID,
        "revision": MODEL_REVISION,
        "dpi": RENDER_DPI,
        "longest_side": LONGEST_SIDE,
        "resize": RESIZE,
        "decoding": DECODING,
        "max_tokens": s.max_tokens,
        "dtype": s.dtype,
        "format": CACHE_FORMAT,
    }


def check_transformers() -> None:
    """Raise a clear error unless transformers >= 5 is installed (the main .venv has 4.52.1)."""
    try:
        version = importlib.metadata.version("transformers")
    except importlib.metadata.PackageNotFoundError as e:
        raise RuntimeError(
            "LightOnOCR needs transformers>=5 (not installed): use .venv-lighton, see docs/ocr.md"
        ) from e
    major = int(re.match(r"\d+", version).group()) if re.match(r"\d+", version) else 0
    if major < MIN_TRANSFORMERS:
        raise RuntimeError(
            f"LightOnOCR needs transformers>=5 (found {version}): "
            "use .venv-lighton, see docs/ocr.md"
        )


_lock = threading.Lock()
_loaded: dict = {}


def _load(dtype: str):
    check_transformers()
    import torch
    import transformers
    from transformers import LightOnOcrForConditionalGeneration, LightOnOcrProcessor

    if threads := env.get("OCR_THREADS"):
        torch.set_num_threads(int(threads))
    transformers.utils.logging.disable_progress_bar()
    transformers.utils.logging.set_verbosity_error()
    torch_dtype = {"bf16": torch.bfloat16, "fp32": torch.float32}[dtype]
    log.info("loading OCR model %s (first run downloads ~2 GB from Hugging Face)", MODEL_ID)
    t0 = time.time()
    model = LightOnOcrForConditionalGeneration.from_pretrained(
        MODEL_ID, revision=MODEL_REVISION, dtype=torch_dtype
    ).eval()
    processor = LightOnOcrProcessor.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
    log.info(
        "OCR model %s@%s loaded in %.1fs (%s, %d threads)",
        MODEL_ID,
        MODEL_REVISION[:8],
        time.time() - t0,
        dtype,
        torch.get_num_threads(),
    )
    return model, processor, torch_dtype


def load(dtype: str = "bf16"):
    """The (model, processor, torch dtype) triple, loaded once per process."""
    with _lock:
        if dtype not in _loaded:
            _loaded.clear()
            _loaded[dtype] = _load(dtype)
        return _loaded[dtype]


def resize(image):
    """The page image downscaled (aspect kept) so that its longest side is at most LONGEST_SIDE."""
    from PIL import Image

    image = image.copy()
    image.thumbnail((LONGEST_SIDE, LONGEST_SIDE), resample=Image.Resampling.LANCZOS)
    return image


def run(image, s: LightOnSettings) -> dict:
    """OCR one page image (PIL, rendered at RENDER_DPI). Returns raw markdown plus timing/tokens."""
    model, processor, torch_dtype = load(s.dtype)
    import torch

    image = resize(image)
    conversation = [{"role": "user", "content": [{"type": "image", "image": image}]}]
    with _lock:
        inputs = processor.apply_chat_template(
            conversation,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        )
        inputs = {k: v.to(torch_dtype) if v.is_floating_point() else v for k, v in inputs.items()}
        prompt_tokens = int(inputs["input_ids"].shape[1])
        t0 = time.time()
        with torch.inference_mode():
            out = model.generate(**inputs, max_new_tokens=s.max_tokens, do_sample=False)
        seconds = time.time() - t0
    gen = out[0, prompt_tokens:].tolist()
    eos = model.generation_config.eos_token_id
    eos = set(eos if isinstance(eos, list) else [eos])
    finish = "stop" if gen and gen[-1] in eos else "length"
    return {
        "raw": processor.decode(gen, skip_special_tokens=True),
        "seconds": round(seconds, 2),
        "tokens": len(gen),
        "prompt_tokens": prompt_tokens,
        "model_image_size": list(image.size),
        "finish": finish,
        "backend": BACKEND,
    }


# ---- markdown output -> plain text -------------------------------------------------------------

_IMAGE = re.compile(r"!\[[^\]\n]*\]\([^)\n]*\)")  # ![alt](src) -> dropped
_LINK = re.compile(r"\[([^\]\n]*)\]\([^)\n]*\)")  # [label](mailto:x) -> label
_HTML_IMG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_HTML_CELL = re.compile(r"</t[dh]>\s*<t[dh][^>]*>", re.IGNORECASE)
_HTML_ROW = re.compile(r"</?(?:tr|table|thead|tbody|div|p|br)\b[^>]*>", re.IGNORECASE)
_HTML_TAG = re.compile(r"</?(?:td|th|span|b|i|u|em|strong|sup|sub)\b[^>]*>", re.IGNORECASE)
_HEADING = re.compile(r"^#{1,6}\s+")
_TABLE_SEP = re.compile(r"^\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?$")  # |---|:--:|
_RULE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
_BLANK = re.compile(r"\*?\((?:blank|empty|puste)\)\*?", re.IGNORECASE)
_EMPH = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")  # *italic* (not a*b*c)
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|<>~])")


def clean_text(raw: str) -> str:
    """Plain text from LightOnOCR markdown: tables as `cell | cell` lines, images dropped."""
    t = _IMAGE.sub("", raw)
    t = _HTML_IMG.sub("", t)
    t = _LINK.sub(r"\1", t)
    t = _HTML_CELL.sub(" | ", t)
    t = _HTML_ROW.sub("\n", t)
    t = _HTML_TAG.sub(" ", t)
    t = _BLANK.sub("", t)
    lines = []
    for line in t.splitlines():
        line = line.strip()
        if _TABLE_SEP.match(line) or _RULE.match(line):
            continue
        line = _HEADING.sub("", line)
        if line.startswith("|") and line.endswith("|") and len(line) > 1:
            line = line[1:-1]
        line = " | ".join(c.strip() for c in line.split("|")) if "|" in line else line
        line = line.replace("**", "").replace("__", "")
        line = _EMPH.sub(r"\1", line)
        line = _ESCAPE.sub(r"\1", line)
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line and line != "|":
            lines.append(line)
    return "\n".join(lines).strip()
