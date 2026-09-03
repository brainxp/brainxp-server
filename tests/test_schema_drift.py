import re
from pathlib import Path

import pytest

from app import tables as T

SQL = (Path(__file__).resolve().parents[1] / "migrations" / "001_init.sql").read_text()


def sql_columns() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for m in re.finditer(r"CREATE TABLE (\w+)\s*\((.*?)\n\);", SQL, re.S):
        name, body = m.group(1), m.group(2)
        cols: set[str] = set()
        depth = 0
        line_acc = ""
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            line_acc = line_acc + " " + stripped if depth else stripped
            depth += stripped.count("(") - stripped.count(")")
            if depth > 0:
                continue
            token = line_acc.split()[0] if line_acc.split() else ""
            line_acc = ""
            if token.upper() in {"CONSTRAINT", "PRIMARY", "UNIQUE", "FOREIGN", "CHECK"}:
                continue
            if re.fullmatch(r"[a-z_][a-z0-9_]*", token):
                cols.add(token)
        out[name] = cols
    return out


SQL_TABLES = sql_columns()
PY_TABLES = {name: {c.name for c in t.columns} for name, t in T.meta.tables.items()}


def test_ddl_terbaca():
    assert len(SQL_TABLES) >= 16, f"hanya {len(SQL_TABLES)} tabel terbaca dari DDL"


@pytest.mark.parametrize("table", sorted(PY_TABLES))
def test_setiap_tabel_python_ada_di_ddl(table):
    assert table in SQL_TABLES, f"tabel '{table}' didefinisikan di Python tetapi tidak di SQL"


@pytest.mark.parametrize("table", sorted(PY_TABLES))
def test_kolom_python_tidak_menyimpang_dari_ddl(table):
    if table not in SQL_TABLES:
        pytest.skip("ketiadaan tabel diuji terpisah")
    extra = PY_TABLES[table] - SQL_TABLES[table]
    assert not extra, f"{table}: kolom ada di Python tapi tidak di SQL → {sorted(extra)}"


DELIBERATELY_UNMAPPED = {
    ("materials", "embedding"),
}


@pytest.mark.parametrize("table", sorted(SQL_TABLES))
def test_kolom_ddl_tidak_terlewat_di_python(table):
    if table not in PY_TABLES:
        pytest.skip(f"tabel {table} belum dipetakan di Python")
    missing = {
        c for c in SQL_TABLES[table] - PY_TABLES[table]
        if (table, c) not in DELIBERATELY_UNMAPPED
    }
    assert not missing, f"{table}: kolom ada di SQL tapi terlewat di Python → {sorted(missing)}"


def test_daftar_pengecualian_tidak_basi():
    for table, col in DELIBERATELY_UNMAPPED:
        assert col in SQL_TABLES.get(table, set()), f"{table}.{col} sudah tidak ada di SQL"
        assert col not in PY_TABLES.get(table, set()), (
            f"{table}.{col} sudah dipetakan di Python — hapus dari daftar pengecualian"
        )


def test_ddl_tidak_memakai_tipe_enum():
    assert "AS ENUM" not in SQL.upper(), (
        "DDL memakai tipe ENUM. Pakai TEXT dengan CHECK agar cocok dengan tables.py."
    )
