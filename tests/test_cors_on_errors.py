import importlib

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

import app.config
import app.main

ORIGIN = "http://localhost:5173"


@pytest.fixture(autouse=True)
def pulihkan_modul():
    yield
    app.config.settings.cache_clear()
    importlib.reload(app.main)


def build(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", ORIGIN)
    app.config.settings.cache_clear()
    return importlib.reload(app.main)


def test_cors_membungkus_penangan_galat(monkeypatch):
    main = build(monkeypatch)
    names = [m.cls for m in main.api.user_middleware]
    assert names[0] is CORSMiddleware, (
        "CORSMiddleware harus paling luar; kalau tidak, respons 500 keluar tanpa "
        "header CORS dan browser melaporkannya sebagai masalah CORS"
    )


def test_galat_server_tetap_membawa_header_cors(monkeypatch):
    main = build(monkeypatch)

    @main.api.get("/__meledak")
    async def meledak():
        raise RuntimeError("pura-pura gagal")

    client = TestClient(main.api, raise_server_exceptions=False)
    res = client.get("/__meledak", headers={"Origin": ORIGIN})

    assert res.status_code == 500
    assert res.headers.get("access-control-allow-origin") == ORIGIN
    assert res.json()["detail"]["code"] == "internal"
