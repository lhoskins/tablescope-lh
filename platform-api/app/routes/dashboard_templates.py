"""Dashboard groups, template mappings, compiled queries and hydration."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.dashboard import Dashboard
from app.models.dashboard_template import DashboardGroup, DashboardTemplateBinding, DashboardTemplateQuery
from app.routes.dashboards_crud import _require_project_access
from app.routes.dashboards_widget_query import _resolve_vdb, _run_widget_sql
from app.routes.projects_datasources import list_project_datasources
from app.services.dashboard_templates import compile_batch_queries, render_sql_template, template_metric_manifest, validate_binding
from app.services.dashboard_templates.compiler import period_bounds
from app.services.dashboard_widget import find_or_create_saved_query
from app.services.tenant_teiid_resolver import TenantTeiidResolver
from app.services.operational_insight_dashboards import (
    CUSTOM_GROUP_SLUG,
    get_or_create_custom_group,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["dashboard-templates"])


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    icon: str = "activity"
    template_id: str | None = None
    collapsed_default: bool = True


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    icon: str | None = None
    position: int | None = None
    collapsed_default: bool | None = None


class SourceProfile(BaseModel):
    viewName: str
    columns: list[str] = Field(default_factory=list)


class MappingPreviewRequest(BaseModel):
    template_id: str
    sources: list[SourceProfile]
    dimension_label: str = "Site"


class BindingCreate(BaseModel):
    template_id: str
    template_name: str
    template_version: str = "1"
    group_key: str
    dashboard_group_id: int | None = None
    dimension_config: dict[str, Any] = Field(default_factory=dict)
    source_mapping: dict[str, str] = Field(default_factory=dict)
    field_mapping: dict[str, dict[str, str]] = Field(default_factory=dict)
    joins: list[dict[str, Any]] = Field(default_factory=list)
    metric_manifest: list[dict[str, Any]] = Field(default_factory=list)


class BindingUpdate(BaseModel):
    dimension_config: dict[str, Any] | None = None
    source_mapping: dict[str, str] | None = None
    field_mapping: dict[str, dict[str, str]] | None = None
    joins: list[dict[str, Any]] | None = None
    metric_manifest: list[dict[str, Any]] | None = None


class BindingApproval(BaseModel):
    dashboard_ids: list[int] = Field(default_factory=list)
    period: str = "30_days"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "dashboard-group"


def _group_out(group: DashboardGroup, dashboard_ids: list[int] | None = None) -> dict[str, Any]:
    return {"id": group.id, "name": group.name, "slug": group.slug, "icon": group.icon, "templateId": group.template_id, "position": group.position, "collapsedDefault": group.collapsed_default, "dashboardIds": dashboard_ids or []}


def _binding_out(binding: DashboardTemplateBinding, queries: list[DashboardTemplateQuery] | None = None) -> dict[str, Any]:
    return {
        "id": binding.id, "templateId": binding.template_id, "templateName": binding.template_name,
        "templateVersion": binding.template_version, "groupKey": binding.group_key,
        "dashboardGroupId": binding.dashboard_group_id, "status": binding.status, "version": binding.version,
        "dimensionConfig": binding.dimension_config, "sourceMapping": binding.source_mapping,
        "fieldMapping": binding.field_mapping, "joins": binding.joins, "metricManifest": binding.metric_manifest,
        "validation": binding.validation, "approvedAt": binding.approved_at.isoformat() if binding.approved_at else None,
        "queries": [{"id": item.id, "queryKey": item.query_key, "savedQueryId": item.saved_query_id, "status": item.status, "version": item.version, "metricKeys": item.metric_keys, "dashboardKeys": item.dashboard_keys, "lineage": item.lineage, "validation": item.validation} for item in (queries or [])],
    }


async def _get_group(project_id: int, group_id: int, session: AsyncSession, context: RequestContext) -> DashboardGroup:
    group = await session.get(DashboardGroup, group_id)
    if group is None or group.project_id != project_id or group.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Dashboard group not found")
    return group


async def _get_binding(project_id: int, binding_id: int, session: AsyncSession, context: RequestContext) -> DashboardTemplateBinding:
    binding = await session.get(DashboardTemplateBinding, binding_id)
    if binding is None or binding.project_id != project_id or binding.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Template binding not found")
    return binding


@router.get("/dashboard-groups")
async def list_dashboard_groups(project_id: int, session: AsyncSession = Depends(get_db), context: RequestContext = Depends(require_role(Role.VIEWER))) -> list[dict[str, Any]]:
    await _require_project_access(project_id, session, context)
    groups = list(await session.scalars(select(DashboardGroup).where(DashboardGroup.project_id == project_id, DashboardGroup.tenant_id == context.tenant_id).order_by(DashboardGroup.position, DashboardGroup.name)))
    dashboards = list(await session.scalars(select(Dashboard).where(Dashboard.project_id == project_id, Dashboard.tenant_id == context.tenant_id)))
    members: dict[int, list[int]] = {group.id: [] for group in groups}
    for dashboard in dashboards:
        group_id = (dashboard.config or {}).get("dashboardGroupId")
        if group_id in members:
            members[group_id].append(dashboard.id)
    return [_group_out(group, members[group.id]) for group in groups]


@router.post("/dashboard-groups", status_code=201)
async def create_dashboard_group(project_id: int, body: GroupCreate, session: AsyncSession = Depends(get_db), context: RequestContext = Depends(require_role(Role.EDITOR))) -> dict[str, Any]:
    await _require_project_access(project_id, session, context)
    base, slug, suffix = _slug(body.name), _slug(body.name), 2
    if slug == CUSTOM_GROUP_SLUG:
        group = await get_or_create_custom_group(
            session,
            tenant_id=context.tenant_id,
            project_id=project_id,
        )
        await session.commit()
        await session.refresh(group)
        return _group_out(group)
    while await session.scalar(select(DashboardGroup.id).where(DashboardGroup.tenant_id == context.tenant_id, DashboardGroup.project_id == project_id, DashboardGroup.slug == slug)):
        slug, suffix = f"{base}-{suffix}", suffix + 1
    position = int(await session.scalar(select(func.count()).select_from(DashboardGroup).where(DashboardGroup.project_id == project_id, DashboardGroup.tenant_id == context.tenant_id)) or 0)
    group = DashboardGroup(tenant_id=context.tenant_id, project_id=project_id, name=body.name.strip(), slug=slug, icon=body.icon, template_id=body.template_id, position=position, collapsed_default=body.collapsed_default)
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return _group_out(group)


@router.put("/dashboard-groups/{group_id}")
async def update_dashboard_group(project_id: int, group_id: int, body: GroupUpdate, session: AsyncSession = Depends(get_db), context: RequestContext = Depends(require_role(Role.EDITOR))) -> dict[str, Any]:
    await _require_project_access(project_id, session, context)
    group = await _get_group(project_id, group_id, session, context)
    for field in ("name", "icon", "position", "collapsed_default"):
        value = getattr(body, field)
        if value is not None:
            setattr(group, field, value.strip() if isinstance(value, str) else value)
    await session.commit()
    await session.refresh(group)
    return _group_out(group)


@router.delete("/dashboard-groups/{group_id}", status_code=204, response_class=Response)
async def delete_dashboard_group(project_id: int, group_id: int, session: AsyncSession = Depends(get_db), context: RequestContext = Depends(require_role(Role.EDITOR))) -> Response:
    await _require_project_access(project_id, session, context)
    group = await _get_group(project_id, group_id, session, context)
    dashboards = list(await session.scalars(select(Dashboard).where(Dashboard.project_id == project_id, Dashboard.tenant_id == context.tenant_id)))
    for dashboard in dashboards:
        config = dict(dashboard.config or {})
        if config.get("dashboardGroupId") == group_id:
            config.pop("dashboardGroupId", None)
            dashboard.config = config
    await session.delete(group)
    await session.commit()
    return Response(status_code=204)


@router.post("/dashboard-groups/{group_id}/dashboards/{dashboard_id}")
async def assign_dashboard_group(project_id: int, group_id: int, dashboard_id: int, session: AsyncSession = Depends(get_db), context: RequestContext = Depends(require_role(Role.EDITOR))) -> dict[str, int]:
    await _require_project_access(project_id, session, context)
    group = await _get_group(project_id, group_id, session, context)
    dashboard = await session.get(Dashboard, dashboard_id)
    if dashboard is None or dashboard.project_id != project_id or dashboard.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    config = dict(dashboard.config or {})
    config["dashboardGroupId"] = group.id
    metadata = dict(config.get("dashboardTemplate") or {})
    metadata.update({"groupId": f"group:{group.id}", "groupName": group.name, "groupIcon": group.icon})
    config["dashboardTemplate"] = metadata
    dashboard.config = config
    await session.commit()
    return {"dashboardId": dashboard.id, "groupId": group.id}


@router.get("/dashboard-template-metrics/{template_id}")
async def get_template_metrics(project_id: int, template_id: str, session: AsyncSession = Depends(get_db), context: RequestContext = Depends(require_role(Role.VIEWER))) -> dict[str, Any]:
    await _require_project_access(project_id, session, context)
    return {"templateId": template_id, "metrics": template_metric_manifest(template_id)}


_FIELD_SYNONYMS = {
    "id": ["id", "number", "sys_id", "ticket_id"], "openedAt": ["opened_at", "opened", "created_at", "created"],
    "closedAt": ["closed_at", "closed", "completed_at"], "resolvedAt": ["resolved_at", "resolved"],
    "site": ["site", "site_code", "location", "region", "plant"], "active": ["active", "is_active", "open"],
    "priority": ["priority", "severity"], "status": ["status", "state"], "slaBreached": ["sla_breached", "breached"],
    "resolutionHours": ["resolution_hours", "resolve_hours", "duration_hours"], "fulfillmentHours": ["fulfillment_hours", "duration_hours"],
    "date": ["date", "period", "transaction_date", "snapshot_date"],
}


def _suggest_column(field: str, columns: list[str]) -> str | None:
    normalized = {re.sub(r"[^a-z0-9]", "", column.lower()): column for column in columns}
    for candidate in [field, *_FIELD_SYNONYMS.get(field, [])]:
        match = normalized.get(re.sub(r"[^a-z0-9]", "", candidate.lower()))
        if match:
            return match
    return None


@router.post("/dashboard-template-bindings/preview")
async def preview_template_mapping(project_id: int, body: MappingPreviewRequest, session: AsyncSession = Depends(get_db), context: RequestContext = Depends(require_role(Role.EDITOR))) -> dict[str, Any]:
    await _require_project_access(project_id, session, context)
    manifest = template_metric_manifest(body.template_id)
    source_mapping: dict[str, str] = {}
    field_mapping: dict[str, dict[str, str]] = {}
    for entity in sorted({metric["entity"] for metric in manifest}):
        fields = {str(value) for metric in manifest if metric["entity"] == entity for value in [metric.get("valueField"), metric.get("dateField"), metric.get("denominatorField"), (metric.get("filter") or {}).get("field"), (metric.get("numeratorFilter") or {}).get("field")] if value} | {"site"}
        source = max(body.sources, key=lambda item: sum(_suggest_column(field, item.columns) is not None for field in fields), default=None)
        if source:
            source_mapping[entity] = source.viewName
            field_mapping[entity] = {field: column for field in fields if (column := _suggest_column(field, source.columns))}
    dimension = {"label": body.dimension_label, "field": "site", "valueSource": "query"}
    validation = validate_binding(source_mapping=source_mapping, field_mapping=field_mapping, metric_manifest=manifest, dimension_config=dimension)
    return {"metricManifest": manifest, "sourceMapping": source_mapping, "fieldMapping": field_mapping, "dimensionConfig": dimension, "validation": validation}


@router.post("/dashboard-template-bindings", status_code=201)
async def create_template_binding(project_id: int, body: BindingCreate, session: AsyncSession = Depends(get_db), context: RequestContext = Depends(require_role(Role.EDITOR))) -> dict[str, Any]:
    await _require_project_access(project_id, session, context)
    version = int(await session.scalar(select(func.max(DashboardTemplateBinding.version)).where(DashboardTemplateBinding.tenant_id == context.tenant_id, DashboardTemplateBinding.project_id == project_id, DashboardTemplateBinding.template_id == body.template_id, DashboardTemplateBinding.group_key == body.group_key)) or 0) + 1
    manifest = body.metric_manifest or template_metric_manifest(body.template_id)
    validation = validate_binding(source_mapping=body.source_mapping, field_mapping=body.field_mapping, metric_manifest=manifest, dimension_config=body.dimension_config)
    binding = DashboardTemplateBinding(tenant_id=context.tenant_id, project_id=project_id, dashboard_group_id=body.dashboard_group_id, template_id=body.template_id, template_name=body.template_name, template_version=body.template_version, group_key=body.group_key, status="draft", version=version, dimension_config=body.dimension_config, source_mapping=body.source_mapping, field_mapping=body.field_mapping, joins=body.joins, metric_manifest=manifest, validation=validation)
    session.add(binding)
    await session.commit()
    await session.refresh(binding)
    return _binding_out(binding)


@router.get("/dashboard-template-bindings")
async def list_template_bindings(project_id: int, session: AsyncSession = Depends(get_db), context: RequestContext = Depends(require_role(Role.VIEWER))) -> list[dict[str, Any]]:
    await _require_project_access(project_id, session, context)
    bindings = list(await session.scalars(select(DashboardTemplateBinding).where(DashboardTemplateBinding.project_id == project_id, DashboardTemplateBinding.tenant_id == context.tenant_id).order_by(DashboardTemplateBinding.updated_at.desc())))
    return [_binding_out(binding) for binding in bindings]


@router.put("/dashboard-template-bindings/{binding_id}")
async def update_template_binding(project_id: int, binding_id: int, body: BindingUpdate, session: AsyncSession = Depends(get_db), context: RequestContext = Depends(require_role(Role.EDITOR))) -> dict[str, Any]:
    await _require_project_access(project_id, session, context)
    binding = await _get_binding(project_id, binding_id, session, context)
    requires_reapproval = any(value is not None for value in (body.source_mapping, body.field_mapping, body.joins, body.metric_manifest))
    if body.dimension_config is not None:
        previous = binding.dimension_config or {}
        requires_reapproval = requires_reapproval or any(body.dimension_config.get(key) != previous.get(key) for key in ("field", "valueSource"))
    for field in ("dimension_config", "source_mapping", "field_mapping", "joins", "metric_manifest"):
        if (value := getattr(body, field)) is not None:
            setattr(binding, field, value)
    binding.validation = validate_binding(source_mapping=binding.source_mapping, field_mapping=binding.field_mapping, metric_manifest=binding.metric_manifest, dimension_config=binding.dimension_config)
    if requires_reapproval:
        binding.status = "draft"
    await session.commit()
    await session.refresh(binding)
    return _binding_out(binding)


async def _validate_sources(project_id: int, binding: DashboardTemplateBinding, session: AsyncSession, context: RequestContext) -> dict[str, Any]:
    validation = validate_binding(source_mapping=binding.source_mapping, field_mapping=binding.field_mapping, metric_manifest=binding.metric_manifest, dimension_config=binding.dimension_config)
    allowed = {source.get("viewName") for source in await list_project_datasources(project_id=project_id, include_archived=False, session=session, context=context)}
    foreign = sorted(set(binding.source_mapping.values()) - allowed)
    if foreign:
        validation["valid"] = False
        validation["errors"].append(f"Datasource is not assigned to this project: {', '.join(foreign)}")
    return validation


@router.post("/dashboard-template-bindings/{binding_id}/validate")
async def validate_template_binding_endpoint(project_id: int, binding_id: int, session: AsyncSession = Depends(get_db), context: RequestContext = Depends(require_role(Role.EDITOR))) -> dict[str, Any]:
    await _require_project_access(project_id, session, context)
    binding = await _get_binding(project_id, binding_id, session, context)
    binding.validation = await _validate_sources(project_id, binding, session, context)
    await session.commit()
    return binding.validation


def _metric_for_widget(widget: dict[str, Any], manifest: list[dict[str, Any]]) -> dict[str, Any] | None:
    title = re.sub(r"[^a-z0-9]", "", str(widget.get("title", "")).lower())
    for metric in manifest:
        if any(re.sub(r"[^a-z0-9]", "", str(candidate).lower()) in title for candidate in (metric.get("key"), metric.get("label")) if candidate):
            return metric
    return None


@router.post("/dashboard-template-bindings/{binding_id}/approve")
async def approve_template_binding(project_id: int, binding_id: int, body: BindingApproval, session: AsyncSession = Depends(get_db), context: RequestContext = Depends(require_role(Role.EDITOR))) -> dict[str, Any]:
    await _require_project_access(project_id, session, context)
    if context.user_id is None:
        raise HTTPException(status_code=401, detail="An authenticated user is required to approve datasource mappings")
    binding = await _get_binding(project_id, binding_id, session, context)
    validation = await _validate_sources(project_id, binding, session, context)
    if not validation["valid"]:
        binding.validation = validation
        await session.commit()
        raise HTTPException(status_code=422, detail=validation)
    try:
        compiled = compile_batch_queries(source_mapping=binding.source_mapping, field_mapping=binding.field_mapping, metric_manifest=binding.metric_manifest, dimension_config=binding.dimension_config, period=body.period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    existing = list(await session.scalars(select(DashboardTemplateQuery).where(DashboardTemplateQuery.binding_id == binding.id)))
    query_version = max((item.version for item in existing), default=0) + 1
    for item in existing:
        if item.status == "approved":
            item.status = "superseded"
    created: list[DashboardTemplateQuery] = []
    for item in compiled:
        saved = await find_or_create_saved_query(session, project_id=project_id, title=f"{binding.template_name} · {item.query_key} · v{query_version}", sql=item.compiled_sql, user_id=context.user_id, allowed_tables=list(binding.source_mapping.values()))
        query = DashboardTemplateQuery(tenant_id=context.tenant_id, project_id=project_id, binding_id=binding.id, saved_query_id=saved.id, query_key=item.query_key, status="approved", version=query_version, sql_template=item.sql_template, compiled_sql=item.compiled_sql, dashboard_keys=item.dashboard_keys, metric_keys=item.metric_keys, lineage=item.lineage, validation={"valid": True, "validatedAt": datetime.now(UTC).isoformat()})
        session.add(query)
        created.append(query)
    for dashboard_id in body.dashboard_ids:
        dashboard = await session.get(Dashboard, dashboard_id)
        if dashboard and dashboard.project_id == project_id and dashboard.tenant_id == context.tenant_id:
            config = dict(dashboard.config or {})
            config.update({"presentation": "operational_insight", "templateBindingId": binding.id})
            widgets = []
            for widget in config.get("widgets", []):
                next_widget = dict(widget)
                if metric := _metric_for_widget(next_widget, binding.metric_manifest):
                    next_widget["templateMetricKey"] = metric["key"]
                    options = dict(next_widget.get("visualizationOptions") or {})
                    options["colorScheme"] = "operational_insight"
                    options["favorableDirection"] = metric.get("polarity", "neutral")
                    next_widget["visualizationOptions"] = options
                widgets.append(next_widget)
            config["widgets"] = widgets
            if binding.dashboard_group_id:
                config["dashboardGroupId"] = binding.dashboard_group_id
            dashboard.config = config
    binding.status = "approved"
    binding.validation = {**validation, "compiledQueryCount": len(created), "compiledQueryVersion": query_version}
    binding.approved_by = context.user_id
    binding.approved_at = datetime.now(UTC)
    await session.commit()
    for item in created:
        await session.refresh(item)
    return _binding_out(binding, created)


_HYDRATION_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


@router.get("/dashboard-template-bindings/{binding_id}/hydrate")
async def hydrate_template_dashboard(project_id: int, binding_id: int, period: str = Query(default="30_days"), dimension: str | None = Query(default=None), refresh: bool = Query(default=False), session: AsyncSession = Depends(get_db), context: RequestContext = Depends(require_role(Role.VIEWER))) -> dict[str, Any]:
    await _require_project_access(project_id, session, context)
    binding = await _get_binding(project_id, binding_id, session, context)
    if binding.status != "approved":
        raise HTTPException(status_code=409, detail="Datasource mapping must be approved before hydration")
    query_version = int((binding.validation or {}).get("compiledQueryVersion") or binding.version)
    cache_key = f"{context.tenant_id}:{project_id}:{binding.id}:{query_version}:{period}:{dimension or '*'}"
    cached = _HYDRATION_CACHE.get(cache_key)
    if cached and not refresh and cached[0] > time.monotonic():
        return {**cached[1], "cacheStatus": "hit"}
    try:
        bounds = period_bounds(period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    queries = list(await session.scalars(select(DashboardTemplateQuery).where(DashboardTemplateQuery.binding_id == binding.id, DashboardTemplateQuery.status == "approved").order_by(DashboardTemplateQuery.id)))
    database = await _resolve_vdb(session=session, context=context, project_id=project_id)
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    batches: list[dict[str, Any]] = []
    metrics: dict[str, dict[str, Any]] = {}
    dimension_field = binding.dimension_config.get("field")
    for query in queries:
        entity = query.lineage.get("entity")
        dimension_column = (binding.field_mapping.get(entity) or {}).get(dimension_field) if dimension_field else None
        sql = render_sql_template(query.sql_template, **bounds, dimension_column=dimension_column if query.lineage.get("kind") == "summary" else None, dimension_value=dimension)
        result = await _run_widget_sql(database=database, sql=sql, teiid_host=endpoint.pg_host, teiid_port=endpoint.pg_port)
        batches.append({"queryKey": query.query_key, "columns": result["columns"], "rows": result["rows"], "metricKeys": query.metric_keys, "lineage": query.lineage})
        if query.lineage.get("kind") == "summary" and result["rows"]:
            row = result["rows"][0]
            for key in query.metric_keys:
                current, previous = row.get(key), row.get(f"{key}__previous")
                delta = 100.0 * (current - previous) / abs(previous) if isinstance(current, int | float) and isinstance(previous, int | float) and previous else None
                metrics[key] = {"value": current, "previousValue": previous, "deltaPercent": delta}
    payload = {"bindingId": binding.id, "bindingVersion": binding.version, "queryVersion": query_version, "period": period, "dimension": dimension, "dimensionConfig": binding.dimension_config, "metricManifest": binding.metric_manifest, "metrics": metrics, "batches": batches, "hydratedAt": datetime.now(UTC).isoformat(), "cacheStatus": "refreshed" if refresh else "miss"}
    ttl = min((query.cache_ttl_seconds for query in queries), default=300)
    _HYDRATION_CACHE[cache_key] = (time.monotonic() + ttl, payload)
    return payload
