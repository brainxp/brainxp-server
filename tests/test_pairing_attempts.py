import uuid
from datetime import timedelta

import pytest
from sqlalchemy.dialects import postgresql

from app import queue as Q
from app import schemas as S
from app.errors import AppError
from app.routers import families
from app.security import now
from app.services import pairing as PC

LIVE_CODE = "418205"


def label(statement) -> tuple[str, str]:
    kind = statement.__visit_name__
    if kind == "select":
        froms = statement.get_final_froms()
        return kind, froms[0].name if froms else "?"
    return kind, statement.table.name


def rendered(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


class Reply:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)

    def scalar_one(self):
        return self.rows[0]


class Recorder:
    def __init__(self, replies=None):
        self.replies = replies or {}
        self.statements: list[object] = []

    async def execute(self, statement, parameters=None):
        self.statements.append(statement)
        return Reply(self.replies.get(label(statement), []))

    @property
    def trail(self) -> list[tuple[str, str]]:
        return [label(s) for s in self.statements]


class OwnConnection:
    def __init__(self, engine):
        self.engine = engine

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement, parameters=None):
        self.engine.statements.append(statement)
        return Reply([self.engine.attempts])

    async def commit(self):
        self.engine.commits += 1


class FakeEngine:
    def __init__(self, attempts=1):
        self.attempts = attempts
        self.statements: list[object] = []
        self.commits = 0

    def connect(self):
        return OwnConnection(self)


class FakeRedis:
    def __init__(self):
        self.counts: dict[str, int] = {}

    async def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, seconds):
        return True


class FakeRequest:
    client = None

    def __init__(self):
        self.headers: dict[str, str] = {}


@pytest.fixture(autouse=True)
def redis_without_a_server(monkeypatch):
    def client():
        return FakeRedis()

    monkeypatch.setattr(Q, "redis", client)


@pytest.fixture
def counter(monkeypatch):
    engine = FakeEngine()

    def own():
        return engine

    monkeypatch.setattr(PC, "engine", own)
    return engine


def code_row(**overrides) -> dict:
    row = {
        "code": LIVE_CODE,
        "subject_id": uuid.uuid4(),
        "family_id": uuid.uuid4(),
        "issued_by": uuid.uuid4(),
        "consumed_at": None,
        "expires_at": now() + timedelta(minutes=5),
        "attempt_count": 0,
    }
    return row | overrides


def pair_body() -> S.PairIn:
    return S.PairIn(
        code=LIVE_CODE, install_binding="install-7f3a9c2b41d5",
        platform="android", model_name="Pixel 6a",
    )


async def pair(db, counter) -> AppError | None:
    try:
        await families.pair_device(pair_body(), db, FakeRequest())
    except AppError as refusal:
        return refusal
    return None


def test_the_advertised_allowance_is_the_one_being_enforced():
    assert PC.MAX_ATTEMPTS == 5
    assert PC.burned(PC.MAX_ATTEMPTS) is False
    assert PC.burned(PC.MAX_ATTEMPTS + 1) is True, (
        "count_attempt returns the count including the attempt under way, so the "
        "fifth attempt still has to be allowed through"
    )


async def test_the_attempt_is_counted_on_its_own_connection(counter):
    await PC.count_attempt(LIVE_CODE)

    assert counter.commits == 1, (
        "the request runs in one transaction that rolls back the moment the attempt "
        "is refused, taking the count with it; the count only survives if it is "
        "committed separately"
    )


async def test_the_count_comes_back_from_the_database(counter):
    counter.attempts = 4

    assert await PC.count_attempt(LIVE_CODE) == 4, (
        "two phones can be trying the same code at once, so the ceiling has to be "
        "checked against the value the database settled on, not one read earlier"
    )


async def test_the_count_is_raised_by_one_and_read_back(counter):
    await PC.count_attempt(LIVE_CODE)

    sql = rendered(counter.statements[0])
    assert "attempt_count + " in sql
    assert "RETURNING" in sql


async def test_a_code_past_its_allowance_is_refused(counter):
    counter.attempts = PC.MAX_ATTEMPTS + 1
    db = Recorder({("select", "pairing_codes"): [code_row()]})

    refusal = await pair(db, counter)

    assert refusal is not None
    assert refusal.status_code == 409
    assert refusal.detail["code"] == "code_burned"
    assert ("insert", "devices") not in db.trail, (
        "a burned code must not hand out a device row or a token"
    )


async def test_a_spent_code_still_burns_through_its_allowance(counter):
    db = Recorder({("select", "pairing_codes"): [code_row(consumed_at=now())]})

    refusal = await pair(db, counter)

    assert refusal.detail["code"] == "code_used"
    assert counter.commits == 1, (
        "counting only the attempts that pass every check leaves the ceiling "
        "unreachable, which is how attempt_count stayed at one on every row"
    )


async def test_an_expired_code_still_burns_through_its_allowance(counter):
    db = Recorder({
        ("select", "pairing_codes"): [code_row(expires_at=now() - timedelta(minutes=1))],
    })

    refusal = await pair(db, counter)

    assert refusal.detail["code"] == "code_expired"
    assert counter.commits == 1


async def test_a_code_that_does_not_exist_costs_no_allowance(counter):
    db = Recorder()

    refusal = await pair(db, counter)

    assert refusal.status_code == 404
    assert counter.commits == 0, (
        "a wrong six digit entry matches no row at all; there is nothing to charge "
        "it against, and the per IP limiter is what answers guessing"
    )


async def test_a_code_within_its_allowance_still_pairs(counter):
    db = Recorder({
        ("select", "pairing_codes"): [code_row()],
        ("insert", "devices"): [uuid.uuid4()],
    })

    assert await pair(db, counter) is None
    assert ("insert", "devices") in db.trail
