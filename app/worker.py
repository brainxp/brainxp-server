from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import uuid

from app import queue as Q
from app.db import dispose, engine
from app.services.generation import run as run_generation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
)
log = logging.getLogger("brainxp.worker")

HANDLERS = {"generate": lambda db, p: run_generation(db, uuid.UUID(p["material_id"]))}


async def handle(raw: str, job: dict) -> None:
    kind = job.get("kind")
    fn = HANDLERS.get(kind)
    if fn is None:
        log.error("jenis pekerjaan tidak dikenal: %s", kind)
        await Q.acknowledge(raw)
        return

    try:
        async with engine().begin() as db:
            await fn(db, job)
    except Exception:
        log.exception("pekerjaan %s gagal: %s", kind, job)
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
        log.info("mengembalikan %d pekerjaan yang tertinggal dari worker sebelumnya", moved)

    log.info("worker siap, menunggu pekerjaan")
    while not stop.is_set():
        try:
            reserved = await Q.reserve(timeout=5)
        except Exception:
            log.exception("gagal membaca antrean, mencoba lagi")
            await asyncio.sleep(3)
            continue
        if reserved is None:
            continue
        raw, job = reserved
        await handle(raw, job)

    log.info("worker berhenti")
    await Q.close()
    await dispose()


if __name__ == "__main__":
    asyncio.run(main())
