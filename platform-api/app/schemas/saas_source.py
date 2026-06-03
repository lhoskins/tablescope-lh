"""Request/response schemas for the SaaS connector workflow."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreateCredentialRequest(BaseModel):
    connector_type: str = Field(..., description="hubspot | salesforce")
    display_name: str
    # Free-form auth config; for HubSpot {access_token}, for Salesforce the
    # OAuth username-password bundle.  Stored encrypted.
    config: dict


class TestCredentialRequest(BaseModel):
    # Either reference a stored credential...
    credential_id: int | None = None
    # ...or pass an inline connector_type + config to test before saving.
    connector_type: str | None = None
    config: dict | None = None


class ObjectsRequest(BaseModel):
    credential_id: int


class FieldsRequest(BaseModel):
    credential_id: int
    object_type: str


class PreviewRequest(BaseModel):
    credential_id: int
    object_type: str
    selected_fields: list[str] = Field(default_factory=list)
    limit: int = 20


class CreateSaasSourceRequest(BaseModel):
    credential_id: int
    connector_type: str
    object_type: str
    selected_fields: list[str] = Field(default_factory=list)
    display_name: str
    project_id: int | None = None


class SyncRequest(BaseModel):
    # Optional cap; null/0 means full sync.
    limit: int | None = None
    # When true, run the sync inline and wait for the result (used by tests /
    # small syncs).  When false, enqueue to the worker and return immediately.
    wait: bool = False
