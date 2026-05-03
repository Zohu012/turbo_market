"""
Thin Redis-backed memoizer for analytics aggregates.

Keys: `analytics:v1:<endpoint>:<filters.cache_key()>:<extra>`.
TTL-only invalidation in v1 (no pub/sub bus). Disable globally via the
`ANALYTICS_CACHE_DISABLED` env var or by passing ttl=0.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Awaitable, Callable, Optional

import redis.asyncio as aioredis

from app.config import settings


log = logging.getLogger(__name__)
_client: Optional[aioredis.Redis] = None


def _enabled() -> bool:
    return os.environ.get("ANALYTICS_CACHE_DISABLED", "").lower() not in {"1", "true"}


def _get_client() -> Optional[aioredis.Redis]:
    global _client
    if not _enabled():
        return None
    if _client is None:
        try:
            _client = aioredis.from_url(
                settings.redis_url, encoding="utf-8", decode_responses=True
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("analytics_cache: redis init failed: %s", exc)
            _client = None
    return _client


async def cache_aggregate(
    key: str,
    ttl: int,
    factory: Callable[[], Awaitable[Any]],
) -> Any:
    """Return a JSON-serialisable cached value, computing+writing on miss.

    On any Redis error, falls back to invoking `factory()` directly so a flaky
    cache never breaks an endpoint.
    """
    if ttl <= 0:
        return await factory()

    client = _get_client()
    if client is None:
        return await factory()

    full_key = f"analytics:v1:{key}"
    try:
        cached = await client.get(full_key)
        if cached is not None:
            return json.loads(cached)
    except Exception as exc:  # noqa: BLE001
        log.warning("analytics_cache: get failed (%s): %s", full_key, exc)

    value = await factory()

    try:
        await client.setex(full_key, ttl, json.dumps(value, default=str))
    except Exception as exc:  # noqa: BLE001
        log.warning("analytics_cache: setex failed (%s): %s", full_key, exc)
    return value
