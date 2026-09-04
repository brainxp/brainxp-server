from datetime import timedelta

import pytest

from app.routers.auth import REPLAY_GRACE, _reply_was_lost
from app.security import now


class HasilKosong:
    def first(self):
        return None


class HasilAda:
    def first(self):
        return (1,)


class DbPalsu:
    def __init__(self, hasil):
        self.hasil = hasil

    async def execute(self, _):
        return self.hasil


def baris(*, dipakai_sejak: timedelta):
    return {"id": 1, "family_chain": 2, "used_at": now() - dipakai_sejak}


@pytest.mark.asyncio
async def test_pemakaian_ulang_sesaat_dianggap_balasan_yang_hilang():
    hilang = await _reply_was_lost(
        DbPalsu(HasilKosong()), baris(dipakai_sejak=timedelta(seconds=2))
    )
    assert hilang is True, (
        "klien yang memuat ulang halaman sebelum sempat menyimpan token barunya "
        "harus bisa memakai token lamanya sekali lagi"
    )


@pytest.mark.asyncio
async def test_pemakaian_ulang_setelah_tenggang_tetap_dianggap_pencurian():
    hilang = await _reply_was_lost(
        DbPalsu(HasilKosong()), baris(dipakai_sejak=REPLAY_GRACE + timedelta(seconds=1))
    )
    assert hilang is False


@pytest.mark.asyncio
async def test_token_lama_ditolak_kalau_penerusnya_sudah_terpakai():
    hilang = await _reply_was_lost(
        DbPalsu(HasilAda()), baris(dipakai_sejak=timedelta(seconds=2))
    )
    assert hilang is False, (
        "kalau rantainya sudah bergerak, klien jelas menerima token barunya, "
        "jadi yang menyodorkan token lama bukan dia"
    )
