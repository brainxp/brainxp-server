from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import text

from app.db import dispose, engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
log = logging.getLogger("brainxp.migrate")

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  filename    TEXT PRIMARY KEY,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


async def run_script(conn, sql: str) -> None:
    raw = await conn.get_raw_connection()
    await raw.driver_connection.execute(sql)


async def pending(conn) -> list[Path]:
    await conn.execute(text(LEDGER))
    done = {r[0] for r in (await conn.execute(text("SELECT filename FROM schema_migrations"))).all()}
    return [p for p in sorted(MIGRATIONS.glob("*.sql")) if p.name not in done]


async def run() -> int:
    files = sorted(MIGRATIONS.glob("*.sql"))
    if not files:
        log.error("no migration files in %s", MIGRATIONS)
        return 1

    async with engine().begin() as conn:
        todo = await pending(conn)

    if not todo:
        log.info("database already up to date, %d migration(s) applied", len(files))
        return 0

    for path in todo:
        log.info("applying %s", path.name)
        async with engine().begin() as conn:
            await run_script(conn, path.read_text())
            await conn.execute(
                text("INSERT INTO schema_migrations (filename) VALUES (:f)"),
                {"f": path.name},
            )
    log.info("done, %d migration(s) applied", len(todo))
    return 0


async def status() -> int:
    async with engine().begin() as conn:
        todo = await pending(conn)
    if todo:
        log.warning("pending migrations: %s", ", ".join(p.name for p in todo))
        return 1
    log.info("database up to date")
    return 0


async def main() -> int:
    try:
        return await (status() if "--check" in sys.argv else run())
    finally:
        await dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
