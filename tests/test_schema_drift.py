import re
from pathlib import Path

import pytest

from app import tables as T

MIGRATIONS = sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.up.sql"))
SQL = "\n".join(p.read_text() for p in MIGRATIONS)


def sql_columns() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for match in re.finditer(r"CREATE TABLE (\w+)\s*\((.*?)\n\);", SQL, re.S):
        name, body = match.group(1), match.group(2)
        columns: set[str] = set()
        depth = 0
        buffer = ""
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            buffer = buffer + " " + stripped if depth else stripped
            depth += stripped.count("(") - stripped.count(")")
            if depth > 0:
                continue
            token = buffer.split()[0] if buffer.split() else ""
            buffer = ""
            if token.upper() in {"CONSTRAINT", "PRIMARY", "UNIQUE", "FOREIGN", "CHECK"}:
                continue
            if re.fullmatch(r"[a-z_][a-z0-9_]*", token):
                columns.add(token)
        out[name] = columns

    for table, action, column in re.findall(
        r"ALTER TABLE (\w+)\s+(ADD|DROP) COLUMN (?:IF (?:NOT )?EXISTS )?(\w+)", SQL
    ):
        if table not in out:
            continue
        if action == "ADD":
            out[table].add(column)
        else:
            out[table].discard(column)
    return out


SQL_TABLES = sql_columns()
PY_TABLES = {name: {c.name for c in t.columns} for name, t in T.meta.tables.items()}


def test_the_ddl_can_be_read():
    assert len(SQL_TABLES) >= 16, f"only {len(SQL_TABLES)} tables read from the DDL"


@pytest.mark.parametrize("table", sorted(PY_TABLES))
def test_every_python_table_exists_in_the_ddl(table):
    assert table in SQL_TABLES, f"table '{table}' is defined in Python but not in SQL"


@pytest.mark.parametrize("table", sorted(PY_TABLES))
def test_python_columns_do_not_drift_from_the_ddl(table):
    if table not in SQL_TABLES:
        pytest.skip("a missing table is covered by its own test")
    extra = PY_TABLES[table] - SQL_TABLES[table]
    assert not extra, f"{table}: columns in Python but not in SQL -> {sorted(extra)}"


DELIBERATELY_UNMAPPED = {
    ("materials", "embedding"),
}


@pytest.mark.parametrize("table", sorted(SQL_TABLES))
def test_no_ddl_column_is_missed_in_python(table):
    if table not in PY_TABLES:
        pytest.skip(f"table {table} is not mapped in Python yet")
    missing = {
        c for c in SQL_TABLES[table] - PY_TABLES[table]
        if (table, c) not in DELIBERATELY_UNMAPPED
    }
    assert not missing, f"{table}: columns in SQL but missed in Python -> {sorted(missing)}"


def test_the_exception_list_is_not_stale():
    for table, column in DELIBERATELY_UNMAPPED:
        assert column in SQL_TABLES.get(table, set()), f"{table}.{column} is gone from SQL"
        assert column not in PY_TABLES.get(table, set()), (
            f"{table}.{column} is mapped in Python now, drop it from the exception list"
        )


def test_the_ddl_uses_no_enum_types():
    assert "AS ENUM" not in SQL.upper(), (
        "the DDL uses an ENUM type. Use TEXT with a CHECK so it matches tables.py."
    )
