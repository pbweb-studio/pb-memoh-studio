from __future__ import annotations

import pytest

from pb_studio.core.config import get_settings


def test_celery_beat_omits_nl_processor_when_nl_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_NL_COMMANDS_ENABLED", "false")
    get_settings.cache_clear()
    from pb_studio.celery_app import create_celery_app

    app = create_celery_app()
    sched = app.conf.beat_schedule or {}
    assert "studio-process-nl-interactions" not in sched
    assert "studio-process-control-group-commands" in sched


def test_celery_beat_includes_nl_processor_when_nl_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_NL_COMMANDS_ENABLED", "true")
    get_settings.cache_clear()
    from pb_studio.celery_app import create_celery_app

    app = create_celery_app()
    sched = app.conf.beat_schedule or {}
    assert "studio-process-nl-interactions" in sched
