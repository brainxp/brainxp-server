import re
from pathlib import Path

import pytest

from app.migrate import LEGACY_BASELINE, split_pending, up_files

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
FILES = sorted(p.name for p in MIGRATIONS.iterdir())
NAME = re.compile(r"^\d{14}_[a-z][a-z0-9_]*\.(up|down)\.sql$")


def test_every_file_follows_the_naming_pattern():
    odd = [f for f in FILES if not NAME.match(f)]
    assert not odd, f"files outside <stamp>_<verb>_<what>.up|down.sql -> {odd}"


def test_every_up_file_has_a_down_file():
    ups = {f[: -len(".up.sql")] for f in FILES if f.endswith(".up.sql")}
    downs = {f[: -len(".down.sql")] for f in FILES if f.endswith(".down.sql")}
    assert ups == downs, f"unpaired: {sorted(ups ^ downs)}"


def test_stamps_are_unique():
    stamps = [f[:14] for f in FILES if f.endswith(".up.sql")]
    assert len(stamps) == len(set(stamps)), "two migrations share a timestamp"


@pytest.mark.parametrize("path", up_files(), ids=lambda p: p.name)
def test_a_create_file_makes_exactly_one_table(path):
    creates = re.findall(r"^CREATE TABLE (\w+)", path.read_text(), re.M)
    if "_create_" not in path.name:
        assert not creates, f"{path.name} creates {creates} but is not named create_"
        return
    expected = path.name.split("_create_", 1)[1][: -len(".up.sql")]
    if expected == "extensions":
        assert not creates
        return
    assert creates == [expected], f"{path.name} creates {creates}"


def test_legacy_ledger_rows_adopt_everything_up_to_their_stamp():
    files = up_files()
    adopted, todo = split_pending(files, {"001_init.sql", "002_weekly_caps_and_idle_lock.sql"})
    assert [p.name for p in todo] == [
        "20260907112627_create_installed_apps.up.sql",
        "20260908010020_create_push_tokens.up.sql",
        "20260908010021_create_guardian_alerts.up.sql",
    ]
    assert len(adopted) == len(files) - 3


def test_a_fully_migrated_legacy_ledger_has_nothing_pending():
    adopted, todo = split_pending(up_files(), set(LEGACY_BASELINE))
    assert not todo
    assert len(adopted) == len(up_files())


def test_a_fresh_database_runs_everything():
    adopted, todo = split_pending(up_files(), set())
    assert not adopted
    assert todo == up_files()


def test_a_current_ledger_has_nothing_to_do():
    done = {p.name for p in up_files()}
    assert split_pending(up_files(), done) == ([], [])
