"""Centralized .env loading for repo root and optional legacy parent directory."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def load_app_dotenv(project_root: Path) -> list[Path]:
    """
    Load environment variables in stable order:
      1) <project_root>/.env (canonical)
      2) <project_root.parent>/.env (legacy; does not override keys from step 1)

    Returns list of paths that existed and were loaded.
    """
    loaded: list[Path] = []
    primary = project_root / ".env"
    if primary.is_file():
        load_dotenv(primary, override=True)
        loaded.append(primary)
    legacy = project_root.parent / ".env"
    if legacy.is_file():
        load_dotenv(legacy, override=not loaded)
        loaded.append(legacy)
    return loaded
