"""Redis job queue.

Redis carries job ids only; Postgres holds the job's actual state. A lost or
duplicated message therefore cannot corrupt anything, and a crashed worker is
recoverable: `claim` moves the id onto a processing list rather than deleting
it, and `requeue_stale` returns abandoned work to the queue.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis
from redis.exceptions import TimeoutError as RedisTimeoutError

from api.settings import get_settings

logger = logging.getLogger(__name__)

BLOCKING_TIMEOUT = 5
"""Seconds `claim` waits before reporting an empty queue."""

_client: Redis | None = None


def get_redis() -> Redis:
    """Return the process-wide Redis client."""
    global _client
    if _client is None:
        _client = Redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            # Longer than the blocking pop, so the socket does not expire first.
            socket_timeout=BLOCKING_TIMEOUT * 2,
            health_check_interval=30,
        )
    return _client


async def close_redis() -> None:
    """Close the Redis connection on shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def enqueue(job_id: str) -> None:
    """Signal that a job is ready to be picked up."""
    settings = get_settings()
    await get_redis().lpush(settings.job_queue_key, job_id)


async def claim(timeout: int = BLOCKING_TIMEOUT) -> str | None:
    """Block for a job id, moving it to the processing list so it survives a crash.

    Returns None when the wait expires -- an idle queue, not a failure.
    """
    settings = get_settings()
    try:
        job_id = await get_redis().blmove(
            settings.job_queue_key,
            settings.job_processing_key,
            timeout,
            src="RIGHT",
            dest="LEFT",
        )
    except RedisTimeoutError:
        return None
    return None if job_id is None else str(job_id)


async def release(job_id: str) -> None:
    """Drop a finished job id from the processing list."""
    settings = get_settings()
    await get_redis().lrem(settings.job_processing_key, 1, job_id)


async def requeue(job_id: str) -> None:
    """Return a job to the queue for another attempt."""
    await release(job_id)
    await enqueue(job_id)


async def queue_depth() -> int:
    """How many jobs are waiting."""
    return int(await get_redis().llen(get_settings().job_queue_key))
