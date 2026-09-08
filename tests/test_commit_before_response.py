from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.db import conn
from app.main import api
from app.routes import CommitBeforeResponse

WITHOUT_DATABASE = {"/health"}


class FakeTransaction:
    def __init__(self, trail: list[str]) -> None:
        self.trail = trail
        self.is_active = True

    async def commit(self) -> None:
        self.is_active = False
        self.trail.append("commit")

    async def rollback(self) -> None:
        self.is_active = False
        self.trail.append("rollback")


class TrailingResponse(Response):
    def __init__(self, trail: list[str], status_code: int) -> None:
        super().__init__(status_code=status_code)
        self.trail = trail

    async def __call__(self, scope, receive, send) -> None:
        self.trail.append("response sent")
        await super().__call__(scope, receive, send)


def build(trail: list[str], *, route_class: type[APIRoute], explode: bool = False) -> FastAPI:
    async def connection(request: Request) -> AsyncIterator[FakeTransaction]:
        tx = FakeTransaction(trail)
        request.state.tx = tx
        try:
            yield tx
        except BaseException:
            if tx.is_active:
                await tx.rollback()
            raise
        if tx.is_active:
            await tx.commit()

    router = APIRouter(route_class=route_class)

    @router.post("/write")
    async def write(tx: FakeTransaction = Depends(connection)) -> Response:
        if explode:
            raise RuntimeError("failed halfway through")
        return TrailingResponse(trail, 201)

    app = FastAPI()
    app.include_router(router)
    return app


def test_the_transaction_closes_before_the_client_gets_a_reply():
    trail: list[str] = []
    client = TestClient(build(trail, route_class=CommitBeforeResponse))

    assert client.post("/write").status_code == 201
    assert trail == ["commit", "response sent"], (
        "the commit has to finish before the reply goes out, or the client can read "
        "back over another connection before its own write is visible"
    )


def test_a_plain_route_replies_before_committing():
    trail: list[str] = []
    client = TestClient(build(trail, route_class=APIRoute))

    assert client.post("/write").status_code == 201
    assert trail == ["response sent", "commit"], (
        "this is the FastAPI default that caused the problem, pinned here so a "
        "change in its behaviour shows up"
    )


def test_a_failure_is_still_rolled_back():
    trail: list[str] = []
    client = TestClient(
        build(trail, route_class=CommitBeforeResponse, explode=True),
        raise_server_exceptions=False,
    )

    assert client.post("/write").status_code == 500
    assert trail == ["rollback"]


def _uses_connection(dependant) -> bool:
    if dependant.call is conn:
        return True
    return any(_uses_connection(d) for d in dependant.dependencies)


def _api_routes(routes) -> list[APIRoute]:
    found: list[APIRoute] = []
    for route in routes:
        parent = getattr(route, "original_router", None)
        if parent is not None:
            found += _api_routes(parent.routes)
        elif isinstance(route, APIRoute):
            found.append(route)
    return found


@pytest.mark.parametrize("route", _api_routes(api.routes), ids=lambda r: f"{r.path}")
def test_every_database_route_closes_its_transaction_first(route: APIRoute):
    if route.path in WITHOUT_DATABASE:
        return
    assert _uses_connection(route.dependant), (
        f"{route.path} does not touch the database, list it in WITHOUT_DATABASE"
    )
    assert isinstance(route, CommitBeforeResponse), (
        f"{route.path} uses an APIRouter without route_class=CommitBeforeResponse, so "
        "its writes only land after the client has the reply"
    )
