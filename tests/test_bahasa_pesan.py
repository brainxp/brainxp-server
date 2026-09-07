import ast
import re
from pathlib import Path

import pytest

from app.errors import Forbidden, LLMRefused, NotFound, RateLimited, TooLarge, Unauthorized

AKAR = Path(__file__).resolve().parents[1]
SUMBER = [*sorted((AKAR / "app").rglob("*.py")), AKAR / "scripts" / "gen_openapi.py"]

KATA_INDONESIA = (
    "tidak", "belum", "sudah", "yang", "untuk", "dengan", "gagal", "berkas", "jalankan",
    "menerapkan", "mengembalikan", "menunggu", "kedaluwarsa", "dikenal", "dibuang",
    "menolak", "cadangan", "penyedia", "pekerjaan", "perangkat", "antrean", "tertinggal",
    "mutakhir", "tertunda", "memakai", "dipakai", "ganti", "coba", "hangus", "galat",
    "aplikasi", "aturan", "saldo", "soal", "materi", "kunci",
)
POLA = re.compile(r"\b(" + "|".join(KATA_INDONESIA) + r")\b", re.I)

PENERBIT_LOG = {"info", "warning", "error", "exception", "debug", "critical"}
GALAT_MENTAH = {"RuntimeError", "ValueError", "TypeError", "NotImplementedError"}


def teks_harfiah(node) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return " ".join(
            bagian.value for bagian in node.values
            if isinstance(bagian, ast.Constant) and isinstance(bagian.value, str)
        )
    return ""


def ditujukan_ke_developer(node: ast.Call) -> bool:
    fungsi = node.func
    if isinstance(fungsi, ast.Attribute):
        induk = fungsi.value
        return isinstance(induk, ast.Name) and induk.id == "log" and fungsi.attr in PENERBIT_LOG
    if isinstance(fungsi, ast.Name):
        return fungsi.id in GALAT_MENTAH or fungsi.id == "print"
    return False


def pesan_developer():
    keluar = []
    for berkas in SUMBER:
        pohon = ast.parse(berkas.read_text())
        for node in ast.walk(pohon):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if not ditujukan_ke_developer(node):
                continue
            teks = teks_harfiah(node.args[0])
            if teks:
                keluar.append((berkas.relative_to(AKAR).as_posix(), node.lineno, teks))
    return keluar


PESAN = pesan_developer()


def test_pesan_developer_memang_terbaca():
    assert len(PESAN) >= 20, f"hanya {len(PESAN)} pesan terbaca, pembacanya kemungkinan rusak"


@pytest.mark.parametrize(
    "berkas,baris,teks", PESAN, ids=lambda v: str(v) if not isinstance(v, str) else v[:40]
)
def test_pesan_untuk_developer_ditulis_dalam_bahasa_inggris(berkas, baris, teks):
    tertangkap = sorted({m.lower() for m in POLA.findall(teks)})
    assert not tertangkap, (
        f"{berkas}:{baris} memakai kata Indonesia {tertangkap} pada pesan yang hanya "
        f"dibaca developer: {teks!r}"
    )


KELAS_PENGGUNA = [Unauthorized, Forbidden, NotFound, TooLarge, RateLimited, LLMRefused]


@pytest.mark.parametrize("kelas", KELAS_PENGGUNA, ids=lambda k: k.__name__)
def test_pesan_untuk_pengguna_tetap_bahasa_indonesia(kelas):
    pesan = kelas().detail["message"]
    assert POLA.search(pesan), (
        f"{kelas.__name__} membalas '{pesan}' ke pengguna akhir. Isi balasan HTTP dibaca "
        "orang tua dan anak, jadi tetap bahasa Indonesia"
    )


def test_balasan_500_tetap_bahasa_indonesia():
    sumber = (AKAR / "app" / "main.py").read_text()
    assert '"message": "Terjadi galat di server."' in sumber, (
        "badan balasan 500 sampai ke pengguna, beda dengan log.exception di atasnya"
    )
