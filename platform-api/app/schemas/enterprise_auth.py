"""Schemas for enterprise authentication (LDAP/SSO)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Tenant enterprise auth settings
# ---------------------------------------------------------------------------


class EnterpriseAuthOverview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: int
    local_login_allowed: bool = True
    enforce_2fa: bool = False
    ldap_status: str = "off"
    sso_status: str = "off"
    sso_provider_display_name: str | None = None
    last_successful_directory_sync: datetime | None = None
    last_successful_sso_test: datetime | None = None


class EnterpriseAuthSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: int
    ldap_enabled: bool = False
    sso_enabled: bool = False
    sso_required: bool = False
    local_login_allowed: bool = True
    sso_provider_display_name: str | None = None
    sso_status: str | None = None
    sso_last_tested_at: datetime | None = None
    sso_last_test_result: str | None = None
    ldap_connection_id: int | None = None


class EnterpriseAuthSettingsUpdate(BaseModel):
    ldap_enabled: bool | None = None
    sso_enabled: bool | None = None
    sso_required: bool | None = None
    local_login_allowed: bool | None = None


# ---------------------------------------------------------------------------
# LDAP connection
# ---------------------------------------------------------------------------


class LdapConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    protocol: str = "ldaps"
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=636, ge=1, le=65535)
    base_dn: str = Field(min_length=1, max_length=1024)
    user_search_base: str | None = Field(default=None, max_length=1024)
    user_filter: str | None = Field(default=None, max_length=1024)
    group_search_base: str | None = Field(default=None, max_length=1024)
    group_filter: str | None = Field(default=None, max_length=1024)
    bind_dn: str | None = Field(default=None, max_length=512)
    bind_secret: str | None = Field(default=None, max_length=2048)
    ca_certificate: str | None = Field(default=None, max_length=65535)
    use_starttls: bool = False
    require_cert_validation: bool = True
    connect_timeout: int = Field(default=10, ge=1, le=300)
    page_size: int = Field(default=1000, ge=1, le=10000)
    nested_group_resolution: bool = False
    max_nested_depth: int = Field(default=10, ge=0, le=100)
    sync_interval_minutes: int = Field(default=60, ge=1, le=10080)
    disabled_user_handling: str = "suspend"
    removed_group_handling: str = "revoke"
    tenant_data_plane_id: int | None = None
    enabled: bool = True


class LdapConnectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    protocol: str
    host: str
    port: int
    base_dn: str
    user_search_base: str | None
    user_filter: str | None
    group_search_base: str | None
    group_filter: str | None
    bind_dn: str | None
    has_bind_secret: bool
    has_ca_certificate: bool
    use_starttls: bool
    require_cert_validation: bool
    connect_timeout: int
    page_size: int
    nested_group_resolution: bool
    max_nested_depth: int
    sync_interval_minutes: int
    disabled_user_handling: str
    removed_group_handling: str
    tenant_data_plane_id: int | None
    enabled: bool
    archived: bool
    last_test_status: str | None
    last_test_message_safe: str | None
    last_tested_at: datetime | None


class LdapConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    protocol: str | None = None
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    base_dn: str | None = Field(default=None, min_length=1, max_length=1024)
    user_search_base: str | None = Field(default=None, max_length=1024)
    user_filter: str | None = Field(default=None, max_length=1024)
    group_search_base: str | None = Field(default=None, max_length=1024)
    group_filter: str | None = Field(default=None, max_length=1024)
    bind_dn: str | None = Field(default=None, max_length=512)
    bind_secret: str | None = Field(default=None, max_length=2048)
    ca_certificate: str | None = Field(default=None, max_length=65535)
    use_starttls: bool | None = None
    require_cert_validation: bool | None = None
    connect_timeout: int | None = Field(default=None, ge=1, le=300)
    page_size: int | None = Field(default=None, ge=1, le=10000)
    nested_group_resolution: bool | None = None
    max_nested_depth: int | None = Field(default=None, ge=0, le=100)
    sync_interval_minutes: int | None = Field(default=None, ge=1, le=10080)
    disabled_user_handling: str | None = None
    removed_group_handling: str | None = None
    tenant_data_plane_id: int | None = None
    enabled: bool | None = None


class LdapConnectionTestResponse(BaseModel):
    success: bool
    status: str
    message: str


class LdapPreviewResponse(BaseModel):
    users: list[dict]
    groups: list[dict]
    membership_count: int


class LdapSyncResponse(BaseModel):
    sync_run_id: int | None
    status: str
    message: str


# ---------------------------------------------------------------------------
# Directory group mappings
# ---------------------------------------------------------------------------


class DirectoryGroupRoleMappingCreate(BaseModel):
    directory_group_guid: str = Field(min_length=1, max_length=64)
    group_display_name: str | None = Field(default=None, max_length=255)
    target_type: str = Field(pattern=r"^(tenant|project|capability)$")
    target_project_id: int | None = None
    mapped_role: str = Field(min_length=1, max_length=32)
    enabled: bool = True


class DirectoryGroupRoleMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    connection_id: int
    directory_group_guid: str
    group_display_name: str | None
    target_type: str
    target_project_id: int | None
    mapped_role: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class DirectoryGroupRoleMappingUpdate(BaseModel):
    group_display_name: str | None = Field(default=None, max_length=255)
    target_type: str | None = Field(default=None, pattern=r"^(tenant|project|capability)$")
    target_project_id: int | None = None
    mapped_role: str | None = Field(default=None, min_length=1, max_length=32)
    enabled: bool | None = None


# ---------------------------------------------------------------------------
# SSO
# ---------------------------------------------------------------------------


class SsoConfiguration(BaseModel):
    provider_friendly_name: str = Field(min_length=1, max_length=255)
    identity_provider_type: str = Field(default="generic_saml")
    metadata_url: str | None = Field(default=None, max_length=2048)
    metadata_xml: str | None = Field(default=None, max_length=65535)
    expected_entity_id: str | None = Field(default=None, max_length=1024)
    allowed_email_domains: list[str] | None = None


class SsoConfigurationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider_friendly_name: str | None
    identity_provider_type: str | None
    expected_entity_id: str | None
    allowed_email_domains: list[str]
    sso_status: str | None
    sso_last_tested_at: datetime | None
    sso_last_test_result: str | None


class SsoPolicyUpdate(BaseModel):
    sso_enabled: bool | None = None
    sso_required: bool | None = None
    local_login_allowed: bool | None = None


class SsoTestResponse(BaseModel):
    success: bool
    status: str
    message: str


# ---------------------------------------------------------------------------
# Identity mappings
# ---------------------------------------------------------------------------


class IdentityMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    provider_type: str
    external_subject: str
    verification_state: str
    sso_provider_uuid: bool
    suspended: bool
    linked_at: datetime | None
    last_authenticated_at: datetime | None
    last_synchronized_at: datetime | None


class IdentityMappingConfirm(BaseModel):
    user_id: int


class IdentityMappingReject(BaseModel):
    pass


# ---------------------------------------------------------------------------
# Public tenant auth policy
# ---------------------------------------------------------------------------


class TenantAuthPolicyResponse(BaseModel):
    tenant_slug: str
    tenant_display_name: str
    local_login_allowed: bool
    sso_enabled: bool
    sso_required: bool
    sso_button_label: str | None = None


class SsoStartRequest(BaseModel):
    tenant_slug: str
    return_path: str | None = "/"


class SsoStartResponse(BaseModel):
    redirect_url: str


class SsoCallbackQuery(BaseModel):
    code: str | None = None
    state: str | None = None
    error: str | None = None
    error_description: str | None = None
