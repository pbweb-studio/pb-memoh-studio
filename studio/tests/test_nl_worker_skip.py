from __future__ import annotations

import pytest

from pb_studio.core.config import get_settings
from pb_studio.nl.processor import run_nl_interactions_standalone


@pytest.mark.asyncio
async def test_run_nl_interactions_skipped_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_NL_COMMANDS_ENABLED", "false")
    get_settings.cache_clear()
    out = await run_nl_interactions_standalone()
    assert out.get("skipped") is True
    assert out.get("processed_nl") == 0
