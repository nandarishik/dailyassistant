"""HTTP / JSON contract for Copilot (`CopilotResponse`).

`evidence` (optional dict) may include:
- `numeric_facts` — digested markdown column sums from `query_sales_db` calls.
- `premise_check` — server-side rank vs calendar days when decline wording + one ISO date
  (`rank`, `total_days`, `premise_conflict`, `day_revenue`, …). See `src/copilot/premise_check.py`.
- `data_scope` — interpreted date window, outlet count, `max_invoice_date`, tables hint,
  `not_in_this_database`. See `src/copilot/data_scope.py`.
- `resolved_query_context` — normalized dates/outlets from the question.
- `intent` / `sql_sha256` — when the guarded intent path ran (`engine` == IntentSQL).
- `guardrail_flags` — e.g. `numeric_mismatch`, `numeric_mismatch_low`, `causal_language_review`,
  `premise_conflict`.
"""

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
    query_id: str | None = None
    evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
