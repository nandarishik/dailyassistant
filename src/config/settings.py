from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    app_db_path: str = "database/AI_DATABASE.DB"


def get_settings() -> AppSettings:
    return AppSettings(
        app_db_path=os.getenv("APP_DB_PATH", "database/AI_DATABASE.DB"),
    )


def resolve_db_path(base_dir: Path) -> Path:
    settings = get_settings()
    return base_dir / settings.app_db_path
