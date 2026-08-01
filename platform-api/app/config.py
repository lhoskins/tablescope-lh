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
    #: Ceiling on how long *activity* may keep extending one session before real
    #: re-authentication. Sliding renewal (see `renew_access_token`) stops here.
    jwt_session_absolute_ttl_minutes: int = 720
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

    # --- LLM Framework (offline Ollama model deployment) ---
    # Master switch. When false, /api/llm-framework/* returns 503 and the UI
    # is hidden. Phase 1 is read-only inventory, so enabling it only exposes
    # runtime/installation/routing data, not model downloads or activation.
    llm_framework_enabled: bool = True
    # Phase 2: enable the Hugging Face catalog search and staging flow.
    llm_framework_hf_catalog_enabled: bool = True
    # Phase 1 restricts the catalog to pre-quantized GGUF artifacts. Setting
    # this to true blocks any FP16 / safetensors / conversion pipeline paths.
    llm_model_catalog_gguf_only: bool = True
    # Allow staging and activation of a verified artifact on a runtime target.
    # Kept off until the deployment agent and canary pipeline are wired.
    llm_deployment_enabled: bool = False
    # Require two distinct platform administrators to approve a production
    # model replacement before activation.
    llm_two_person_approval_required: bool = True
    # Automatically roll back an activation that fails its stabilization window.
    llm_auto_rollback_enabled: bool = True
    # Max bytes allowed in the model vault on the app server. The preflight
    # check uses twice the artifact size plus reserve.
    llm_model_vault_max_bytes: int = 107_374_182_400  # 100 GiB
    # Path to the model vault on the app server (/opt/tablescope is mounted
    # into platform-api, platform-api-worker, and the deployment agent).
    llm_model_vault_path: str = "/opt/tablescope/model-vault"
    # Ed25519/RSA signing key used to sign the artifact manifest. The public
    # key is baked into the deployment agent so it never has to fetch it.
    llm_manifest_signing_key_path: str = "/opt/tablescope/model-vault/signing.pem"
    # Public-key fingerprint of the trusted manifest-signing key. The agent
    # verifies artifacts against a key baked into its image, not fetched from
    # the app server at deploy time.
    llm_manifest_signing_key_fingerprint: str = ""
    # Optional Hugging Face token for accessing gated models.
    llm_huggingface_token: str = ""
    # Phase 4: allow dynamic routing profile changes and activation.
    llm_dynamic_routing_enabled: bool = False
    # Phase 5: enable embedding-model re-index migrations (dual collection,
    # re-embed, recall comparison, cut-over). Disabled until the AI server
    # vector-store backend is wired.
    llm_embedding_migration_enabled: bool = False
    # Phase 6: enable FP16 / safetensors -> GGUF conversion. The converter must
    # be a sandboxed command or container; the platform-api never installs the
    # conversion toolchain itself.
    llm_fp16_conversion_enabled: bool = False
    llm_fp16_converter_command: str = ""
    llm_embedding_recall_threshold: float = 0.95
    # URL of the deployment agent on the AI host. If empty, deployment tasks
    # fail closed with a descriptive quarantine reason.
    llm_deployment_agent_url: str = ""
    # Internal Ollama API URL used by the deployment agent and preflight checks.
    llm_ollama_url: str = "http://ollama:11434"
    # Path on the AI host where GGUF files are installed before ollama create.
    # The agent writes here and Ollama's Modelfile references this path.
    llm_model_install_path: str = "/mnt/tablescope-ai/ollama/models/imported"
    # Number of Ollama model slots reserved for the previous (rollback) model.
    llm_ollama_rollback_slots: int = 1
    tablescope_ai_cross_project_enabled: bool = False
    tablescope_ai_tenant_scope_enabled: bool = False
    # Business Context (Goal Setting) workspace feature flags.
    business_context_v2_enabled: bool = True
    business_context_kpi_matching_enabled: bool = True
    # Max projects analysed concurrently by the Home intelligence SSE stream.
    # Bounds AI/Ollama load so a large project count doesn't flood the server
    # and silently time out into empty "0 insights" results.
    home_intelligence_max_concurrent_projects: int = 3
    # Initial plans are non-degradable, so start them serially while completed
    # plans overlap with sibling projects' execution and interpretation work.
    home_intelligence_max_concurrent_plan_calls: int = 1
    # A busy plan is the one call that restarts the whole project job, so let
    # the client absorb more transient 503s in-place before escalating to an
    # arq-level retry (which re-samples tables and re-runs SQL from scratch).
    home_intelligence_plan_max_retries: int = 4
    home_intelligence_plan_retry_base_seconds: float = 2.0
    # Max concurrent repair/interpret calls spawned by one project analysis.
    # Kept at 1 so (tenant slots) x (this fan-out) stays under the AI gate's
    # real per-tenant capacity; a higher value oversubscribes the gate and
    # turns every project into a stream of retryable 503s.
    home_intelligence_max_concurrent_ai_calls_per_project: int = 1
    # --- Durable per-tenant Home-intelligence queue (arq + Redis) ---
    # Per-tenant fairness cap: at most this many of a tenant's projects run
    # their heavy AI pipeline at once across all workers (Redis-backed, so it
    # is authoritative even when the worker is scaled horizontally). With the
    # per-project fan-out pinned at 1, peak steady-state demand is
    # (cap x 1) regular calls plus one in-flight plan per starting project.
    # Kept at 2 (one below the gate's per-tenant limit of 3) so a full tenant
    # never oversubscribes the gate and there is headroom for plan calls,
    # embeddings, and a second tenant. Raising this above the gate's
    # per-tenant limit adds retries, not throughput.
    home_intelligence_max_concurrent_projects_per_tenant: int = 2
    # TTL for a run's per-run result store (expected set, results hash, run
    # metadata, pub/sub bookkeeping). Long enough for a slow run to drain.
    home_intelligence_run_result_ttl_seconds: int = 3600
    # arq max_tries for analyze_project_intelligence — high so AI-capacity
    # contention AND per-tenant slot waiting are retried generously rather
    # than dropping a project. Because every slot deferral consumes one try,
    # this must comfortably exceed (projects / cap) x (run duration / slot
    # backoff) or late-queued projects get abandoned before their turn.
    home_intelligence_job_max_tries: int = 200
    # Backoff (seconds) when a project defers because its tenant is at the
    # concurrency cap. Every deferral consumes one of job_max_tries, so this
    # interval x job_max_tries is the total time a queued project will wait
    # for a slot before being abandoned as "capacity". 10s x 200 tries gives
    # a ~33-minute budget — enough to outlast a full multi-project drain
    # (2s x 200 was only ~7 minutes and abandoned late-queued projects).
    home_intelligence_tenant_slot_retry_seconds: float = 10.0
    # Fallback backoff (seconds) when the AI gate signals busy without an
    # explicit Retry-After; the client's Retry-After is honored when present.
    home_intelligence_busy_retry_seconds: float = 5.0
    # Hard arq kill-switch for one analyze_project_intelligence job. Must
    # comfortably exceed the worst-case single-project wall time under gate
    # contention (plan + serialized interpret chunks + SQL repair). A job
    # killed by arq's job_timeout writes NO result, so the run can never
    # finalize — keep this above the self-timeout below.
    home_intelligence_job_timeout_seconds: int = 2700
    # Self-imposed per-project analysis deadline, enforced INSIDE the job so
    # a too-slow project raises an ordinary TimeoutError that is recorded as
    # a terminal result (run still finalizes) instead of being silently
    # cancelled by arq. Keep below home_intelligence_job_timeout_seconds.
    home_intelligence_project_analysis_timeout_seconds: int = 2400

    # --- Shared per-project Business Insight result cache (Phase 2) ---
    # When enabled, analyze_project_intelligence serves a project's cards from
    # the tenant-shared business_insight_results cache when it is still keyed
    # to the project's active Knowledge Graph version, so a project is
    # analysed once per data change instead of once per user. Project
    # membership is the visibility boundary: everyone who can open a project
    # sees the same cards.
    business_insight_shared_cache_enabled: bool = False
    # When enabled, a successful Knowledge Graph build enqueues a debounced
    # background re-analysis of that project (attributed to the project
    # owner) so the cache is warm before any user opens Home.
    business_insight_event_refresh_enabled: bool = False
    # Safety-net freshness bound for cached results, covering data paths no
    # graph fingerprint watches. A cached result older than this is rebuilt
    # even if its KG version still matches.
    business_insight_result_ttl_seconds: int = 86400
    # Activity gate for event-driven refresh: skip the background analysis
    # unless someone in the tenant ran Home within this many days, so idle
    # tenants consume zero AI capacity.
    business_insight_refresh_activity_days: int = 7

    # --- Project Insight event-driven rebuild ---
    # When enabled, a successful Knowledge Graph build (or document/reference
    # change) marks the project insight snapshot stale and enqueues a debounced
    # rebuild. The rebuild runs as the snapshot owner and refreshes the cache.
    project_insight_event_rebuild_enabled: bool = False
    # Maximum number of users who already have a Project Insight snapshot that a
    # background rebuild will refresh for one project.
    project_insight_max_rebuild_users: int = 10

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

    # --- Twilio SMS MFA (primary MFA method) ---
    # Secrets are injected at deploy time (never committed). The API key secret
    # is rotated separately from the repo. SMS is delivered via the Twilio
    # Messaging Service SID.
    twilio_account_sid: str = ""
    twilio_api_key_sid: str = ""
    twilio_api_key_secret: str = ""
    twilio_messaging_service_sid: str = ""
    # Twilio Verify service (the MFA primitive that generates/validates OTPs).
    # SMS MFA goes through Twilio Verify directly (no Supabase phone-MFA addon).
    twilio_verify_service_sid: str = ""
    # Master switch for aal2 enforcement on admin-tier roles. Defaults OFF so
    # the feature can ship to production without locking out admins before
    # Twilio Verify is configured. Flip to true
    # (env: MFA_ENFORCEMENT_ENABLED=true) once MFA is fully provisioned.
    mfa_enforcement_enabled: bool = False
    # MFA cost controls.
    mfa_sms_resend_cooldown_seconds: int = 60
    mfa_sms_max_sends_per_window: int = 5
    mfa_sms_window_seconds: int = 900
    mfa_sms_max_attempts_per_challenge: int = 5
    # How long a successful SMS verification keeps the session at aal2 before a
    # re-challenge is required (minutes). Applied to the verified-factor record
    # so reloads / re-logins within the window do not re-prompt.
    mfa_session_ttl_minutes: int = 720

    # Whether tenant provisioning auto-creates a default "<Tenant> Workspace"
    # project for the new tenant admin. Defaults OFF — admins create their own
    # workspace after onboarding. Existing projects are never removed.
    create_default_project_on_tenant_provisioning: bool = False

    @property
    def twilio_configured(self) -> bool:
        return bool(
            self.twilio_account_sid
            and self.twilio_api_key_sid
            and self.twilio_api_key_secret
            and self.twilio_messaging_service_sid
        )

    @property
    def twilio_verify_configured(self) -> bool:
        return bool(
            self.twilio_account_sid
            and self.twilio_api_key_sid
            and self.twilio_api_key_secret
            and self.twilio_verify_service_sid
        )

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

    # --- File acquisition (Data Source Builder URL / UNC-SMB imports) ---
    # Independent runtime flags so either acquisition method can be rolled
    # back without touching local upload, database, or SaaS behaviour.
    file_import_url_enabled: bool = True
    file_import_network_enabled: bool = False
    file_import_max_bytes: int = 104_857_600  # 100 MB
    file_import_connect_timeout_seconds: float = 10.0
    file_import_read_timeout_seconds: float = 60.0
    file_import_total_timeout_seconds: float = 300.0
    file_import_max_redirects: int = 5
    file_import_max_concurrent_fetches: int = 4
    file_import_quarantine_path: str = "/opt/tablescope/quarantine"
    file_import_job_ttl_seconds: int = 86_400
    # Comma-separated host suffix allowlist. Empty means "any public host".
    file_import_allowed_url_domains: str = ""
    # Comma-separated SMB host allowlist. Empty blocks every SMB host, so
    # network import fails closed until operations approves specific hosts.
    file_import_allowed_smb_hosts: str = ""
    # Plain http:// fetches. Off by default; HTTPS-only is the contract.
    file_import_allow_http: bool = False
    # Malware scanning is real infrastructure (a private ClamAV service with
    # operator-managed offline signature updates), not a toggle over an
    # existing capability. When enabled and the scanner is unreachable the
    # import fails closed unless fail_open is explicitly turned on.
    file_import_malware_scan_enabled: bool = False
    file_import_malware_scan_host: str = "clamav"
    file_import_malware_scan_port: int = 3310
    file_import_malware_scan_timeout_seconds: float = 30.0
    file_import_malware_scan_fail_open: bool = False

    @property
    def file_import_url_domain_allowlist(self) -> list[str]:
        raw = self.file_import_allowed_url_domains
        return [d.strip().lower().lstrip(".") for d in raw.split(",") if d.strip()]

    @property
    def file_import_smb_host_allowlist(self) -> list[str]:
        raw = self.file_import_allowed_smb_hosts
        return [h.strip().lower() for h in raw.split(",") if h.strip()]

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
