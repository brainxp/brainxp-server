import pytest

from app.services import ratelimit as RL


@pytest.mark.parametrize(
    "count,expected",
    [(1, False), (10, False), (11, True), (500, True)],
)
def test_the_limit_trips_once_the_quota_is_spent(count, expected):
    assert RL.exceeded(count, RL.PAIR_PER_IP) is expected


def test_the_global_quota_is_looser_than_the_per_ip_one():
    assert RL.PAIR_GLOBAL.limit > RL.PAIR_PER_IP.limit


def test_the_global_quota_closes_a_sweep_of_the_code_space():
    assert RL.PAIR_GLOBAL.seconds <= 600, (
        "a six digit code has 10^6 possibilities and lives only ten minutes"
    )
    assert RL.PAIR_GLOBAL.limit / 1_000_000 < 0.001, (
        "the global limit has to stay far below that space so a distributed sweep "
        "remains impossible within one lifetime of a code"
    )


def test_the_ip_comes_from_x_real_ip_first():
    headers = {"x-real-ip": "203.0.113.9", "x-forwarded-for": "1.2.3.4, 5.6.7.8"}
    assert RL.client_ip(headers, "172.18.0.1") == "203.0.113.9"


def test_the_ip_uses_the_last_entry_of_x_forwarded_for():
    headers = {"x-forwarded-for": "9.9.9.9, 203.0.113.9"}
    assert RL.client_ip(headers, "172.18.0.1") == "203.0.113.9", (
        "nginx appends the real address at the end of the chain, so the last entry "
        "is the trustworthy one; earlier entries can be forged by an attacker"
    )


def test_the_ip_falls_back_to_the_connection_address_without_headers():
    assert RL.client_ip({}, "198.51.100.7") == "198.51.100.7"
    assert RL.client_ip({}, None) == "unknown"
