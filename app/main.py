from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import queue as Q
from app.config import settings, weak_secret_reason
from app.db import dispose, engine
from app.routers import apps, auth, families, ledger, materials, policies, quizzes, reports

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
)
log = logging.getLogger("brainxp")


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = settings()
    log.info("BrainXP API up · env=%s · llm=%s", s.app_env,
             "anthropic" if s.llm_enabled else "stub")
    weak = weak_secret_reason(s.app_env, s.jwt_secret)
    if weak:
        raise RuntimeError(f"{weak} Set it to 64 random characters before running in production.")
    if not s.jwt_secret:
        log.warning("JWT_SECRET is empty, falling back to a throwaway key. Tokens die on restart.")
    engine()
    yield
    await Q.close()
    await dispose()


api = FastAPI(
    title="BrainXP",
    version="0.1.0",
    summary="Kartu waktu bermain yang dicetak dari materi belajar",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

@api.middleware("http")
async def security_headers(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        response = JSONResponse(
            status_code=500,
            content={"detail": {"code": "internal", "message": "Terjadi galat di server."}},
        )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


if settings().origins:
    api.add_middleware(
        CORSMiddleware,
        allow_origins=settings().origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@api.get("/health", tags=["ops"])
async def health():
    return {"status": "ok", "llm": "anthropic" if settings().llm_enabled else "stub"}


for r in (auth, families, policies, apps, materials, quizzes, ledger, reports):
    api.include_router(r.router)
