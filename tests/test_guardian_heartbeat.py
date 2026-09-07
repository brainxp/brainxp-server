import inspect
import uuid

import pytest

from app import schemas as S
from app import worker
from app.errors import AppError
from app.routers import families
from app.services import guardian as G
from tests.conftest import Recorder, rendered


class Device:
    role = "child"
    user_id = None
    is_parent = False
    is_child = True

    def __init__(self):
        self.subject_id = uuid.uuid4()
        self.device_id = uuid.uuid4()


class Parent:
    role = "parent"
    device_id = None
    subject_id = None
    is_parent = True
    is_child = False

    def __init__(self):
        self.user_id = uuid.uuid4()


class Tasks:
    def __init__(self):
        self.queued: list[tuple[object, tuple, dict]] = []

    def add_task(self, fn, *args, **kwargs):
        self.queued.append((fn, args, kwargs))


def beat(status: str = "ok", events: list[dict] | None = None) -> S.HeartbeatIn:
    return S.HeartbeatIn(guardian_status=status, events=events or [])


def db_with(previous: str, opened: int | None = 9) -> Recorder:
    return Recorder({
        ("select", "devices"): [previous],
        ("insert", "guardian_alerts"): [opened] if opened is not None else [],
    })


async def test_only_a_paired_device_may_report():
    db = Recorder()

    with pytest.raises(AppError) as refused:
        await families.heartbeat(beat(), db, Parent(), Tasks())

    assert refused.value.status_code == 403
    assert db.trail == []


async def test_a_heartbeat_still_records_the_status_and_the_time():
    db = db_with("ok")

    await families.heartbeat(beat("ok"), db, Device(), Tasks())

    stmt, _ = db.only("update", "devices")
    sql = rendered(stmt)
    assert "guardian_status" in sql and "last_heartbeat_at" in sql


async def test_a_heartbeat_clears_the_silence_alert():
    db = db_with("ok")

    await families.heartbeat(beat("ok"), db, Device(), Tasks())

    updates = [s for s, _ in db.calls if rendered(s).startswith("UPDATE guardian_alerts")]
    assert updates, "the phone is talking again, so device_silent has to stop being open"
    assert G.DEVICE_SILENT in rendered(updates[0], literals=True)


async def test_protection_dropping_raises_an_alert_and_queues_one_push():
    tasks = Tasks()
    db = db_with("ok")

    await families.heartbeat(beat("disabled"), db, Device(), tasks)

    stmt, _ = db.only("insert", "guardian_alerts")
    assert G.PROTECTION_DISABLED in rendered(stmt, literals=True)
    assert len(tasks.queued) == 1
    _, _, payload = tasks.queued[0]
    assert payload["kind"] == G.PROTECTION_DISABLED
    assert payload["alert_id"] == 9


async def test_a_phone_that_keeps_reporting_disabled_is_not_a_new_alert_each_time():
    tasks = Tasks()
    db = db_with("disabled")

    await families.heartbeat(beat("disabled"), db, Device(), tasks)

    assert ("insert", "guardian_alerts") not in db.trail, (
        "the state did not change, so there is nothing new to tell anyone"
    )
    assert tasks.queued == []


async def test_an_alert_already_open_does_not_queue_a_second_push():
    tasks = Tasks()
    db = db_with("ok", opened=None)

    await families.heartbeat(beat("disabled"), db, Device(), tasks)

    assert tasks.queued == [], (
        "the insert conflicted with an alert still open, and pushing again is "
        "exactly the duplicate notification the alert table exists to prevent"
    )


async def test_protection_coming_back_resolves_the_alert():
    tasks = Tasks()
    db = db_with("disabled")

    await families.heartbeat(beat("ok"), db, Device(), tasks)

    resolved = [
        rendered(s, literals=True) for s, _ in db.calls
        if rendered(s).startswith("UPDATE guardian_alerts")
    ]
    assert any(G.PROTECTION_DISABLED in sql for sql in resolved)
    assert tasks.queued == []


