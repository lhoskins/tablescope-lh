"""Shared request model for archive/unarchive operations."""

from pydantic import BaseModel


class ArchiveSourceRequest(BaseModel):
    archived: bool
