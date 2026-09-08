from datetime import timedelta

from app.routers.auth import REPLAY_GRACE, replay_is_recoverable
from app.security import now

CURRENT = now()


def used(ago: timedelta):
    return CURRENT - ago


def test_an_immediate_replay_reads_as_a_lost_reply():
    assert replay_is_recoverable(
        used_at=used(timedelta(seconds=2)), chain_moved_on=False, at=CURRENT
    ), (
        "a client that reloads before it managed to store the new token has to be "
        "able to present the old one once more"
    )


def test_a_replay_after_the_grace_window_still_reads_as_theft():
    assert not replay_is_recoverable(
        used_at=used(REPLAY_GRACE + timedelta(seconds=1)),
        chain_moved_on=False, at=CURRENT,
    )


def test_exactly_on_the_grace_boundary_is_still_accepted():
    assert replay_is_recoverable(
        used_at=used(REPLAY_GRACE), chain_moved_on=False, at=CURRENT
    )


def test_an_old_token_is_refused_once_the_chain_moved_on():
    assert not replay_is_recoverable(
        used_at=used(timedelta(seconds=2)), chain_moved_on=True, at=CURRENT
    ), (
        "if a token was used after this one, the client clearly received its "
        "replacement, so whoever presents the old one is not that client"
    )
