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
STAMP_LENGTH = 14

LEGACY_BASELINE = {
    "001_init.sql": "20260903192248",
    "002_weekly_caps_and_idle_lock.sql": "20260904143651",
    "003_installed_apps.sql": "20260907112627",
    "004_push_tokens.sql": "20260908010020",
    "005_guardian_alerts.sql": "20260908010021",
}

LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  filename    TEXT PRIMARY KEY,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def up_files() -> list[Path]:
    return sorted(MIGRATIONS.glob("*.up.sql"))


def stamp_of(path: Path) -> str:
    return path.name[:STAMP_LENGTH]


def legacy_baseline(done: set[str]) -> str | None:
    stamps = [LEGACY_BASELINE[name] for name in done if name in LEGACY_BASELINE]
    return max(stamps) if stamps else None


def split_pending(files: list[Path], done: set[str]) -> tuple[list[Path], list[Path]]:
    baseline = legacy_baseline(done)
    adopted: list[Path] = []
    todo: list[Path] = []
    for path in files:
        if path.name in done:
            continue
        if baseline and stamp_of(path) <= baseline:
            adopted.append(path)
        else:
            todo.append(path)
    return adopted, todo


async def run_script(conn, sql: str) -> None:
    raw = await conn.get_raw_connection()
    await raw.driver_connection.execute(sql)


async def record(conn, name: str) -> None:
    await conn.execute(text("INSERT INTO schema_migrations (filename) VALUES (:f)"), {"f": name})


async def applied(conn) -> set[str]:
    await conn.execute(text(LEDGER))
    rows = await conn.execute(text("SELECT filename FROM schema_migrations"))
    return {r[0] for r in rows.all()}


async def pending(conn) -> tuple[list[Path], list[Path]]:
    return split_pending(up_files(), await applied(conn))


async def adopt_legacy(conn, adopted: list[Path]) -> None:
    for path in adopted:
        await record(conn, path.name)
    for name in LEGACY_BASELINE:
        await conn.execute(text("DELETE FROM schema_migrations WHERE filename = :f"), {"f": name})
    log.info("adopted %d migration(s) recorded under the legacy file names", len(adopted))


async def run() -> int:
    files = up_files()
    if not files:
        log.error("no migration files in %s", MIGRATIONS)
        return 1

    async with engine().begin() as conn:
        adopted, todo = await pending(conn)
        if adopted:
            await adopt_legacy(conn, adopted)

    if not todo:
        log.info("database already up to date, %d migration(s) applied", len(files))
        return 0

    for path in todo:
        log.info("applying %s", path.name)
        async with engine().begin() as conn:
            await run_script(conn, path.read_text())
            await record(conn, path.name)
    log.info("done, %d migration(s) applied", len(todo))
    return 0


async def status() -> int:
    async with engine().begin() as conn:
        adopted, todo = await pending(conn)
    if adopted:
        log.info("%d migration(s) still recorded under the legacy file names", len(adopted))
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
