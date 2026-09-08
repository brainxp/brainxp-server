from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import settings
from app.errors import Unauthorized

_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def hash_password(raw: str) -> str:
    return _ph.hash(raw)


def verify_password(stored: str, raw: str) -> bool:
    try:
        return _ph.verify(stored, raw)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def needs_rehash(stored: str) -> bool:
    try:
        return _ph.check_needs_rehash(stored)
    except Exception:
        return False


def now() -> datetime:
    return datetime.now(UTC)


def issue_access_token(
    *, user_id: str | None, subject_id: str | None, role: str, device_id: str | None = None
) -> tuple[str, int]:
    s = settings()
    ttl = s.access_ttl_seconds
    payload: dict[str, Any] = {
        "sub": user_id or subject_id,
        "uid": user_id,
        "sid": subject_id,
        "role": role,
        "did": device_id,
        "iat": int(now().timestamp()),
        "exp": int((now() + timedelta(seconds=ttl)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, s.signing_key, algorithm="HS256"), ttl


def read_access_token(token: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(token, settings().signing_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Token akses sudah kedaluwarsa.") from None
    except jwt.PyJWTError:
        raise Unauthorized("Token akses tidak sah.") from None
    if claims.get("typ") != "access":
        raise Unauthorized("Jenis token salah.")
    return claims


def new_opaque_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, sha256(raw)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_chain_id() -> uuid.UUID:
    return uuid.uuid4()


def new_pairing_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def new_device_secret() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, sha256(raw)


def answer_hmac(*, question_id: str, correct_index: int, device_secret: str) -> str:
    msg = f"{question_id}:{correct_index}".encode()
    return hmac.new(device_secret.encode(), msg, hashlib.sha256).hexdigest()
