"""KPI tab input validation (no pandas — safe for lightweight tests)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator


class KpiTabQuery(BaseModel):
    """Validates non-empty KPI tab inputs (Mark II D1)."""

    outlets: list[str] = Field(default_factory=list)
    date_start: str = ""
    date_end: str = ""

    @field_validator("outlets", mode="before")
    @classmethod
    def _strip_outlets(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            return []
        return [str(x).strip() for x in v if str(x).strip()]

    @field_validator("date_start", "date_end")
    @classmethod
    def _iso_date(cls, v: str) -> str:
        if not v:
            raise ValueError("date must be non-empty YYYY-MM-DD")
        date.fromisoformat(v)
        return v

    @model_validator(mode="after")
    def _ordered(self) -> KpiTabQuery:
        if self.outlets and self.date_start > self.date_end:
            raise ValueError("date_start must be on or before date_end")
        return self
