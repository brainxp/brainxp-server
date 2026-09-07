import inspect

from fastapi.dependencies.utils import get_dependant

from app import deps
from app.db import conn
from app.security import now

BOUND = {"unbound_at": None, "deleted_at": None}


def test_a_bound_device_is_accepted():
    assert deps.revoked_reason(BOUND) is None


def test_a_released_device_is_refused():
    assert deps.revoked_reason({"unbound_at": now(), "deleted_at": None}) is not None, (
        "revoking the refresh token is not enough: an access token already issued "
        "stays valid for up to 15 minutes, and in that window the old phone can "
        "spend balance and pull the offline question bank"
    )


def test_a_deleted_profile_is_refused():
    assert deps.revoked_reason({"unbound_at": None, "deleted_at": now()}) is not None


def test_a_device_missing_from_the_database_is_refused():
    assert deps.revoked_reason(None) is not None


def test_the_refusal_names_the_next_step():
    message = deps.revoked_reason({"unbound_at": now(), "deleted_at": None})
    assert "Pasangkan ulang" in message, (
        "the client reads this message to decide whether to show the pairing screen"
    )


def test_the_caller_identity_is_checked_against_the_database():
    dependant = get_dependant(path="/x", call=deps.caller)
    assert any(sub.call is conn for sub in dependant.dependencies), (
        "caller needs a database connection; without one nothing checks that the "
        "device is still bound"
    )


def test_a_device_token_always_goes_through_the_binding_check():
    source = inspect.getsource(deps.caller)
    assert "require_bound_device" in source
    assert "me.device_id" in source, (
        "a parent token carries no device id, so the check has to be conditional or "
        "it adds a query for them too"
    )


def test_the_binding_check_reads_both_tables_at_once():
    source = inspect.getsource(deps.require_bound_device)
    assert "unbound_at" in source and "deleted_at" in source, (
        "a released device and a deleted profile are two different events; one query "
        "has to cover both"
    )
