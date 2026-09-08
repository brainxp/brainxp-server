import uuid
from datetime import timedelta

import pytest

from app.errors import AppError
from app.routers import guardian as R
from app.security import now
from app.services import guardian as G
from tests.conftest import Recorder, rendered


class Parent:
    role = "parent"
    device_id = None
    is_parent = True
    is_child = False

    def __init__(self):
        self.user_id = uuid.uuid4()
        self.subject_id = None


class Child:
    role = "child"
    user_id = None
    is_parent = False
    is_child = True

    def __init__(self, subject_id=None):
        self.subject_id = subject_id or uuid.uuid4()
        self.device_id = uuid.uuid4()


def alert_row(**overrides) -> dict:
    row = {
        "id": 41,
        "subject_id": uuid.uuid4(),
        "device_id": uuid.uuid4(),
        "kind": G.ACCESSIBILITY_OFF,
        "detail": "Izin aksesibilitas dicabut di ponsel anak.",
        "created_at": now(),
        "acknowledged_at": None,
        "resolved_at": None,
        "display_name": "Dimas",
    }
    return row | overrides


def subject_row(**overrides) -> dict:
    row = {
        "id": uuid.uuid4(),
        "family_id": uuid.uuid4(),
        "user_id": None,
        "display_name": "Dimas",
        "kind": "child",
        "academic_level": "smp",
        "deleted_at": None,
    }
    return row | overrides


def test_every_kind_the_api_names_is_a_kind_the_server_can_raise():
    from app import schemas as S

    declared = set(S.AlertKind.__args__)
    assert declared == set(G.KINDS), (
        "the parent app switches on kind to pick an icon and a copy string, so a "
        "kind the server can write but the schema cannot name would render blank"
    )


def test_every_kind_has_something_to_show_in_a_notification():
    missing = [k for k in G.KINDS if k not in G.HEADLINES or k not in G.BODIES]
    assert not missing, f"kinds with no push copy: {missing}"


@pytest.mark.parametrize("kind", G.KINDS)
def test_a_notification_says_whose_phone_it_is(kind):
    title, body = G.notification_text(kind, "Rozan")
    assert "Rozan" in f"{title} {body}", (
        "a parent with two children cannot act on a warning that never says which "
        "phone broke"
    )


@pytest.mark.parametrize("kind", G.KINDS)
def test_a_notification_body_is_not_the_headline_said_twice(kind):
    title, body = G.notification_text(kind, "Rozan")
    assert body, f"{kind} arrives with an empty body"
    assert body != title
    assert title.rstrip(".") not in body, (
        f"{kind} spends the body repeating the title and tells the parent nothing new"
    )


@pytest.mark.parametrize("kind", G.KINDS)
def test_a_notification_never_calls_the_child_the_child(kind):
    title, body = G.notification_text(kind, "Rozan")
    assert "anak" not in f"{title} {body}".lower(), (
        "the subject has a name and the server already knows it"
    )


@pytest.mark.parametrize("kind", sorted(G.PERMISSION_KINDS.values()))
def test_a_revoked_permission_says_how_to_put_it_back(kind):
    _, body = G.notification_text(kind, "Rozan")
    assert "Nyalakan" in body, (
        "a parent who reads that a permission is gone still has to be told where to "
        "turn it on"
    )


def test_the_line_written_for_the_feed_does_not_become_the_push_body():
    detail = G.revoked_detail("accessibility")
    _, body = G.notification_text(G.ACCESSIBILITY_OFF, "Rozan", detail=detail)
    assert body != detail, (
        "the detail is the one-line summary the alert list shows under a heading "
        "that already names the kind; sent as the push body it drops the name, the "
        "consequence, and the fix"
    )


def test_a_silent_phone_pushes_how_long_it_has_been_quiet():
    at = now()
    detail = G.silence_detail(at - timedelta(minutes=22), at)
    _, body = G.notification_text(G.DEVICE_SILENT, "Rozan", detail=detail)
    assert "22 menit" in body
    assert "dibekukan" in body, "how long it has been quiet is only half the news"


