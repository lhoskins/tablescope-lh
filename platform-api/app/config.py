"""Platform API configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # Accept both ENVIRONMENT (legacy) and APP_ENV (billing plan) env names.
    environment: Literal["development", "test", "staging", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("ENVIRONMENT", "APP_ENV"),
    )
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

    # When the platform API runs as a container (the normal deployment), it
    # cannot reach a tenant Teiid via the host's 127.0.0.1-bound ports. Instead
    # it reaches the tenant container directly over the tenant Docker network
    # using the container's fixed IP + container-internal ports. Set to False
    # only when the platform API runs as a host process.
    tenant_teiid_in_cluster: bool = True

    customer_base_path: str = "/opt/wildfly/teiidfiles/customers"
    drilldown_config_path: str = "/opt/redash-8.0.0-7/apps/tsTest/src/drilldownConfig.json"

    s3_bucket_name: str = "tablescope-data-988823366090"
    s3_region: str = "us-west-1"
    s3_enabled: bool = True

    # Symmetric key used to encrypt database data-source passwords at rest.
    # In production set TABLESCOPE_SECRET_KEY to a stable Fernet key.  When
    # empty, a key is derived from JWT_SECRET_KEY so dev still works.
    tablescope_secret_key: str = ""

    clerk_jwks_url: str = ""
    clerk_issuer: str = ""
    supabase_jwks_url: str = ""
    supabase_issuer: str = ""

    sentry_dsn: str = ""
    prometheus_enabled: bool = True

    cors_allow_origins: str = "*"

    # --- AI Server integration ---
    tablescope_ai_enabled: bool = False
    tablescope_ai_api_url: str = ""
    tablescope_ai_signing_secret: str = ""
    tablescope_ai_default_scope: str = "project"
    tablescope_ai_cross_project_enabled: bool = False
    tablescope_ai_tenant_scope_enabled: bool = False

    # --- Supabase authentication ---
    # Single environment-configured auth provider (NOT one project per tenant).
    supabase_env: Literal["test", "staging", "production"] = "test"
    supabase_url: str = ""
    supabase_project_ref: str = ""
    supabase_anon_key: str = ""
    # Backend-only. Never expose to the frontend.
    supabase_service_role_key: str = ""
    supabase_database_url: str = ""
    supabase_jwt_secret: str = ""

    # --- Stripe billing ---
    stripe_mode: Literal["test", "live"] = "test"
    stripe_publishable_key: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_success_url: str = ""
    stripe_cancel_url: str = ""

    # --- Outbound email (branded billing/invite emails) ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    email_from: str = Field(
        default="Tablescope <no-reply@tablescope.cloud>",
        validation_alias=AliasChoices("EMAIL_FROM", "TABLESCOPE_EMAIL_FROM"),
    )
    email_reply_to: str = Field(
        default="",
        validation_alias=AliasChoices("EMAIL_REPLY_TO", "TABLESCOPE_EMAIL_REPLY_TO"),
    )
    email_logo_url: str = Field(
        default="",
        validation_alias=AliasChoices("EMAIL_LOGO_URL", "TABLESCOPE_EMAIL_LOGO_URL"),
    )
    app_base_url: str = Field(
        default="https://app.tablescope.cloud",
        validation_alias=AliasChoices("APP_BASE_URL", "TABLESCOPE_APP_URL"),
    )
    support_email: str = Field(
        default="support@tablescope.cloud",
        validation_alias=AliasChoices("SUPPORT_EMAIL", "TABLESCOPE_SUPPORT_EMAIL"),
    )

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.email_from)

    @property
    def resolved_supabase_project_ref(self) -> str:
        """Project ref, derived from the Supabase URL when not set explicitly."""
        if self.supabase_project_ref:
            return self.supabase_project_ref
        url = self.supabase_url.removeprefix("https://").removeprefix("http://")
        return url.split(".")[0] if url else ""

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def stripe_configured(self) -> bool:
        return bool(self.stripe_secret_key)

    @model_validator(mode="after")
    def _validate_env_safety(self) -> Settings:
        """Guard against mismatched Stripe credentials.

        The billing mode is keyed off ``STRIPE_MODE`` (not the global app
        ``ENVIRONMENT``) so that a production app host can run billing in test
        mode during rollout. The guarantees that still hold:
          * the secret key must match the declared mode (no test key in live
            mode and vice-versa), and
          * live keys may only run when the app ``ENVIRONMENT`` is production.
        """
        if self.stripe_secret_key:
            if self.stripe_mode == "live" and self.stripe_secret_key.startswith("sk_test_"):
                raise ValueError("STRIPE_MODE=live but a Stripe test secret key was provided")
            if self.stripe_mode == "test" and self.stripe_secret_key.startswith("sk_live_"):
                raise ValueError("STRIPE_MODE=test but a Stripe live secret key was provided")
            if self.stripe_mode == "live" and self.environment != "production":
                raise ValueError(
                    f"Refusing to use Stripe live mode in APP_ENV={self.environment}"
                )
        return self

    @model_validator(mode="after")
    def _derive_supabase_auth_endpoints(self) -> Settings:
        """Derive the Supabase issuer + JWKS URL from the project URL when unset.

        Supabase access tokens are signed with the project's GoTrue keys and
        carry ``iss = <supabase_url>/auth/v1``; the matching JWKS lives at
        ``<supabase_url>/auth/v1/.well-known/jwks.json``. Deriving these means
        the exchange endpoint works with only ``SUPABASE_URL`` configured.
        """
        base = self.supabase_url.rstrip("/")
        if base:
            if not self.supabase_issuer:
                self.supabase_issuer = f"{base}/auth/v1"
            if not self.supabase_jwks_url:
                self.supabase_jwks_url = f"{base}/auth/v1/.well-known/jwks.json"
        return self

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