async def test_a_revoked_permission_raises_the_matching_kind():
    tasks = Tasks()
    db = db_with("ok")

    await families.heartbeat(
        beat("degraded", [{"type": G.REVOKED, "permission": "usage_access", "required": True}]),
        db, Device(), tasks,
    )

    kinds = {p["kind"] for _, _, p in tasks.queued}
    assert G.USAGE_ACCESS_OFF in kinds
    assert G.PROTECTION_DISABLED in kinds, (
        "the status moved as well, and the two say different things to a parent: "
        "one names the permission, the other says protection is off"
    )


async def test_a_restored_permission_resolves_its_alert():
    tasks = Tasks()
    db = db_with("ok")

    await families.heartbeat(
        beat("ok", [{"type": G.RESTORED, "permission": "overlay"}]), db, Device(), tasks,
    )

    resolved = [
        rendered(s, literals=True) for s, _ in db.calls
        if rendered(s).startswith("UPDATE guardian_alerts")
    ]
    assert any(G.OVERLAY_OFF in sql for sql in resolved)
    assert tasks.queued == [], "a permission coming back is not worth waking a parent"


async def test_every_event_is_still_written_to_the_audit_log():
    db = db_with("ok")

    await families.heartbeat(
        beat("ok", [{"type": "screen_unlocked"}, {"type": G.RESTORED, "permission": "overlay"}]),
        db, Device(), Tasks(),
    )

    logged = [s for s, _ in db.calls if rendered(s).startswith("INSERT INTO guardian_events")]
    assert len(logged) == 2


async def test_an_event_the_server_does_not_know_is_kept_but_raises_nothing():
    tasks = Tasks()
    db = db_with("ok")

    await families.heartbeat(
        beat("ok", [{"type": G.REVOKED, "permission": "camera"}]), db, Device(), tasks,
    )

    assert ("insert", "guardian_events") in db.trail
    assert ("insert", "guardian_alerts") not in db.trail
    assert tasks.queued == []


async def test_a_heartbeat_survives_an_event_shape_the_server_has_never_seen():
    db = db_with("ok")

    body = beat("ok", [{"type": "battery_saver_on", "level": 4, "note": "anything"}])

    await families.heartbeat(body, db, Device(), Tasks())

    stmt, _ = db.only("update", "devices")
    assert "guardian_status" in rendered(stmt), (
        "a heartbeat is what keeps the balance unfrozen; rejecting the whole report "
        "over one unrecognised event would punish the child for a client update"
    )


def test_an_unknown_field_is_carried_into_the_payload():
    event = S.GuardianEventIn(type="battery_saver_on", level=4)
    assert event.model_dump()["level"] == 4, (
        "the audit log was free form before this schema; narrowing it would throw "
        "away whatever the client learns to report next"
    )


async def test_only_a_bounded_number_of_events_is_accepted():
    db = db_with("ok")

    await families.heartbeat(
        beat("ok", [{"type": "noise"}] * 200), db, Device(), Tasks(),
    )

    logged = [s for s, _ in db.calls if rendered(s).startswith("INSERT INTO guardian_events")]
    assert len(logged) == families.EVENT_LIMIT, (
        "the body is unauthenticated input from a phone the child controls"
    )


def test_the_push_job_reaches_the_queue_only_after_the_transaction_closes():
    source = inspect.getsource(families.heartbeat)
    assert "tasks.add_task(" in source
    assert "await Q.enqueue(" not in source, (
        "the worker reads the alert row by id; enqueued inline it can look before "
        "the insert is committed"
    )


def test_the_worker_knows_how_to_deliver_a_queued_alert():
    assert "guardian_push" in worker.HANDLERS


def test_the_watchdog_keeps_running_after_a_failed_sweep():
    source = inspect.getsource(worker.watch_for_silence)
    assert "log.exception" in source and "while not stop.is_set()" in source, (
        "a watchdog that dies on one bad tick is worse than none: every client side "
        "alert can be silenced by force stopping the app, and this is the backstop"
    )
