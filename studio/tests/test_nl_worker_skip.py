from __future__ import annotations

import pytest

from pb_studio.core.config import get_settings
from pb_studio.nl.processor import run_nl_interactions_standalone


@pytest.mark.asyncio
async def test_run_nl_interactions_always_skipped_archived(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_NL_COMMANDS_ENABLED", "true")
    get_settings.cache_clear()
    out = await run_nl_interactions_standalone()
    assert out.get("skipped") is True
    assert out.get("reason") == "nl_responder_archived_single_brain"
    assert out.get("processed_nl") == 0
