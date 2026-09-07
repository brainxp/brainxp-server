from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx2
import jwt
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app import tables as T
from app.config import settings
from app.security import now

log = logging.getLogger("brainxp.push")

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
ASSERTION_LIFETIME = 3600
EARLY_REFRESH = 120
SEND_TIMEOUT = 10.0
UNREGISTERED = 404


@dataclass(frozen=True)
class Notification:
    title: str
    body: str
    data: dict[str, str] = field(default_factory=dict)


class PushSender(Protocol):
    async def send(self, tokens: list[str], note: Notification) -> list[str]: ...


def read_credentials(raw: str) -> dict[str, Any]:
    if raw.lstrip().startswith("{"):
        return json.loads(raw)
    path = Path(raw)
    if not path.is_file():
        raise RuntimeError("FCM_SERVICE_ACCOUNT is neither inline JSON nor a readable file.")
    return json.loads(path.read_text())


class FcmSender:
    def __init__(self) -> None:
        s = settings()
        creds = read_credentials(s.fcm_service_account)
        absent = [k for k in ("client_email", "private_key", "token_uri") if not creds.get(k)]
        if absent:
            raise RuntimeError(f"FCM service account is missing {', '.join(absent)}.")
        self._creds = creds
        self._project = s.fcm_project_id
        self._bearer = ""
        self._bearer_until = 0.0

    @property
    def endpoint(self) -> str:
        return f"https://fcm.googleapis.com/v1/projects/{self._project}/messages:send"

    def assertion(self, *, at: float) -> str:
        return jwt.encode(
            {
                "iss": self._creds["client_email"],
                "scope": SCOPE,
                "aud": self._creds["token_uri"],
                "iat": int(at),
                "exp": int(at) + ASSERTION_LIFETIME,
            },
            self._creds["private_key"],
            algorithm="RS256",
        )

    def envelope(self, token: str, note: Notification) -> dict[str, Any]:
        return {
            "message": {
                "token": token,
                "notification": {"title": note.title, "body": note.body},
                "data": {k: str(v) for k, v in note.data.items()},
                "android": {"priority": "high"},
            }
        }

    async def authorize(self, client: httpx2.AsyncClient, *, at: float) -> str:
        if self._bearer and at < self._bearer_until:
            return self._bearer
        resp = await client.post(
            self._creds["token_uri"],
            data={"grant_type": GRANT, "assertion": self.assertion(at=at)},
        )
        resp.raise_for_status()
        granted = resp.json()
        self._bearer = granted["access_token"]
        self._bearer_until = at + int(granted.get("expires_in", ASSERTION_LIFETIME)) - EARLY_REFRESH
        return self._bearer

    async def send(self, tokens: list[str], note: Notification) -> list[str]:
        if not tokens:
            return []
        dead: list[str] = []
        async with httpx2.AsyncClient(timeout=SEND_TIMEOUT) as client:
            bearer = await self.authorize(client, at=time.time())
            for token in tokens:
                resp = await client.post(
                    self.endpoint,
                    json=self.envelope(token, note),
                    headers={"Authorization": f"Bearer {bearer}"},
                )
                if resp.status_code == UNREGISTERED:
                    dead.append(token)
                elif resp.status_code >= 300:
                    log.warning(
                        "FCM refused a message (%s): %s", resp.status_code, resp.text[:200]
                    )
        if dead:
            log.info("%d push token(s) are no longer registered", len(dead))
        return dead


class StubSender:
    def __init__(self) -> None:
        self.sent: list[tuple[list[str], Notification]] = []

    async def send(self, tokens: list[str], note: Notification) -> list[str]:
        self.sent.append((list(tokens), note))
        log.info("push (stub) to %d token(s): %s", len(tokens), note.title)
        return []


_sender: PushSender | None = None


def sender() -> PushSender:
    global _sender
    if _sender is None:
        _sender = FcmSender() if settings().push_enabled else StubSender()
        log.info("push sender: %s", type(_sender).__name__)
    return _sender


async def remember(
    db: AsyncConnection, *, token: str, platform: str,
    user_id: uuid.UUID | None, device_id: uuid.UUID | None,
) -> None:
    stmt = pg_insert(T.push_tokens).values(
        token=token, platform=platform, user_id=user_id, device_id=device_id,
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[T.push_tokens.c.token],
            set_={
                "user_id": stmt.excluded.user_id,
                "device_id": stmt.excluded.device_id,
                "platform": stmt.excluded.platform,
                "last_seen_at": now(),
                "revoked_at": None,
            },
        )
    )


def owned_by(*, user_id: uuid.UUID | None, device_id: uuid.UUID | None):
    if device_id is not None:
        return T.push_tokens.c.device_id == device_id
    return T.push_tokens.c.user_id == user_id


async def forget(
    db: AsyncConnection, *, token: str,
    user_id: uuid.UUID | None, device_id: uuid.UUID | None,
) -> None:
    await db.execute(
        T.push_tokens.update().where(
            T.push_tokens.c.token == token,
            T.push_tokens.c.revoked_at.is_(None),
            owned_by(user_id=user_id, device_id=device_id),
        ).values(revoked_at=now())
    )


async def revoke_devices(db: AsyncConnection, device_ids: Sequence[uuid.UUID]) -> None:
    if not device_ids:
        return
    await db.execute(
        T.push_tokens.update().where(
            T.push_tokens.c.device_id.in_(device_ids),
            T.push_tokens.c.revoked_at.is_(None),
        ).values(revoked_at=now())
    )


async def prune(db: AsyncConnection, tokens: Sequence[str]) -> None:
    if not tokens:
        return
    await db.execute(
        T.push_tokens.update().where(
            T.push_tokens.c.token.in_(tokens),
            T.push_tokens.c.revoked_at.is_(None),
        ).values(revoked_at=now())
    )


def guardian_users(subject_id: uuid.UUID):
    parents = (
        select(T.family_members.c.user_id)
        .join(T.subjects, T.subjects.c.family_id == T.family_members.c.family_id)
        .where(T.subjects.c.id == subject_id, T.family_members.c.role == "parent")
    )
    owner = select(T.subjects.c.user_id).where(
        T.subjects.c.id == subject_id, T.subjects.c.user_id.isnot(None)
    )
    return parents.union(owner)


async def recipients(db: AsyncConnection, subject_id: uuid.UUID) -> list[str]:
    rows = (
        await db.execute(
            select(T.push_tokens.c.token).where(
                T.push_tokens.c.revoked_at.is_(None),
                T.push_tokens.c.user_id.in_(guardian_users(subject_id)),
            )
        )
    ).all()
    return [r[0] for r in rows]