def test_an_unknown_kind_still_reads_as_a_sentence():
    title, body = G.notification_text("something_new", "Rozan")
    assert "Rozan" in title and body and "{" not in f"{title} {body}"


def test_every_permission_maps_onto_a_kind():
    assert set(G.PERMISSION_KINDS.values()) <= set(G.KINDS)
    assert set(G.PERMISSION_KINDS) == set(G.PERMISSION_LABELS), (
        "a permission the client can report but the server cannot label would reach "
        "a parent as a blank sentence"
    )


async def test_an_alert_is_only_raised_once_while_it_stays_open():
    db = Recorder({("insert", "guardian_alerts"): [5]})

    await G.raise_alert(db, subject_id=uuid.uuid4(), kind=G.DEVICE_SILENT)

    stmt, _ = db.only("insert", "guardian_alerts")
    sql = rendered(stmt)
    assert "ON CONFLICT (subject_id, kind) WHERE" in sql
    assert "acknowledged_at IS NULL AND resolved_at IS NULL DO NOTHING" in sql, (
        "the predicate has to match guardian_alerts_open_idx exactly, or Postgres "
        "cannot infer the index and the insert raises instead of deduping"
    )
    assert "RETURNING" in sql, (
        "a conflicting insert returns no row, and that is how the caller knows not "
        "to send a second push for trouble already reported"
    )


async def test_a_second_report_of_the_same_trouble_is_not_a_second_alert():
    db = Recorder()

    assert await G.raise_alert(db, subject_id=uuid.uuid4(), kind=G.DEVICE_SILENT) is None, (
        "an insert that conflicts returns no id, and that is the signal not to push "
        "again; the parent app cannot dedupe what it was already notified about"
    )


async def test_a_resolved_alert_can_be_raised_again_later():
    sql = rendered(G.still_open())
    assert "acknowledged_at IS NULL" in sql and "resolved_at IS NULL" in sql, (
        "acknowledging or resolving has to take the row out of the unique index, or "
        "the same trouble could never be reported a second time"
    )


async def test_resolving_nothing_writes_nothing():
    db = Recorder()
    await G.resolve(db, subject_id=uuid.uuid4(), kinds=[])
    assert db.trail == []


async def test_resolving_only_touches_alerts_that_are_still_open():
    db = Recorder()

    await G.resolve(db, subject_id=uuid.uuid4(), kinds=[G.OVERLAY_OFF])

    stmt, _ = db.only("update", "guardian_alerts")
    sql = rendered(stmt)
    assert "resolved_at" in sql
    assert "acknowledged_at IS NULL" in sql, (
        "an alert the parent already read must keep its acknowledged state instead "
        "of being rewritten as resolved"
    )


def test_protection_is_reported_on_the_way_down_only():
    assert G.protection_lost("ok", "disabled")
    assert G.protection_lost("unknown", "degraded")
    assert not G.protection_lost("degraded", "disabled"), (
        "a phone that keeps reporting degraded sends a heartbeat every few minutes; "
        "alerting each time would be a push notification every few minutes"
    )
    assert not G.protection_lost("ok", "ok")


def test_protection_coming_back_is_recognised():
    assert G.protection_regained("disabled", "ok")
    assert not G.protection_regained("disabled", "degraded"), (
        "half repaired is still broken, so the alert stays open"
    )
    assert not G.protection_regained("ok", "ok")


def test_the_silence_detail_counts_whole_minutes_in_indonesian():
    at = now()
    assert G.silence_detail(at - timedelta(minutes=22), at) == (
        "Sudah 22 menit tidak ada kabar dari ponselnya."
    )
    assert G.silence_detail(at, at) == "Sudah 1 menit tidak ada kabar dari ponselnya.", (
        "a zero would read as though the phone were fine"
    )


