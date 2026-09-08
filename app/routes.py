from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute


class CommitBeforeResponse(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handle = super().get_route_handler()

        async def commit_then_send(request: Request) -> Response:
            response = await handle(request)
            tx = getattr(request.state, "tx", None)
            if tx is not None and tx.is_active:
                await tx.commit()
            return response

        return commit_then_send
