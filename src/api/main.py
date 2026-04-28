"""FastAPI surface for Streamlit-adjacent clients (Mark II D4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from src.services.query_service import run_copilot_query

_REPO_ROOT = Path(__file__).resolve().parents[2]

app = FastAPI(title="DailyAssistant API", version="0.2.0")


class CopilotQueryBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=8000)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/copilot/query")
def copilot_query(body: CopilotQueryBody) -> dict[str, Any]:
    return run_copilot_query(body.question)


@app.get("/v1/kpi/revenue-total")
def kpi_revenue_total(
    date_start: str = Query(..., min_length=10, max_length=10, description="YYYY-MM-DD"),
    date_end: str = Query(..., min_length=10, max_length=10, description="YYYY-MM-DD"),
    outlets: list[str] = Query(default=[], description="Repeat param: outlets=A&outlets=B"),
) -> dict[str, Any]:
    """
    Read-only KPI slice: first row of the KPI aggregate query (same SQL family as Streamlit).
    """
    if not outlets:
        raise HTTPException(status_code=422, detail="Provide at least one `outlets` query param.")
    try:
        from src.services.kpi_service import load_kpi_tab_data

        data = load_kpi_tab_data(_REPO_ROOT, outlets, date_start, date_end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — DB missing, sqlite errors, etc.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if data.kpi.empty:
        return {"status": "ok", "date_start": date_start, "date_end": date_end, "kpi": {}}
    return {
        "status": "ok",
        "date_start": date_start,
        "date_end": date_end,
        "kpi": data.kpi.iloc[0].to_dict(),
    }


class MorningBriefJobBody(BaseModel):
    """Placeholder body for a future async morning-brief job."""

    dry_run: bool = True


@app.post("/v1/jobs/morning-brief")
def morning_brief_job(_body: MorningBriefJobBody) -> dict[str, Any]:
    """Stub: Morning Brief remains Streamlit-driven until a worker exists."""
    return {
        "job_id": "stub-not-scheduled",
        "status": "not_implemented",
        "detail": "Use the Streamlit Notification tab or scripts until D4 worker lands.",
    }
