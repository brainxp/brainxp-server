import re
from pathlib import Path

import pytest

from app.config import MIN_JWT_SECRET_LENGTH, Settings, ephemeral_signing_key, weak_secret_reason

BERKAS_KODE = sorted(
    p for p in (Path(__file__).resolve().parents[1] / "app").rglob("*.py")
)

MEDAN_RAHASIA = [
    "jwt_secret",
    "database_url",
    "anthropic_api_key",
    "s3_access_key",
    "s3_secret_key",
]


@pytest.mark.parametrize("medan", MEDAN_RAHASIA)
def test_tidak_ada_kredensial_bawaan_di_kode(medan):
    assert Settings.model_fields[medan].default == "", (
        f"{medan} punya nilai bawaan di kode. Kredensial hanya boleh datang dari .env, "
        "supaya tidak ada yang ikut tersalin saat repositori dibagikan"
    )


def test_kode_tidak_memuat_kata_sandi_di_dalam_url():
    pola = re.compile(r"://[^/\s\"']+:[^/\s\"'@]+@")
    tersangka = [
        f"{p.name}: {m.group(0)}"
        for p in BERKAS_KODE
        for m in pola.finditer(p.read_text())
    ]
    assert not tersangka, f"URL dengan kata sandi tertanam di kode: {tersangka}"


def test_produksi_menolak_rahasia_kosong():
    assert weak_secret_reason("production", "") is not None


@pytest.mark.parametrize(
    "nilai",
    ["ganti-dengan-64-karakter-acak", "dev-secret-jangan-dipakai-di-produksi", "changeme"],
)
def test_produksi_menolak_nilai_contoh(nilai):
    assert weak_secret_reason("production", nilai) is not None, (
        "nilai contoh dari .env.example gampang ikut tersalin ke server tanpa diganti"
    )


def test_produksi_menolak_rahasia_pendek():
    assert weak_secret_reason("production", "a" * (MIN_JWT_SECRET_LENGTH - 1)) is not None
    assert weak_secret_reason("production", "a" * MIN_JWT_SECRET_LENGTH) is None


def test_pengembangan_tidak_dipaksa_mengisi_rahasia():
    assert weak_secret_reason("development", "") is None


def test_kunci_sementara_acak_dan_tetap_sepanjang_proses():
    assert ephemeral_signing_key() == ephemeral_signing_key(), (
        "token yang diterbitkan harus masih bisa dibaca oleh permintaan berikutnya"
    )
    assert len(ephemeral_signing_key()) >= MIN_JWT_SECRET_LENGTH


def test_kunci_penanda_tangan_memakai_rahasia_bila_diisi():
    assert Settings(jwt_secret="x" * 64).signing_key == "x" * 64
    assert Settings(jwt_secret="").signing_key == ephemeral_signing_key()
