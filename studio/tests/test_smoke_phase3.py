from __future__ import annotations

from fastapi.testclient import TestClient

from pb_studio.api.main import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "studio-api"
    assert "env" in body


def test_settings_load():
    from pb_studio.core.config import Settings, get_settings

    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.database_url.startswith("postgresql")
    assert settings.redis_url.startswith("redis://")


def test_database_session_layer_importable():
    from pb_studio.core.database import get_db_session, get_session_factory  # noqa: F401


def test_redis_client_importable():
    from pb_studio.core.redis_client import get_redis  # noqa: F401


def test_celery_app_importable():
    from pb_studio.celery_app import celery_app  # noqa: F401


def test_response_queue_service_importable():
    from pb_studio.response_queue.service import QueueService  # noqa: F401


def test_worker_tasks_importable():
    import pb_studio.worker.tasks  # noqa: F401
