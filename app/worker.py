from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import uuid

from app import queue as Q
from app import tables as T
from app.db import dispose, engine
from app.services import guardian as G
from app.services.generation import publish
from app.services.generation import run as run_generation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
)
log = logging.getLogger("brainxp.worker")

HANDLERS = {
    "generate": lambda db, p: run_generation(db, uuid.UUID(p["material_id"])),
    "guardian_push": lambda db, p: G.deliver(
        db, subject_id=uuid.UUID(p["subject_id"]), kind=p["kind"],
        alert_id=p["alert_id"], detail=p.get("detail"),
    ),
}


async def watch_for_silence(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            async with engine().begin() as db:
                raised = await G.sweep(db)
            if raised:
                log.info("raised %d silent device alert(s)", raised)
        except Exception:
            log.exception("the silence watchdog failed, retrying next tick")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=G.SWEEP_INTERVAL)


async def abandon(job: dict) -> None:
    material_id = job.get("material_id")
    if not material_id:
        return
    try:
        async with engine().begin() as db:
            await db.execute(
                T.materials.update()
                .where(T.materials.c.id == uuid.UUID(material_id))
                .values(status="failed", gate_reason="internal_error")
            )
        await publish(uuid.UUID(material_id), {"stage": "failed", "reason": "internal_error"})
    except Exception:
        log.exception("could not mark material %s as failed", material_id)


async def handle(raw: str, job: dict) -> None:
    kind = job.get("kind")
    fn = HANDLERS.get(kind)
    if fn is None:
        log.error("unknown job kind: %s", kind)
        await Q.acknowledge(raw)
        return

    try:
        async with engine().begin() as db:
            await fn(db, job)
    except Exception:
        log.exception("job %s failed: %s", kind, job)
        await abandon(job)
    finally:
        await Q.acknowledge(raw)


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    moved = await Q.requeue_stale()
    if moved:
        log.info("requeued %d job(s) left behind by a previous worker", moved)

    watchdog = asyncio.create_task(watch_for_silence(stop))

    log.info("worker ready, waiting for jobs")
    while not stop.is_set():
        try:
            reserved = await Q.reserve(timeout=5)
        except Exception:
            log.exception("could not read the queue, retrying")
            await asyncio.sleep(3)
            continue
        if reserved is None:
            continue
        raw, job = reserved
        await handle(raw, job)

    watchdog.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await watchdog

    log.info("worker stopped")
    await Q.close()
    await dispose()


if __name__ == "__main__":
    asyncio.run(main())
