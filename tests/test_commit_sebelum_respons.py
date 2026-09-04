from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.db import conn
from app.main import api
from app.routes import CommitBeforeResponse

TANPA_BASIS_DATA = {"/health"}


class TransaksiPalsu:
    def __init__(self, jejak: list[str]) -> None:
        self.jejak = jejak
        self.is_active = True

    async def commit(self) -> None:
        self.is_active = False
        self.jejak.append("commit")

    async def rollback(self) -> None:
        self.is_active = False
        self.jejak.append("rollback")


class ResponsBerjejak(Response):
    def __init__(self, jejak: list[str], status_code: int) -> None:
        super().__init__(status_code=status_code)
        self.jejak = jejak

    async def __call__(self, scope, receive, send) -> None:
        self.jejak.append("respons terkirim")
        await super().__call__(scope, receive, send)


def bangun(jejak: list[str], *, kelas_rute: type[APIRoute], meledak: bool = False) -> FastAPI:
    async def sambungan(request: Request) -> AsyncIterator[TransaksiPalsu]:
        tx = TransaksiPalsu(jejak)
        request.state.tx = tx
        try:
            yield tx
        except BaseException:
            if tx.is_active:
                await tx.rollback()
            raise
        if tx.is_active:
            await tx.commit()

    router = APIRouter(route_class=kelas_rute)

    @router.post("/tulis")
    async def tulis(tx: TransaksiPalsu = Depends(sambungan)) -> Response:
        if meledak:
            raise RuntimeError("gagal di tengah jalan")
        return ResponsBerjejak(jejak, 201)

    app = FastAPI()
    app.include_router(router)
    return app


def test_transaksi_ditutup_sebelum_klien_menerima_balasan():
    jejak: list[str] = []
    client = TestClient(bangun(jejak, kelas_rute=CommitBeforeResponse))

    assert client.post("/tulis").status_code == 201
    assert jejak == ["commit", "respons terkirim"], (
        "commit harus selesai sebelum balasan dikirim; kalau tidak, klien bisa "
        "membaca ulang lewat koneksi lain sebelum tulisannya terlihat"
    )


def test_rute_polos_membalas_sebelum_commit():
    jejak: list[str] = []
    client = TestClient(bangun(jejak, kelas_rute=APIRoute))

    assert client.post("/tulis").status_code == 201
    assert jejak == ["respons terkirim", "commit"], (
        "ini bentuk bawaan FastAPI yang jadi sumber masalahnya, dijaga di sini "
        "supaya perubahan perilakunya ketahuan"
    )


def test_kegagalan_tetap_dibatalkan():
    jejak: list[str] = []
    client = TestClient(
        bangun(jejak, kelas_rute=CommitBeforeResponse, meledak=True),
        raise_server_exceptions=False,
    )

    assert client.post("/tulis").status_code == 500
    assert jejak == ["rollback"]


def _memakai_sambungan(dependant) -> bool:
    if dependant.call is conn:
        return True
    return any(_memakai_sambungan(d) for d in dependant.dependencies)


def _rute_api(routes) -> list[APIRoute]:
    keluar: list[APIRoute] = []
    for r in routes:
        induk = getattr(r, "original_router", None)
        if induk is not None:
            keluar += _rute_api(induk.routes)
        elif isinstance(r, APIRoute):
            keluar.append(r)
    return keluar


@pytest.mark.parametrize("rute", _rute_api(api.routes), ids=lambda r: f"{r.path}")
def test_setiap_rute_basis_data_menutup_transaksinya_lebih_dulu(rute: APIRoute):
    if rute.path in TANPA_BASIS_DATA:
        return
    assert _memakai_sambungan(rute.dependant), (
        f"{rute.path} tidak menyentuh basis data, daftarkan di TANPA_BASIS_DATA"
    )
    assert isinstance(rute, CommitBeforeResponse), (
        f"{rute.path} memakai APIRouter tanpa route_class=CommitBeforeResponse, "
        "jadi tulisannya baru tersimpan setelah klien menerima balasan"
    )
