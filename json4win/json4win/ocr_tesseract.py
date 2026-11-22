"""Tesseract OCR backend via subprocess (no shell, Windows-compatible; task P4).

Renders each PDF page with pypdfium2 (in json4win.ocr) and feeds the PNG bytes over stdin to the
`tesseract` CLI (`tesseract stdin stdout --tessdata-dir <dir> -l <lang> --dpi <dpi> [--psm <psm>]`).
No extra Python dependencies are required. Traineddata files live outside git in
`OCR_TESSDATA_DIR` (default: `json4win.env.cache_dir()/tessdata`).
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from json4win import env

log = logging.getLogger(__name__)

BACKEND = "tesseract"
DEFAULT_CMD = "tesseract"
DEFAULT_LANG = "pol"
DEFAULT_DPI = 300
CACHE_FORMAT = 1
TIMEOUT_SECONDS = 120

_version_cache: dict[str, str] = {}
_tessdata_sha_memo: dict[tuple, str] = {}


@dataclass(frozen=True)
class TesseractSettings:
    """Tesseract OCR settings; version, lang, dpi, psm and traineddata hash go in the cache key."""

    lang: str = DEFAULT_LANG
    dpi: int = DEFAULT_DPI
    psm: int | None = None  # None = Tesseract's default page segmentation (PSM 3)
    tessdata_dir: str = ""
    cmd: str = DEFAULT_CMD


def default_tessdata_dir() -> Path:
    """OCR_TESSDATA_DIR, or `<cache_dir>/tessdata`."""
    if override := env.get("OCR_TESSDATA_DIR"):
        return Path(override)
    return env.cache_dir() / "tessdata"


def settings_from_env() -> TesseractSettings:
    """Tesseract settings from env (OCR_TESSERACT_CMD/LANG/DPI/PSM, OCR_TESSDATA_DIR)."""
    cmd = env.get("OCR_TESSERACT_CMD", DEFAULT_CMD)
    lang = env.get("OCR_TESSERACT_LANG", DEFAULT_LANG)
    dpi_raw = env.get("OCR_TESSERACT_DPI", str(DEFAULT_DPI))
    try:
        dpi = int(dpi_raw)
    except ValueError as e:
        raise ValueError(f"OCR_TESSERACT_DPI must be an integer, got {dpi_raw!r}") from e
    if dpi <= 0:
        raise ValueError(f"OCR_TESSERACT_DPI must be > 0, got {dpi}")

    psm: int | None = None
    if psm_raw := env.get("OCR_TESSERACT_PSM"):
        try:
            psm = int(psm_raw)
        except ValueError as e:
            raise ValueError(f"OCR_TESSERACT_PSM must be an integer, got {psm_raw!r}") from e
        if not 0 <= psm <= 13:
            raise ValueError(f"OCR_TESSERACT_PSM must be between 0 and 13, got {psm}")

    return TesseractSettings(
        lang=lang,
        dpi=dpi,
        psm=psm,
        tessdata_dir=str(default_tessdata_dir()),
        cmd=cmd,
    )


def _missing_binary_error(cmd: str) -> RuntimeError:
    return RuntimeError(
        f"Tesseract binary {cmd!r} not found. Install Tesseract OCR "
        "(Linux: package tesseract-ocr; Windows: UB Mannheim installer) "
        "or set OCR_TESSERACT_CMD."
    )


def tesseract_version(cmd: str = DEFAULT_CMD) -> str:
    """First line of `tesseract --version` (cached per binary path)."""
    if cmd in _version_cache:
        return _version_cache[cmd]
    try:
        proc = subprocess.run(
            [cmd, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except FileNotFoundError as e:
        raise _missing_binary_error(cmd) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Tesseract {cmd!r} --version timed out") from e

    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(f"Tesseract {cmd!r} --version failed (exit {proc.returncode}): {msg}")
    out = proc.stdout or proc.stderr or ""
    first = next((line.strip() for line in out.splitlines() if line.strip()), "unknown")
    _version_cache[cmd] = first
    return first


def tessdata_hash(tessdata_dir: str, lang: str) -> str | None:
    """Short sha256 of the traineddata file(s) for `lang` in `tessdata_dir`, or None if absent."""
    if not tessdata_dir:
        return None
    base = Path(tessdata_dir)
    if not base.is_dir():
        return None
    parts = [p.strip() for p in lang.split("+") if p.strip()]
    files = [(part, base / f"{part}.traineddata") for part in parts]
    present = [(part, f) for part, f in files if f.is_file()]
    if not present:
        return None
    memo_key = tuple(
        (part, str(f.resolve()), f.stat().st_size, f.stat().st_mtime_ns) for part, f in present
    )
    if memo_key not in _tessdata_sha_memo:
        h = hashlib.sha256()
        for part, f in present:
            h.update(part.encode("utf-8"))
            h.update(b"\0")
            with f.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
        _tessdata_sha_memo[memo_key] = h.hexdigest()[:16]
    return _tessdata_sha_memo[memo_key]


def cache_key(s: TesseractSettings) -> dict:
    """Serializable cache key dict for Tesseract (backend, version, lang, dpi, psm, traineddata)."""
    key: dict[str, object] = {
        "backend": BACKEND,
        "version": tesseract_version(s.cmd),
        "lang": s.lang,
        "dpi": s.dpi,
        "psm": s.psm,
        "format": CACHE_FORMAT,
    }
    if td_hash := tessdata_hash(s.tessdata_dir, s.lang):
        key["tessdata_sha256"] = td_hash
    return key


def build_command(s: TesseractSettings) -> list[str]:
    """Argument list for subprocess (no shell; safe with spaces and non-ASCII paths)."""
    cmd = [s.cmd, "stdin", "stdout"]
    if s.tessdata_dir:
        cmd.extend(["--tessdata-dir", s.tessdata_dir])
    cmd.extend(["-l", s.lang, "--dpi", str(s.dpi)])
    if s.psm is not None:
        cmd.extend(["--psm", str(s.psm)])
    return cmd


def run(image, s: TesseractSettings) -> dict:
    """OCR one rendered page image (PIL) with Tesseract. Returns raw stdout + timing."""
    buf = io.BytesIO()
    image.save(buf, format="PNG", dpi=(s.dpi, s.dpi))
    png_bytes = buf.getvalue()
    cmd = build_command(s)

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            input=png_bytes,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
        )
    except FileNotFoundError as e:
        raise _missing_binary_error(s.cmd) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Tesseract timed out after {TIMEOUT_SECONDS}s") from e

    elapsed = round(time.perf_counter() - t0, 2)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        hint = ""
        if (
            "traineddata" in err
            or "Error opening data file" in err
            or "Failed loading language" in err
        ):
            hint = (
                f" (check OCR_TESSDATA_DIR={s.tessdata_dir!r} and that {s.lang}.traineddata exists)"
            )
        raise RuntimeError(f"Tesseract failed (exit {proc.returncode}): {err}{hint}")

    raw = proc.stdout.decode("utf-8", errors="replace")
    return {
        "raw": raw,
        "seconds": elapsed,
        "backend": BACKEND,
    }


def clean_text(raw: str) -> str:
    """Plain text from Tesseract stdout: drop form feeds, normalise line endings and blank lines."""
    t = raw.replace("\x0c", "\n").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in t.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
