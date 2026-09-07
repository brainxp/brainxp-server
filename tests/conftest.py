import pytest
from sqlalchemy.dialects import postgresql

from app import queue as Q
from app.services import pairing as PC


def label(statement) -> tuple[str, str]:
    kind = statement.__visit_name__
    if kind == "select":
        froms = statement.get_final_froms()
        return kind, froms[0].name if froms else "?"
    return kind, statement.table.name


def rendered(statement, *, literals: bool = False) -> str:
    kwargs = {"literal_binds": True} if literals else {}
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs=kwargs))


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
        self.calls: list[tuple[object, object]] = []

    async def execute(self, statement, parameters=None):
        self.calls.append((statement, parameters))
        return Reply(self.replies.get(label(statement), []))

    @property
    def trail(self) -> list[tuple[str, str]]:
        return [label(s) for s, _ in self.calls]

    def only(self, kind: str, table: str):
        found = [(s, p) for s, p in self.calls if label(s) == (kind, table)]
        assert len(found) == 1, f"expected one {kind} on {table}, got {len(found)}"
        return found[0]


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


@pytest.fixture(autouse=True)
def counter(monkeypatch):
    engine = FakeEngine()

    def own():
        return engine

    monkeypatch.setattr(PC, "engine", own)
    return engine
