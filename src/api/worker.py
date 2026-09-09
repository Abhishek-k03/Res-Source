"""Ingestion worker.

Claims job ids from Redis and runs the ingest graph. Job state lives in
Postgres, so this process is free to crash: whatever it was holding is
requeued on the next sweep.

    python -m api.worker
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

from dotenv import load_dotenv

from api import queue, services
from api.db import dispose_db, init_db, session_scope
from api.settings import get_settings

logger = logging.getLogger(__name__)


async def _handle(job_id: str) -> None:
    """Run one job and release it from the processing list.

    Never raises: this runs as a detached task, so an escaping exception would
    only surface as an unretrieved-task warning.
    """
    try:
        async with session_scope() as session:
            job = await services.run_job(session, job_id)
        if job is not None:
            logger.info("Job %s finished as %s.", job_id, job.status.value)
    except Exception:
        logger.exception("Job %s raised out of its handler.", job_id)
    finally:
        await queue.release(job_id)


SWEEP_EVERY_SECONDS = 120
"""How often to look for jobs whose queue signal never arrived."""


async def run(stop: asyncio.Event) -> None:
    """Claim and run jobs until asked to stop.

    Several jobs run at once, so one slow source -- an arXiv query pulling
    PDFs, say -- does not hold up everything queued behind it.
    """
    await init_db()
    limit = max(1, get_settings().worker_concurrency)
    running: set[asyncio.Task[None]] = set()
    last_sweep = 0.0

    logger.info("Worker ready (concurrency %d).", limit)
    while not stop.is_set():
        # A periodic sweep, not just one at startup: it is the backstop for any
        # signal lost while this worker was already running.
        now = asyncio.get_running_loop().time()
        if now - last_sweep >= SWEEP_EVERY_SECONDS:
            last_sweep = now
            try:
                async with session_scope() as session:
                    await services.requeue_stale_jobs(session)
            except Exception:
                logger.exception("Stale-job sweep failed.")

        while len(running) >= limit:
            await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            running = {task for task in running if not task.done()}

        try:
            job_id = await queue.claim(timeout=5)
        except Exception:
            logger.exception("Could not reach Redis; retrying shortly.")
            await asyncio.sleep(5)
            continue

        running = {task for task in running if not task.done()}
        if job_id is None:
            continue
        running.add(asyncio.create_task(_handle(job_id)))

    if running:
        logger.info("Finishing %d job(s) before shutdown.", len(running))
        await asyncio.gather(*running, return_exceptions=True)


async def main() -> int:
    """Entry point with graceful shutdown."""
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    for noisy in ("elastic_transport", "httpx", "urllib3", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        sig: Any = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows: KeyboardInterrupt handles it instead.
            pass

    try:
        await run(stop)
    except KeyboardInterrupt:
        pass
    finally:
        await queue.close_redis()
        await dispose_db()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
