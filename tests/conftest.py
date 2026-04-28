"""Pytest fixtures."""

from __future__ import annotations

import pytest
from src.config.settings import clear_settings_cache


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()
