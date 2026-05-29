"""S3 storage management routes.

Provides endpoints for:
- Migrating existing local files to S3
- Syncing S3 back to local
- Checking S3 status
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/storage", tags=["storage"])


async def _require_super_admin(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> RequestContext:
    if context.is_service:
        return context
    user = await session.get(User, context.user_id)
    if user is None or not user.is_super_admin:
        raise HTTPException(status_code=403, detail="Only super-admins can manage storage")
    return context


@router.get("/status")
async def storage_status(
    context: RequestContext = Depends(_require_super_admin),
) -> dict:
    """Check S3 storage status."""
    settings = get_settings()
    if not settings.s3_enabled:
        return {
            "s3_enabled": False,
            "message": "S3 storage is not enabled. Set S3_ENABLED=true to enable.",
        }

    from app.services.s3_storage import S3StorageService
    svc = S3StorageService()
    try:
        svc.ensure_bucket_exists()
        files = svc.list_files("customers/")
        return {
            "s3_enabled": True,
            "bucket": settings.s3_bucket_name,
            "region": settings.s3_region,
            "file_count": len(files),
        }
    except Exception as e:
        return {
            "s3_enabled": True,
            "bucket": settings.s3_bucket_name,
            "region": settings.s3_region,
            "error": str(e),
        }


@router.post("/migrate-to-s3")
async def migrate_to_s3(
    context: RequestContext = Depends(_require_super_admin),
) -> dict:
    """Migrate all existing local files to S3."""
    settings = get_settings()
    if not settings.s3_enabled:
        raise HTTPException(status_code=400, detail="S3 storage is not enabled")

    from app.services.s3_storage import S3StorageService
    svc = S3StorageService()

    try:
        svc.ensure_bucket_exists()
        count = svc.sync_local_to_s3(settings.customer_base_path, "customers")
        return {
            "status": "success",
            "files_uploaded": count,
            "bucket": settings.s3_bucket_name,
        }
    except Exception as e:
        logger.error("S3 migration failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Migration failed: {e}") from e


@router.post("/sync-from-s3")
async def sync_from_s3(
    context: RequestContext = Depends(_require_super_admin),
) -> dict:
    """Sync all S3 files back to local filesystem."""
    settings = get_settings()
    if not settings.s3_enabled:
        raise HTTPException(status_code=400, detail="S3 storage is not enabled")

    from app.services.s3_storage import S3StorageService
    svc = S3StorageService()

    try:
        count = svc.sync_s3_to_local("customers/", settings.customer_base_path)
        return {
            "status": "success",
            "files_downloaded": count,
        }
    except Exception as e:
        logger.error("S3 sync failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}") from e
