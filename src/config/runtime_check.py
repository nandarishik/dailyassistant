"""Startup validation for database path and runtime configuration (D1)."""

from __future__ import annotations

from pathlib import Path

from src.config.settings import get_settings, resolve_db_path


class DatabaseConfigError(RuntimeError):
    """Raised when the configured database path is missing or unusable."""


def validate_database_path(base_dir: Path, *, require_exists: bool = True) -> Path:
    """
    Resolve APP_DB_PATH relative to base_dir and optionally require the file.

    Returns the absolute Path to the SQLite database.
    Raises DatabaseConfigError if require_exists and file is missing.
    """
    path = resolve_db_path(base_dir)
    raw = get_settings().app_db_path.strip()
    if not raw:
        raise DatabaseConfigError("APP_DB_PATH is empty; set it to e.g. database/AI_DMS_database.db")
    if ".." in Path(raw).parts:
        raise DatabaseConfigError("APP_DB_PATH must not contain '..' path segments")
    if require_exists and not path.is_file():
        raise DatabaseConfigError(
            f"Database file not found: {path}\n"
            "Copy AI_DMS_database.db into database/ or set APP_DB_PATH to the correct file."
        )
    return path
