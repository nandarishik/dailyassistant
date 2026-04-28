"""Optional append-only JSONL traces for Copilot (plan Phase 14)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def append_copilot_trace(base_dir: Path, payload: dict[str, Any]) -> None:
    """Write one JSON line under var/copilot_traces/ (creates parents)."""
    log_dir = base_dir / "var" / "copilot_traces"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "copilot.jsonl"
    row = {"ts": datetime.now(tz=UTC).isoformat(), **payload}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