def test_the_alert_threshold_is_never_tighter_than_the_freeze():
    assert G.HEARTBEAT_SILENCE >= G.HEARTBEAT_GRACE, (
        "the balance freezes after HEARTBEAT_GRACE; alerting earlier than that would "
        "tell a parent something is wrong while the child can still play"
    )


def test_the_watchdog_ignores_phones_it_should_not_report():
    sql = rendered(G.silent_devices(now() - G.HEARTBEAT_SILENCE))
    assert "devices.unbound_at IS NULL" in sql, "a released phone is nobody's problem"
    assert "subjects.deleted_at IS NULL" in sql, "a deleted profile must not raise alerts"
    assert "devices.last_heartbeat_at IS NOT NULL" in sql, (
        "a phone that has never reported has no silence to measure"
    )


def test_the_watchdog_raises_one_alert_per_stretch_of_silence():
    sql = rendered(G.silent_devices(now() - G.HEARTBEAT_SILENCE))
    assert "NOT (EXISTS" in sql, (
        "acknowledging lifts the row out of the open index, so without this the "
        "sweep would raise a fresh alert and push again on its next tick, every "
        "couple of minutes, to a parent who had already read it"
    )
    assert "guardian_alerts.created_at > devices.last_heartbeat_at" in sql, (
        "the stretch of silence is identified by the last report, so a phone that "
        "comes back and goes quiet again is a new alert rather than a suppressed one"
    )


async def test_the_watchdog_sweeps_nothing_when_every_phone_is_reporting():
    db = Recorder()
    assert await G.sweep(db) == 0
    assert db.trail == [("select", "devices")]


async def test_a_silent_phone_raises_one_alert_and_one_push(monkeypatch):
    subject, device = uuid.uuid4(), uuid.uuid4()
    db = Recorder({
        ("select", "devices"): [{
            "id": device, "subject_id": subject,
            "last_heartbeat_at": now() - timedelta(minutes=40),
        }],
        ("insert", "guardian_alerts"): [77],
        ("select", "subjects"): ["Dimas"],
        ("select", "push_tokens"): [("token-abc",)],
    })
    sent = []

    class Sender:
        async def send(self, tokens, note):
            sent.append((tokens, note))
            return []

    monkeypatch.setattr(G.PU, "_sender", Sender())

    assert await G.sweep(db) == 1
    assert len(sent) == 1
    tokens, note = sent[0]
    assert tokens == ["token-abc"]
    assert note.data["kind"] == G.DEVICE_SILENT
    assert note.data["alert_id"] == 77, (
        "the app deep-links to the alert and acknowledges it by id, so the id has to "
        "travel with the notification"
    )
    assert "Dimas" in note.title
    assert note.body.startswith("Sudah 40 menit"), (
        "the watchdog measured the silence, so the push says how long it has been"
    )
    assert "dibekukan" in note.body


async def test_a_push_that_fails_does_not_lose_the_alert(monkeypatch):
    db = Recorder({
        ("select", "subjects"): ["Dimas"],
        ("select", "push_tokens"): [("token-abc",)],
    })

    class Broken:
        async def send(self, tokens, note):
            raise RuntimeError("FCM is down")

    monkeypatch.setattr(G.PU, "_sender", Broken())

    await G.deliver(db, subject_id=uuid.uuid4(), kind=G.DEVICE_SILENT, alert_id=1)

    assert ("update", "push_tokens") not in db.trail, (
        "the alert row is the source of truth and the parent can still see it in the "
        "list; a dead FCM must not take tokens down with it"
    )


async def test_nobody_to_notify_is_not_an_error(monkeypatch):
    db = Recorder({("select", "subjects"): ["Dimas"], ("select", "push_tokens"): []})
    monkeypatch.setattr(G.PU, "_sender", None)

    await G.deliver(db, subject_id=uuid.uuid4(), kind=G.DEVICE_SILENT, alert_id=1)


