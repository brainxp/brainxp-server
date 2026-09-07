import json
import uuid

import pytest

from app import schemas as S
from app.errors import AppError
from app.routers import families
from app.services import devices as D
from app.services import push as PU
from tests.conftest import Recorder, rendered

TOKEN = "fcm-token-0123456789abcdef"


class Parent:
    role = "parent"
    device_id = None
    is_parent = True
    is_child = False

    def __init__(self):
        self.user_id = uuid.uuid4()
        self.subject_id = None


class ChildDevice:
    role = "child"
    user_id = None
    is_parent = False
    is_child = True

    def __init__(self):
        self.subject_id = uuid.uuid4()
        self.device_id = uuid.uuid4()


class Nobody:
    role = "child"
    user_id = None
    subject_id = None
    device_id = None
    is_parent = False
    is_child = True


def body(token: str = TOKEN) -> S.PushTokenIn:
    return S.PushTokenIn(token=token, platform="android")


async def test_a_parent_phone_is_stored_against_the_account():
    me = Parent()
    db = Recorder()

    await families.register_push_token(body(), db, me)

    stmt, _ = db.only("insert", "push_tokens")
    sql = rendered(stmt, literals=True)
    assert str(me.user_id) in sql, (
        "the point of the token is reaching the parent while their app is closed, "
        "and a parent session carries no device id, so it can only be filed under "
        "the account"
    )


async def test_a_paired_phone_is_stored_against_the_device():
    me = ChildDevice()
    db = Recorder()

    await families.register_push_token(body(), db, me)

    stmt, _ = db.only("insert", "push_tokens")
    assert str(me.device_id) in rendered(stmt, literals=True)


async def test_a_session_with_neither_owner_is_refused():
    db = Recorder()

    with pytest.raises(AppError) as refusal:
        await families.register_push_token(body(), db, Nobody())

    assert refusal.value.status_code == 403
    assert db.trail == [], "nothing should be written for a session that owns no inbox"


async def test_re_registering_a_token_moves_it_to_its_new_owner():
    db = Recorder()

    await families.register_push_token(body(), db, Parent())

    stmt, _ = db.only("insert", "push_tokens")
    sql = rendered(stmt)
    assert "ON CONFLICT (token) DO UPDATE" in sql, (
        "FCM hands the same token to whoever installs the app next, so the row has "
        "to change owner instead of leaving a stranger subscribed to a child"
    )
    assert "user_id = excluded.user_id" in sql
    assert "device_id = excluded.device_id" in sql


async def test_registering_again_lifts_an_earlier_revocation():
    db = Recorder()

    await families.register_push_token(body(), db, Parent())

    stmt, _ = db.only("insert", "push_tokens")
    assert "revoked_at" in rendered(stmt), (
        "a phone that logs back in has to start receiving again without waiting for "
        "a new token from FCM"
    )


async def test_dropping_a_token_only_touches_your_own():
    me = Parent()
    db = Recorder()

    await families.drop_push_token(body(), db, me)

    stmt, _ = db.only("update", "push_tokens")
    sql = rendered(stmt, literals=True)
    assert TOKEN in sql
    assert str(me.user_id) in sql, (
        "the token is guessable from a captured request, so ownership has to be "
        "part of the predicate"
    )


async def test_dropping_a_token_that_is_not_there_is_not_an_error():
    db = Recorder()

    assert await families.drop_push_token(body(), db, Parent()) is None, (
        "logout calls this on every sign-out; failing when the row is already gone "
        "would surface as an error the user cannot act on"
    )


async def test_releasing_a_device_stops_its_notifications():
    old = uuid.uuid4()
    db = Recorder({("select", "devices"): [{"id": old, "subject_id": uuid.uuid4()}]})

    await D.release(db, uuid.uuid4())

    stmt, _ = db.only("update", "push_tokens")
    sql = rendered(stmt, literals=True)
    assert str(old) in sql, (
        "a phone handed to someone else must stop receiving alerts about the child "
        "it used to be paired with"
    )


async def test_nothing_is_revoked_when_no_device_was_released():
    db = Recorder()

    await D.release(db, uuid.uuid4())

    assert ("update", "push_tokens") not in db.trail


def test_the_recipients_of_an_alert_are_the_people_who_can_act_on_it():
    sql = rendered(PU.guardian_users(uuid.uuid4()), literals=True)
    assert "family_members" in sql and "'parent'" in sql, (
        "an alert says protection is off on the child's phone; telling the child "
        "is pointless, so it goes to the parents of that family"
    )
    assert "UNION" in sql and "subjects.user_id" in sql, (
        "in personal mode the subject is the account holder and there is no other "
        "parent to tell"
    )


def test_the_sender_is_a_stub_until_firebase_is_configured(monkeypatch):
    monkeypatch.setattr(PU, "_sender", None)
    assert isinstance(PU.sender(), PU.StubSender), (
        "the whole flow has to be walkable without Firebase credentials, the way "
        "the LLM falls back to a stub"
    )


def test_inline_credentials_and_a_file_are_both_accepted(tmp_path):
    creds = {"client_email": "a@b.iam.gserviceaccount.com", "private_key": "k", "token_uri": "u"}
    assert PU.read_credentials(json.dumps(creds)) == creds

    path = tmp_path / "sa.json"
    path.write_text(json.dumps(creds))
    assert PU.read_credentials(str(path)) == creds


def test_a_missing_credentials_file_says_so_in_english():
    with pytest.raises(RuntimeError) as bad:
        PU.read_credentials("/nowhere/sa.json")
    assert "FCM_SERVICE_ACCOUNT" in str(bad.value)


def test_the_message_is_addressed_to_one_token_at_high_priority():
    fcm = PU.FcmSender.__new__(PU.FcmSender)
    fcm._project = "brainxp-dev"
    note = PU.Notification(title="Judul", body="Isi", data={"alert_id": 7})

    envelope = fcm.envelope(TOKEN, note)

    assert envelope["message"]["token"] == TOKEN
    assert envelope["message"]["android"]["priority"] == "high", (
        "the phone may be dozing; a normal priority message can sit for minutes"
    )
    assert envelope["message"]["data"] == {"alert_id": "7"}, (
        "FCM rejects a data payload whose values are not strings"
    )
    assert fcm.endpoint.endswith("/projects/brainxp-dev/messages:send")


async def test_only_an_unregistered_token_is_pruned():
    assert PU.UNREGISTERED == 404, (
        "a 400 can mean our own envelope is malformed, and treating that as a dead "
        "token would revoke every subscription at once"
    )


async def test_pruning_nothing_writes_nothing():
    db = Recorder()
    await PU.prune(db, [])
    await PU.revoke_devices(db, [])
    assert db.trail == []
