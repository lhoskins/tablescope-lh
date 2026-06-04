"""Project sharing routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.schemas.sharing import ShareProjectRequest, ShareProjectResponse
from app.services.project_sharing import ProjectSharingError, ProjectSharingService

router = APIRouter(prefix="/sharing", tags=["sharing"])


@router.post("/share", response_model=ShareProjectResponse)
async def share_project(
    payload: ShareProjectRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ShareProjectResponse:
    service = ProjectSharingService(session)
    try:
        result = await service.share_project(
            context=context,
            project_id=payload.projectId,
            filenames=payload.filenames,
        )
    except ProjectSharingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await service.aclose()

    return ShareProjectResponse(
        projectId=result.project_id,
        sharedVdbId=result.shared_vdb_id,
        copiedFiles=result.copied_files,
    )
