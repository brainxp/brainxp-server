import uuid
from datetime import timedelta

from app import schemas as S
from app.routers import families
from app.security import now, sha256
from app.services import devices as D
from tests.conftest import FakeRequest, Recorder, rendered

INSTALL_BINDING = "install-7f3a9c2b41d5"
BINDING_HASH = sha256(INSTALL_BINDING)


def live_code(subject_id: uuid.UUID) -> dict:
    return {
        "code": "418205",
        "subject_id": subject_id,
        "family_id": uuid.uuid4(),
        "issued_by": uuid.uuid4(),
        "consumed_at": None,
        "expires_at": now() + timedelta(minutes=5),
        "attempt_count": 0,
    }


def pair_body() -> S.PairIn:
    return S.PairIn(
        code="418205", install_binding=INSTALL_BINDING,
        platform="android", model_name="Pixel 6a",
    )


def test_the_search_for_a_device_in_the_way_covers_the_phone_itself():
    sql = rendered(D.conflicting(uuid.uuid4(), BINDING_HASH))
    assert "install_binding_hash" in sql, (
        "devices_binding_idx is unique on install_binding_hash alone, so a phone "
        "already bound to another child blocks the insert; filtering by subject_id "
        "only leaves that row in place and the insert dies with a 500"
    )


def test_a_device_in_the_way_is_either_the_childs_or_the_phones():
    sql = rendered(D.conflicting(uuid.uuid4(), BINDING_HASH))
    assert " OR " in sql, (
        "two separate rows can block the pairing: the child's previous phone and "
        "this phone's previous owner. Both have to go, so the two claims are joined "
        "with OR, not AND"
    )


def test_the_search_ignores_devices_that_are_already_released():
    sql = rendered(D.conflicting(uuid.uuid4(), BINDING_HASH))
    assert "unbound_at IS NULL" in sql, (
        "the unique index is partial on unbound_at IS NULL; released rows are "
        "allowed to pile up and must not be touched again"
    )


async def test_the_phone_is_taken_from_its_previous_owner():
    previous_owner = uuid.uuid4()
    old_device = uuid.uuid4()
    db = Recorder({
        ("select", "devices"): [{"id": old_device, "subject_id": previous_owner}],
    })

    displaced = await D.displace(db, uuid.uuid4(), BINDING_HASH)

    assert [r["id"] for r in displaced] == [old_device]
    assert ("update", "devices") in db.trail
    assert ("update", "refresh_tokens") in db.trail, (
        "unbinding is not enough on its own: the refresh token of the old phone "
        "would keep minting access tokens"
    )
    forget, _ = db.only("delete", "installed_apps")
    assert str(previous_owner) in rendered(forget, literals=True), (
        "the app list belongs to the child the phone was taken from, not to the "
        "child receiving it"
    )


async def test_nothing_is_written_when_no_device_is_in_the_way():
    db = Recorder()

    assert await D.displace(db, uuid.uuid4(), BINDING_HASH) == []
    assert db.trail == [("select", "devices")]


async def test_the_device_in_the_way_is_released_before_the_new_row_is_written():
    db = Recorder({
        ("select", "pairing_codes"): [live_code(uuid.uuid4())],
        ("select", "devices"): [{"id": uuid.uuid4(), "subject_id": uuid.uuid4()}],
        ("insert", "devices"): [uuid.uuid4()],
    })

    await families.pair_device(pair_body(), db, FakeRequest())

    trail = db.trail
    assert trail.index(("update", "devices")) < trail.index(("insert", "devices")), (
        "devices_binding_idx rejects a second live row for the same phone, so the "
        "old row has to carry unbound_at before the insert runs, not after"
    )


async def test_the_new_row_carries_the_hash_that_was_searched_for():
    db = Recorder({
        ("select", "pairing_codes"): [live_code(uuid.uuid4())],
        ("insert", "devices"): [uuid.uuid4()],
    })

    await families.pair_device(pair_body(), db, FakeRequest())

    search, _ = db.only("select", "devices")
    written, _ = db.only("insert", "devices")
    assert BINDING_HASH in rendered(search, literals=True)
    assert BINDING_HASH in rendered(written, literals=True), (
        "hashing the binding twice invites the two values to drift apart, and then "
        "the search clears a row the insert never collides with"
    )


async def test_each_child_who_loses_a_device_gets_told():
    previous_owner = uuid.uuid4()
    old_device, replacement = uuid.uuid4(), uuid.uuid4()
    db = Recorder({
        ("select", "pairing_codes"): [live_code(uuid.uuid4())],
        ("select", "devices"): [{"id": old_device, "subject_id": previous_owner}],
        ("insert", "devices"): [replacement],
    })

    await families.pair_device(pair_body(), db, FakeRequest())

    _, events = db.only("insert", "guardian_events")
    assert events == [{
        "subject_id": previous_owner, "device_id": old_device,
        "event_type": D.REPLACED_EVENT, "payload": {"replaced_by": str(replacement)},
    }], (
        "the event is filed against the child who lost the phone, because that is "
        "the timeline their parent reads; guardian_subject_idx is keyed that way"
    )


async def test_no_replacement_is_announced_on_a_first_pairing():
    db = Recorder({
        ("select", "pairing_codes"): [live_code(uuid.uuid4())],
        ("insert", "devices"): [uuid.uuid4()],
    })

    await families.pair_device(pair_body(), db, FakeRequest())

    assert ("insert", "guardian_events") not in db.trail
