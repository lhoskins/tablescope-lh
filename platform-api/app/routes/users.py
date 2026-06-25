"""Current-user profile routes (avatar upload + serving)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext, get_request_context
from app.database import get_db
from app.models.user import User
from app.services.avatar_storage import (
    AvatarValidationError,
    read_avatar,
    store_avatar,
    validate_avatar,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


def _profile(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
    }


@router.post("/me/avatar")
async def upload_my_avatar(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> dict:
    """Upload/replace the authenticated user's profile picture.

    A user can only change their own avatar (the target is always the caller).
    """
    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    content = await file.read()
    try:
        ext = validate_avatar(
            content=content,
            content_type=file.content_type,
            filename=file.filename,
        )
    except AvatarValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    file_id = store_avatar(
        tenant_id=user.tenant_id,
        user_id=user.id,
        content=content,
        ext=ext,
    )
    user.avatar_file_id = file_id
    # Cache-bust on every upload so the new image shows immediately.
    user.avatar_url = f"/api/users/{user.id}/avatar?v={file_id.split('.')[0]}"
    await session.commit()
    await session.refresh(user)

    logger.info("Avatar uploaded for user %d (tenant %d)", user.id, user.tenant_id)
    return _profile(user)


@router.get("/{user_id}/avatar")
async def get_user_avatar(
    user_id: int,
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Serve a user's avatar image by opaque URL (no filesystem path exposed)."""
    user = await session.get(User, user_id)
    if user is None or not user.avatar_file_id:
        raise HTTPException(status_code=404, detail="No avatar")

    result = read_avatar(
        tenant_id=user.tenant_id,
        user_id=user.id,
        file_id=user.avatar_file_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="No avatar")
    content, content_type = result
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
