"""Dependency inventory for tenant decommission preview and audit."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import BillingSubscription
from app.models.dashboard import Dashboard
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.project_action import ProjectAction
from app.models.saas_object_data_source import SaasObjectDataSource
from app.models.saved_query import SavedQuery
from app.models.user import User


@dataclass(slots=True)
class TenantDependencyInventory:
    user_count: int
    project_count: int
    project_action_count: int
    database_source_count: int
    saas_source_count: int
    file_source_count: int
    saved_query_count: int
    dashboard_count: int
    has_active_billing_subscription: bool


async def collect_tenant_dependency_inventory(
    session: AsyncSession,
    tenant_id: int,
) -> TenantDependencyInventory:
    """Count tenant-owned application dependencies that will be removed."""
    project_ids = list(
        (
            await session.scalars(
                select(Project.id).where(Project.tenant_id == tenant_id)
            )
        ).all()
    )

    user_count = await session.scalar(
        select(func.count(User.id)).where(User.tenant_id == tenant_id)
    ) or 0

    project_count = len(project_ids)

    project_action_count = 0
    if project_ids:
        project_action_count = (
            await session.scalar(
                select(func.count(ProjectAction.id)).where(
                    ProjectAction.project_id.in_(project_ids)
                )
            )
            or 0
        )

    database_source_count = (
        await session.scalar(
            select(func.count(DatabaseDataSource.id)).where(
                DatabaseDataSource.tenant_id == tenant_id
            )
        )
        or 0
    )
    saas_source_count = (
        await session.scalar(
            select(func.count(SaasObjectDataSource.id)).where(
                SaasObjectDataSource.tenant_id == tenant_id
            )
        )
        or 0
    )
    file_source_count = (
        await session.scalar(
            select(func.count(FileSourceMeta.id)).where(
                FileSourceMeta.tenant_id == tenant_id
            )
        )
        or 0
    )

    saved_query_count = 0
    dashboard_count = 0
    if project_ids:
        saved_query_count = (
            await session.scalar(
                select(func.count(SavedQuery.id)).where(
                    SavedQuery.project_id.in_(project_ids)
                )
            )
            or 0
        )
        dashboard_count = (
            await session.scalar(
                select(func.count(Dashboard.id)).where(
                    Dashboard.project_id.in_(project_ids)
                )
            )
            or 0
        )

    billing = (
        await session.scalar(
            select(BillingSubscription).where(
                BillingSubscription.tenant_id == tenant_id,
                BillingSubscription.subscription_status.in_(
                    ["active", "trialing", "past_due"]
                ),
            )
        )
    ) is not None

    return TenantDependencyInventory(
        user_count=user_count,
        project_count=project_count,
        project_action_count=project_action_count,
        database_source_count=database_source_count,
        saas_source_count=saas_source_count,
        file_source_count=file_source_count,
        saved_query_count=saved_query_count,
        dashboard_count=dashboard_count,
        has_active_billing_subscription=billing,
    )


def inventory_to_dict(inventory: TenantDependencyInventory) -> dict:
    return {
        "users": inventory.user_count,
        "projects": inventory.project_count,
        "project_actions": inventory.project_action_count,
        "database_data_sources": inventory.database_source_count,
        "saas_object_data_sources": inventory.saas_source_count,
        "file_sources": inventory.file_source_count,
        "saved_queries": inventory.saved_query_count,
        "dashboards": inventory.dashboard_count,
        "active_billing_subscription": inventory.has_active_billing_subscription,
    }
