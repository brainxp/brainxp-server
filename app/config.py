import secrets
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

WEAK_SECRET_PREFIXES = ("ganti-", "dev-secret", "changeme")
MIN_JWT_SECRET_LENGTH = 32


@lru_cache
def ephemeral_signing_key() -> str:
    return secrets.token_urlsafe(48)


def weak_secret_reason(app_env: str, jwt_secret: str) -> str | None:
    if app_env == "development":
        return None
    if not jwt_secret:
        return "JWT_SECRET is not set."
    if jwt_secret.startswith(WEAK_SECRET_PREFIXES):
        return "JWT_SECRET still holds an example value."
    if len(jwt_secret) < MIN_JWT_SECRET_LENGTH:
        return f"JWT_SECRET is shorter than {MIN_JWT_SECRET_LENGTH} characters."
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_tz: str = "Asia/Jakarta"
    cors_origins: str = ""

    database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = ""
    access_ttl_seconds: int = 900
    refresh_ttl_seconds: int = 2_592_000

    anthropic_api_key: str = ""
    model_generation: str = "claude-opus-5"
    model_grading: str = "claude-opus-5"
    model_gate: str = "claude-haiku-4-5"
    model_fallback: str = "claude-opus-4-8"

    s3_endpoint_url: str = ""
    s3_bucket: str = "brainxp-materials"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "auto"
    signed_url_ttl_seconds: int = 300

    max_upload_bytes: int = 33_554_432
    daily_upload_quota: int = 20

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def signing_key(self) -> str:
        return self.jwt_secret or ephemeral_signing_key()


@lru_cache
def settings() -> Settings:
    return Settings()
