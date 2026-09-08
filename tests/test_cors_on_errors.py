import importlib

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

import app.config
import app.main

ORIGIN = "http://localhost:5173"


@pytest.fixture(autouse=True)
def restore_module():
    yield
    app.config.settings.cache_clear()
    importlib.reload(app.main)


def build(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", ORIGIN)
    app.config.settings.cache_clear()
    return importlib.reload(app.main)


def test_cors_wraps_the_error_handler(monkeypatch):
    main = build(monkeypatch)
    names = [m.cls for m in main.api.user_middleware]
    assert names[0] is CORSMiddleware, (
        "CORSMiddleware has to sit outermost; otherwise a 500 goes out without CORS "
        "headers and the browser reports it as a CORS problem"
    )


def test_a_server_error_still_carries_cors_headers(monkeypatch):
    main = build(monkeypatch)

    @main.api.get("/__explode")
    async def explode():
        raise RuntimeError("pretend this failed")

    client = TestClient(main.api, raise_server_exceptions=False)
    res = client.get("/__explode", headers={"Origin": ORIGIN})

    assert res.status_code == 500
    assert res.headers.get("access-control-allow-origin") == ORIGIN
    assert res.json()["detail"]["code"] == "internal"
