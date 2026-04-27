from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CopilotResponse:
    status: str
    contract_version: str = "v1"
    answer_text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    guardrail_flags: list[str] = field(default_factory=list)
    latency_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
