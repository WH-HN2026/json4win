"""Settings from environment variables, with json4win/.env.local loaded first (architecture D13).

Every variable the app reads is listed in json4win/.env.example.
"""

import os
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from .env.local into os.environ; variables already set win."""
    path = path or APP_ROOT / ".env.local"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip("'\"")
        os.environ.setdefault(key.strip(), value)


def get(name: str, default: str = "") -> str:
    """An env setting; empty values count as unset."""
    return os.environ.get(name) or default


def cache_dir() -> Path:
    """Per-user cache dir shared by all worktrees (OCR results); JSON4WIN_CACHE_DIR overrides."""
    if override := get("JSON4WIN_CACHE_DIR"):
        return Path(override)
    if sys.platform == "win32":
        base = Path(get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "json4win"
