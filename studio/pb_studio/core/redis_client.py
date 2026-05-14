from __future__ import annotations

from redis.asyncio import Redis

from pb_studio.core.config import Settings, get_settings

_redis: Redis | None = None


def get_redis(settings: Settings | None = None) -> Redis:
    global _redis
    if _redis is None:
        cfg = settings or get_settings()
        _redis = Redis.from_url(cfg.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
