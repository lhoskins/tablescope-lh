"""Data source metadata service — persist and retrieve AI file analysis results."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_source_ai_profile import (
    DataSourceAIProfile,
    DataSourceAIRecommendation,
    DataSourceFieldProfile,
    DataSourceTag,
)

logger = logging.getLogger(__name__)


async def create_ai_profile(
    session: AsyncSession,
    *,
    data_source_id: int,
    tenant_id: int,
    user_id: int,
    project_id: int | None,
    file_profile: dict[str, Any],
    ai_result: dict[str, Any],
) -> dict[str, Any]:
    """Create a full AI profile with fields, tags, and recommendations."""

    profile = DataSourceAIProfile(
        data_source_id=data_source_id,
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id,
        file_name=file_profile.get("file_name"),
        file_type=file_profile.get("file_type"),
        file_size_bytes=file_profile.get("file_size_bytes"),
        row_count=file_profile.get("row_count"),
        column_count=file_profile.get("column_count"),
        sheet_name=file_profile.get("sheet_name"),
        ai_summary=ai_result.get("summary"),
        ai_usage_summary=ai_result.get("usage_summary"),
        ai_quality_summary=ai_result.get("quality_summary"),
        status="analyzed",
    )
    session.add(profile)
    await session.flush()

    # Save field profiles
    profile_fields = file_profile.get("fields", [])
    ai_fields = {f["field_name"]: f for f in ai_result.get("fields", [])}

    for pf in profile_fields:
        ai_f = ai_fields.get(pf["field_name"], {})
        session.add(DataSourceFieldProfile(
            data_source_id=data_source_id,
            profile_id=profile.id,
            field_name=pf["field_name"],
            detected_type=pf.get("detected_type"),
            recommended_type=ai_f.get("recommended_type", pf.get("detected_type")),
            max_length=pf.get("max_length"),
            min_length=pf.get("min_length"),
            nullable=pf.get("nullable"),
            null_count=pf.get("null_count"),
            null_percent=pf.get("null_percent"),
            distinct_count=pf.get("distinct_count"),
            sample_values=pf.get("sample_values"),
            min_value=pf.get("min_value"),
            max_value=pf.get("max_value"),
            ai_description=ai_f.get("description"),
            ai_quality_notes=ai_f.get("quality_notes"),
        ))

    # Save tags
    for tag_data in ai_result.get("tags", []):
        session.add(DataSourceTag(
            data_source_id=data_source_id,
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project_id,
            tag=tag_data["tag"],
            tag_type=tag_data.get("tag_type", "user"),
            source="ai",
            confidence=tag_data.get("confidence"),
            accepted=True,
        ))

    # Save recommendations
    for rec_data in ai_result.get("recommendations", []):
        session.add(DataSourceAIRecommendation(
            data_source_id=data_source_id,
            profile_id=profile.id,
            recommendation_type=rec_data.get("recommendation_type", "info"),
            title=rec_data["title"],
            description=rec_data.get("description", ""),
            severity=rec_data.get("severity", "info"),
            suggested_action=rec_data.get("suggested_action"),
            status="pending",
        ))

    await session.flush()

    return await get_ai_profile(session, data_source_id=data_source_id)


async def get_ai_profile(
    session: AsyncSession, *, data_source_id: int
) -> dict[str, Any]:
    """Get the full AI profile for a data source."""
    profile = await session.scalar(
        select(DataSourceAIProfile)
        .where(DataSourceAIProfile.data_source_id == data_source_id)
        .order_by(DataSourceAIProfile.id.desc())
    )
    if profile is None:
        return {}

    fields = (
        await session.scalars(
            select(DataSourceFieldProfile)
            .where(DataSourceFieldProfile.data_source_id == data_source_id)
            .order_by(DataSourceFieldProfile.id)
        )
    ).all()

    tags = (
        await session.scalars(
            select(DataSourceTag)
            .where(DataSourceTag.data_source_id == data_source_id)
        )
    ).all()

    recommendations = (
        await session.scalars(
            select(DataSourceAIRecommendation)
            .where(DataSourceAIRecommendation.data_source_id == data_source_id)
            .order_by(DataSourceAIRecommendation.id)
        )
    ).all()

    return {
        "profile": profile.to_dict(),
        "fields": [f.to_dict() for f in fields],
        "tags": [t.to_dict() for t in tags],
        "recommendations": [r.to_dict() for r in recommendations],
    }


async def update_tags(
    session: AsyncSession,
    *,
    data_source_id: int,
    tenant_id: int,
    user_id: int,
    project_id: int | None,
    tags: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replace all tags for a data source."""
    existing = (
        await session.scalars(
            select(DataSourceTag)
            .where(DataSourceTag.data_source_id == data_source_id)
        )
    ).all()
    for t in existing:
        await session.delete(t)

    result = []
    for tag_data in tags:
        tag = DataSourceTag(
            data_source_id=data_source_id,
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project_id,
            tag=tag_data["tag"],
            tag_type=tag_data.get("tag_type", "user"),
            source=tag_data.get("source", "user"),
            confidence=tag_data.get("confidence"),
            accepted=tag_data.get("accepted", True),
        )
        session.add(tag)
        await session.flush()
        result.append(tag.to_dict())

    return result


async def update_recommendations(
    session: AsyncSession,
    *,
    data_source_id: int,
    recommendations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Update recommendation statuses (accept/reject)."""
    result = []
    for rec_update in recommendations:
        rec_id = rec_update.get("id")
        new_status = rec_update.get("status", "pending")
        if rec_id is None:
            continue

        rec = await session.get(DataSourceAIRecommendation, rec_id)
        if rec is None or rec.data_source_id != data_source_id:
            continue

        rec.status = new_status
        now = datetime.now(UTC)
        if new_status == "accepted":
            rec.accepted_at = now
        elif new_status == "rejected":
            rec.rejected_at = now
        result.append(rec.to_dict())

    return result


async def update_user_notes(
    session: AsyncSession,
    *,
    data_source_id: int,
    user_notes: str | None = None,
    user_nuances: str | None = None,
) -> dict[str, Any]:
    """Update user notes/nuances on the profile."""
    profile = await session.scalar(
        select(DataSourceAIProfile)
        .where(DataSourceAIProfile.data_source_id == data_source_id)
        .order_by(DataSourceAIProfile.id.desc())
    )
    if profile is None:
        return {}

    if user_notes is not None:
        profile.user_notes = user_notes
    if user_nuances is not None:
        profile.user_nuances = user_nuances

    return profile.to_dict()


async def get_ai_context_for_data_source(
    session: AsyncSession, *, data_source_id: int
) -> dict[str, Any]:
    """Get compact AI context for a data source — used by future AI workflows."""
    full = await get_ai_profile(session, data_source_id=data_source_id)
    if not full:
        return {}

    profile = full.get("profile", {})
    tags = [t["tag"] for t in full.get("tags", []) if t.get("accepted")]

    fields = []
    for f in full.get("fields", []):
        fields.append({
            "name": f["field_name"],
            "type": f.get("recommended_type") or f.get("detected_type"),
            "description": f.get("ai_description", ""),
            "quality_notes": f.get("ai_quality_notes", ""),
            "user_notes": f.get("user_notes", ""),
        })

    return {
        "data_source_id": data_source_id,
        "name": profile.get("file_name", ""),
        "summary": profile.get("ai_summary", ""),
        "usage_summary": profile.get("ai_usage_summary", ""),
        "tags": tags,
        "fields": fields,
        "user_nuances": profile.get("user_nuances", ""),
    }
