from datetime import timedelta

from app.routers.auth import REPLAY_GRACE, replay_is_recoverable
from app.security import now

SAAT_INI = now()


def dipakai(sejak: timedelta):
    return SAAT_INI - sejak


def test_pemakaian_ulang_sesaat_dianggap_balasan_yang_hilang():
    assert replay_is_recoverable(
        used_at=dipakai(timedelta(seconds=2)), chain_moved_on=False, at=SAAT_INI
    ), (
        "klien yang memuat ulang halaman sebelum sempat menyimpan token barunya "
        "harus bisa memakai token lamanya sekali lagi"
    )


def test_pemakaian_ulang_setelah_tenggang_tetap_dianggap_pencurian():
    assert not replay_is_recoverable(
        used_at=dipakai(REPLAY_GRACE + timedelta(seconds=1)),
        chain_moved_on=False, at=SAAT_INI,
    )


def test_tepat_di_batas_tenggang_masih_diterima():
    assert replay_is_recoverable(
        used_at=dipakai(REPLAY_GRACE), chain_moved_on=False, at=SAAT_INI
    )


def test_token_lama_ditolak_kalau_rantainya_sudah_bergerak():
    assert not replay_is_recoverable(
        used_at=dipakai(timedelta(seconds=2)), chain_moved_on=True, at=SAAT_INI
    ), (
        "kalau ada token yang dipakai setelah token ini, klien jelas menerima "
        "penggantinya, jadi yang menyodorkan token lama bukan dia"
    )
