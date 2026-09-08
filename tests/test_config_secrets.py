import re
from pathlib import Path

import pytest

from app.config import MIN_JWT_SECRET_LENGTH, Settings, ephemeral_signing_key, weak_secret_reason

SOURCE_FILES = sorted((Path(__file__).resolve().parents[1] / "app").rglob("*.py"))

SECRET_FIELDS = [
    "jwt_secret",
    "database_url",
    "anthropic_api_key",
    "openrouter_api_key",
    "s3_access_key",
    "s3_secret_key",
]


@pytest.mark.parametrize("field", SECRET_FIELDS)
def test_no_credential_is_baked_into_the_code(field):
    assert Settings.model_fields[field].default == "", (
        f"{field} has a default baked into the code. Credentials may only come from "
        ".env, so none of them travel with a copy of the repository"
    )


def test_the_code_holds_no_password_inside_a_url():
    pattern = re.compile(r"://[^/\s\"']+:[^/\s\"'@]+@")
    suspects = [
        f"{p.name}: {m.group(0)}"
        for p in SOURCE_FILES
        for m in pattern.finditer(p.read_text())
    ]
    assert not suspects, f"URLs with an embedded password in the code: {suspects}"


def test_production_refuses_an_empty_secret():
    assert weak_secret_reason("production", "") is not None


@pytest.mark.parametrize(
    "value",
    ["ganti-dengan-64-karakter-acak", "dev-secret-jangan-dipakai-di-produksi", "changeme"],
)
def test_production_refuses_an_example_value(value):
    assert weak_secret_reason("production", value) is not None, (
        "an example value from .env.example is easy to copy to a server unchanged"
    )


def test_production_refuses_a_short_secret():
    assert weak_secret_reason("production", "a" * (MIN_JWT_SECRET_LENGTH - 1)) is not None
    assert weak_secret_reason("production", "a" * MIN_JWT_SECRET_LENGTH) is None


def test_development_is_not_forced_to_supply_a_secret():
    assert weak_secret_reason("development", "") is None


def test_the_throwaway_key_is_random_and_stable_for_the_process():
    assert ephemeral_signing_key() == ephemeral_signing_key(), (
        "a token that was issued has to stay readable to the next request"
    )
    assert len(ephemeral_signing_key()) >= MIN_JWT_SECRET_LENGTH


def test_the_signing_key_uses_the_secret_when_one_is_set():
    assert Settings(jwt_secret="x" * 64).signing_key == "x" * 64
    assert Settings(jwt_secret="").signing_key == ephemeral_signing_key()
