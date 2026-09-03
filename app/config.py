from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_tz: str = "Asia/Jakarta"
    cors_origins: str = ""

    database_url: str = "postgresql+asyncpg://brainxp:brainxp@localhost:5432/brainxp"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "dev-secret-jangan-dipakai-di-produksi"
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


@lru_cache
def settings() -> Settings:
    return Settings()