async def test_a_parent_sees_every_child_in_their_family():
    me = Parent()
    db = Recorder({("select", "guardian_alerts"): [alert_row()]})

    out = await R.list_alerts(db, me)

    assert len(out) == 1
    stmt, _ = db.only("select", "guardian_alerts")
    sql = rendered(stmt, literals=True)
    assert "family_members" in sql and str(me.user_id) in sql
    assert "acknowledged_at IS NULL AND guardian_alerts.resolved_at IS NULL" in sql, (
        "the default feed is what drives the badge, so it defaults to open only"
    )


async def test_a_child_only_ever_sees_their_own():
    me = Child()
    db = Recorder({("select", "guardian_alerts"): []})

    await R.list_alerts(db, me)

    stmt, _ = db.only("select", "guardian_alerts")
    sql = rendered(stmt, literals=True)
    assert str(me.subject_id) in sql
    assert "family_members" not in sql


async def test_the_feed_carries_the_name_the_parent_reads():
    db = Recorder({("select", "guardian_alerts"): [alert_row(display_name="Dimas")]})

    out = await R.list_alerts(db, Parent())

    assert out[0].subject_name == "Dimas", (
        "a parent with three children needs to know which phone this is about "
        "without a second request per alert"
    )


async def test_asking_for_all_statuses_drops_the_filter():
    db = Recorder({("select", "guardian_alerts"): []})

    await R.list_alerts(db, Parent(), status="all")

    stmt, _ = db.only("select", "guardian_alerts")
    assert "resolved_at IS NULL" not in rendered(stmt)


async def test_since_narrows_the_feed():
    cutoff = now() - timedelta(days=1)
    db = Recorder({("select", "guardian_alerts"): []})

    await R.list_alerts(db, Parent(), since=cutoff)

    stmt, _ = db.only("select", "guardian_alerts")
    assert "created_at >=" in rendered(stmt)


async def test_a_missing_alert_is_a_404():
    db = Recorder()

    with pytest.raises(AppError) as gone:
        await R.acknowledge_alert(9, db, Parent())

    assert gone.value.status_code == 404


async def test_a_child_cannot_dismiss_the_alert_about_their_own_phone():
    subject = uuid.uuid4()
    db = Recorder({
        ("select", "guardian_alerts"): [alert_row(subject_id=subject)],
        ("select", "subjects"): [subject_row(id=subject)],
    })

    with pytest.raises(AppError) as refused:
        await R.acknowledge_alert(41, db, Child(subject_id=subject))

    assert refused.value.status_code == 403, (
        "the alert says the child switched protection off; letting them clear the "
        "badge hands them the whole loophole back"
    )
    assert ("update", "guardian_alerts") not in db.trail


async def test_a_parent_acknowledging_stamps_the_row_and_returns_it():
    subject = uuid.uuid4()
    db = Recorder({
        ("select", "guardian_alerts"): [alert_row(subject_id=subject)],
        ("select", "subjects"): [subject_row(id=subject)],
        ("select", "families"): [(uuid.uuid4(),)],
    })

    out = await R.acknowledge_alert(41, db, Parent())

    assert out.acknowledged_at is not None
    stmt, _ = db.only("update", "guardian_alerts")
    assert "acknowledged_at" in rendered(stmt)


async def test_acknowledging_twice_does_not_move_the_timestamp():
    subject, seen = uuid.uuid4(), now() - timedelta(hours=3)
    db = Recorder({
        ("select", "guardian_alerts"): [alert_row(subject_id=subject, acknowledged_at=seen)],
        ("select", "subjects"): [subject_row(id=subject)],
        ("select", "families"): [(uuid.uuid4(),)],
    })

    out = await R.acknowledge_alert(41, db, Parent())

    assert out.acknowledged_at == seen
    assert ("update", "guardian_alerts") not in db.trail, (
        "a retry from a flaky network must not rewrite when the parent first saw it"
    )
