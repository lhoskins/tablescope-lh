"""Project sharing schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ShareProjectRequest(BaseModel):
    projectId: int = Field(ge=1)
    filenames: list[str] = Field(default_factory=list)


class ShareProjectResponse(BaseModel):
    projectId: int
    sharedVdbId: str
    copiedFiles: list[str]
