"""Platform API configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api"

    database_url: str = "postgresql+asyncpg://postgres:password@db:5432/tablescope"
    database_pool_min_size: int = 5
    database_pool_max_size: int = 20

    redis_url: str = "redis://redis:6379/0"

    jwt_secret_key: str = "change-me-please"
    jwt_algorithm: str = "HS256"
    jwt_access_token_ttl_minutes: int = 60
    jwt_issuer: str = "tablescope-platform-api"
    jwt_audience: str = "tablescope-clients"

    service_api_keys: str = ""

    teiid_pg_host: str = "teiid"
    teiid_pg_port: int = 35442
    teiid_pg_default_vdb: str = "myvdbtest"
    teiid_servlet_url: str = "http://teiid:8095"
    teiid_servlet_api_key: str = ""

    customer_base_path: str = "/opt/wildfly/teiidfiles/customers"
    drilldown_config_path: str = "/opt/redash-8.0.0-7/apps/tsTest/src/drilldownConfig.json"

    clerk_jwks_url: str = ""
    clerk_issuer: str = ""
    supabase_jwks_url: str = ""
    supabase_issuer: str = ""

    sentry_dsn: str = ""
    prometheus_enabled: bool = True

    cors_allow_origins: str = "*"

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}:
            raise ValueError(f"Invalid log level: {value}")
        return normalized

    @property
    def service_api_key_set(self) -> set[str]:
        """Parse the SERVICE_API_KEYS env var into a set."""
        if not self.service_api_keys:
            return set()
        return {key.strip() for key in self.service_api_keys.split(",") if key.strip()}

    @property
    def cors_origins(self) -> list[str]:
        if not self.cors_allow_origins or self.cors_allow_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
