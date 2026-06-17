"""User preferences — home intelligence settings persistence."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.user import User

router = APIRouter(prefix="/users", tags=["Users"])

_DEFAULT_INTELLIGENCE = {
    "run_on_load": True,
    "cross_project": True,
    "email_digest": False,
    "granularity": 3,
}


def _with_defaults(prefs: dict[str, Any]) -> dict[str, Any]:
    prefs = dict(prefs or {})
    intelligence = {**_DEFAULT_INTELLIGENCE, **(prefs.get("intelligence") or {})}
    prefs["intelligence"] = intelligence
    return prefs


class PreferencesUpdate(BaseModel):
    intelligence: dict[str, Any] | None = None


@router.get("/preferences")
async def get_preferences(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _with_defaults(user.preferences or {})


@router.patch("/preferences")
async def update_preferences(
    body: PreferencesUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    prefs = _with_defaults(user.preferences or {})
    if body.intelligence is not None:
        prefs["intelligence"] = {
            **prefs["intelligence"],
            **body.intelligence,
        }
    # Reassign so SQLAlchemy detects the JSON change.
    user.preferences = prefs
    await session.commit()
    return prefs
