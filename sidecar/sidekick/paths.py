"""Filesystem locations. Everything user-specific lives in the roaming app-data folder."""

from __future__ import annotations

import sys
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "Sidekick"


def app_data_dir() -> Path:
    path = Path(user_data_dir(APP_NAME, appauthor=False, roaming=True))
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return app_data_dir() / "config.toml"


def db_path() -> Path:
    return app_data_dir() / "sidekick.db"


def models_dir() -> Path:
    path = app_data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def brainstorms_dir() -> Path:
    """Scratch working directories of brainstorm sessions (Claude Code needs a cwd)."""
    path = app_data_dir() / "brainstorms"
    path.mkdir(parents=True, exist_ok=True)
    return path


def package_dir() -> Path:
    """Directory that holds bundled resources (sounds, prompts, models).

    Works both from source and from a PyInstaller onedir build, where resources are
    copied next to the executable under ``sidekick/``.
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidate = base / "sidekick"
        if candidate.exists():
            return candidate
        return base
    return Path(__file__).resolve().parent


def sounds_dir() -> Path:
    return package_dir() / "sounds"


def prompts_dir() -> Path:
    return package_dir() / "prompts"


def bundled_models_dir() -> Path:
    return package_dir() / "models"
