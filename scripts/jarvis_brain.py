"""
Backward-compatible shim: Jarvis branding merged into Copilot.

All logic lives in `copilot_brain.py`. Import from there in new code.
"""

from __future__ import annotations

from copilot_brain import (  # noqa: F401
    TOOL_REGISTRY,
    CopilotAgent as JarvisAgent,
    CopilotResult as JarvisResult,
    generate_anomaly_diagnosis,
    generate_proactive_brief,
    _tool_compute_live_basket,
    _tool_get_combo_recommendations,
    _tool_get_holiday_status,
    _tool_get_news_context,
    _tool_get_weather_context,
    _tool_query_sales_db,
    _tool_simulate_scenario,
)
