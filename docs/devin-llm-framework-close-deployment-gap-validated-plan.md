# Devin-Ready Plan: Close the LLM Framework Deployment Gap

## Summary

Phases 1–6 of the LLM Framework (platform-scoped inventory, Hugging Face
catalog, Model Vault staging, deployment/routing/canary/rollback, embedding
re-index, FP16→GGUF conversion) are all merged into this branch's history.
The backend is substantially complete. But the feature is **not usable
end-to-end**: there is no way to register a runtime target, so install can
never succeed regardless of UI wiring; the frontend never wires the
install/approve/activate/rollback/routing endpoints it already has clients
for; and a security control the UI claims is active (two-person approval)
is not actually enforced. This plan closes those gaps in five phases, each
independently shippable.

All root causes below were verified by reading the actual code on
`origin/devin/r-echarts-e2e-validation` (the branch this repo has deployed;
it already contains everything from
`devin/llm-framework-huggingface-offline-deployment`), not from the plan
that requested Phases 1–6.

## Phase A — Runtime target registration (unblocks everything else)

### Root cause

`LLMRuntimeTarget` (`platform-api/app/models/llm_framework.py:47-63`) is
never instantiated anywhere in the codebase outside its own class
definition. There is no `POST` route to create one:

```
$ grep -n "target" platform-api/app/routes/llm_framework.py
129:        "targets": inventory["targets"],
267:        report = await preflight_install(session, artifact_id=artifact_id, target_id=request.target_id)
...
```
— every reference reads an existing `target_id`; none creates a row.
Migration `0070_llm_framework.py` creates the table but seeds no data.
`preflight_install` (`platform-api/app/services/llm_deployment.py:53-55`)
raises `DeploymentError("Runtime target not found")` for any `target_id`
that doesn't already exist. Since no target can ever exist, `preflight`,
`install`, `activate`, and routing-profile assignment are unreachable no
matter what the frontend does — this is the actual root cause behind the
"no install button" symptom, not just a missing UI element.

`docker-compose.yml:126` already wires `LLM_OLLAMA_URL:
${LLM_OLLAMA_URL:-http://ollama:11434}` into `platform-api`, and
`platform-api/app/services/llm_ollama_adapter.py:66` /
`llm_deployment.py:73,117,300` already use `settings.llm_ollama_url` as the
runtime endpoint for preflight/install/rollback — the primary target's host
is already known to the app. It just never becomes a `LLMRuntimeTarget` row.

### Fix

Two parts: a registration endpoint for operators to add targets (including
future remote/secondary targets), and an idempotent startup step that
registers the already-configured primary Ollama target so a fresh
deployment isn't empty by default.

**1. Schema** — `platform-api/app/schemas/llm_framework.py`, add near
`RuntimeTargetSummary`:

```python
class RuntimeTargetCreate(BaseModel):
    name: str
    host: str
    runtime_type: str = "ollama"
    version: str | None = None
    max_loaded_models: int | None = None
    keep_alive_minutes: int | None = None
    labels: dict = {}
```

**2. Service** — `platform-api/app/services/llm_framework.py`, add:

```python
from app.models.llm_framework import LLMRuntimeTarget  # already imported
from app.services.llm_ollama_adapter import OllamaAdapter


class DuplicateRuntimeTargetError(ValueError):
    """Raised when a target with the same name already exists."""


async def register_runtime_target(
    session: AsyncSession,
    *,
    name: str,
    host: str,
    runtime_type: str = "ollama",
    version: str | None = None,
    max_loaded_models: int | None = None,
    keep_alive_minutes: int | None = None,
    labels: dict | None = None,
) -> LLMRuntimeTarget:
    """Register a runtime target. Probes reachability but does not require it —
    an operator may register a target before it comes online."""
    existing = await session.scalar(
        select(LLMRuntimeTarget).where(LLMRuntimeTarget.name == name)
    )
    if existing is not None:
        raise DuplicateRuntimeTargetError(f"A runtime target named '{name}' already exists")

    is_reachable = False
    last_seen_at = None
    if runtime_type == "ollama":
        try:
            result = await OllamaAdapter(base_url=host).preflight(
                artifact_size=0, reserve_bytes=0
            )
            is_reachable = result.reachable
            if is_reachable:
                last_seen_at = datetime.now(UTC)
        except Exception:
            logger.warning("Reachability probe failed for new target %s (%s)", name, host)

    target = LLMRuntimeTarget(
        name=name,
        runtime_type=runtime_type,
        host=host,
        version=version,
        status="active",
        is_reachable=is_reachable,
        last_seen_at=last_seen_at,
        max_loaded_models=max_loaded_models,
        keep_alive_minutes=keep_alive_minutes,
        labels=labels or {},
    )
    session.add(target)
    await session.flush()
    return target


async def ensure_primary_runtime_target_registered(session: AsyncSession) -> None:
    """Idempotently register the configured primary Ollama target on startup,
    so a fresh deployment has a usable target without a manual step."""
    settings = get_settings()
    existing = await session.scalar(
        select(LLMRuntimeTarget).where(LLMRuntimeTarget.host == settings.llm_ollama_url)
    )
    if existing is not None:
        return
    try:
        await register_runtime_target(
            session, name="primary-ollama", host=settings.llm_ollama_url,
        )
        await session.commit()
    except DuplicateRuntimeTargetError:
        await session.rollback()
```

Needs `from datetime import UTC, datetime` added to the service module's
imports (not currently imported there).

**3. Route** — `platform-api/app/routes/llm_framework.py`, add after the
inventory endpoint:

```python
@router.post("/runtime-targets", response_model=RuntimeTargetSummary, status_code=201)
async def create_llm_runtime_target(
    request: RuntimeTargetCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_human_platform_admin),
) -> LLMRuntimeTarget:
    _require_enabled()
    try:
        target = await register_runtime_target(
            session,
            name=request.name,
            host=request.host,
            runtime_type=request.runtime_type,
            version=request.version,
            max_loaded_models=request.max_loaded_models,
            keep_alive_minutes=request.keep_alive_minutes,
            labels=request.labels,
        )
    except DuplicateRuntimeTargetError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return target
```

Uses `require_human_platform_admin` (not `require_platform_admin`) —
registering infrastructure a service identity could then install models
onto is a governance action, matching the guard's own documented intent
(`rbac.py:112`, `:130-146`).

**4. Startup wiring** — `platform-api/app/main.py`, in `lifespan`, alongside
the existing `_reconcile_db_sources_on_startup()` background task
(`main.py:143`): call `ensure_primary_runtime_target_registered` against a
fresh session before or alongside that task. Follow the same
try/log-don't-crash pattern already used there — a reachability hiccup
against Ollama at boot must not block API startup.

### Tests

`platform-api/tests/test_llm_framework.py` — add:
- `register_runtime_target` creates a row with the given fields.
- Registering a second target with the same `name` raises
  `DuplicateRuntimeTargetError`.
- `ensure_primary_runtime_target_registered` is idempotent: calling it
  twice results in exactly one row for `settings.llm_ollama_url`.

`platform-api/tests/test_rbac.py` — extend the existing LLM platform-admin
block (pattern at `test_rbac.py:90-121`) with: `POST
/runtime-targets` is rejected for a service caller (must use
`require_human_platform_admin`, not `require_platform_admin`).

## Phase B — Close the two-person-approval bypass (security fix)

### Root cause

`llm_two_person_approval_required` defaults to `True`
(`platform-api/app/config.py:104`) and is surfaced in the UI as "Two-person
approval: Required" (`page.tsx` status section, reading
`FrameworkStatusResponse.two_person_approval_required`) — but the setting
is **read nowhere except that status display**:

```
$ grep -rn "llm_two_person_approval_required" platform-api/app/
platform-api/app/config.py:104:    llm_two_person_approval_required: bool = True
platform-api/app/routes/llm_framework.py:94,112  (status response only)
```

`activate_deployment` (`platform-api/app/services/llm_deployment.py:186-238`)
accepts a deployment in either `"pending"` or `"approved"` status:

```python
if deployment.status not in ("pending", "approved"):
    raise DeploymentError(f"Deployment is {deployment.status}, cannot activate")
```

So a single `require_human_platform_admin` caller can install and then
immediately activate a deployment — `approve_deployment` (which correctly
enforces `deployment.requested_by_user_id != approved_by_user_id` at
`llm_deployment.py:177`) is never required to run first. The UI's "Required"
badge does not reflect actual enforcement.

### Fix

`platform-api/app/services/llm_deployment.py`:

```diff
 async def activate_deployment(
     session: AsyncSession,
     deployment_id: int,
     *,
     capability: str,
     target_id: int,
 ) -> LLMDeployment:
     """Promote an installation to the active routing profile for a capability.

     Sets the deployment status to ``stabilizing`` so the stabilization window
     can be observed before it is considered permanently active.
     """
     settings = get_settings()
     if not settings.llm_dynamic_routing_enabled:
         raise DeploymentError("Dynamic routing is disabled")

     deployment = await session.get(LLMDeployment, deployment_id)
     if deployment is None:
         raise DeploymentError("Deployment not found")
-    if deployment.status not in ("pending", "approved"):
-        raise DeploymentError(f"Deployment is {deployment.status}, cannot activate")
+    required_status = "approved" if settings.llm_two_person_approval_required else "pending"
+    allowed_statuses = ("approved",) if settings.llm_two_person_approval_required else ("pending", "approved")
+    if deployment.status not in allowed_statuses:
+        raise DeploymentError(
+            f"Deployment is {deployment.status}, requires {required_status} to activate"
+        )
```

### Tests

`platform-api/tests/` (new or existing deployment test module) — add:
- With `llm_two_person_approval_required=True` (default), `activate_deployment`
  on a `"pending"` deployment raises `DeploymentError`.
- The same deployment activates successfully after `approve_deployment` runs.
- With the setting overridden `False`, activation from `"pending"` still
  succeeds (preserves existing behavior for deployments that opt out).

## Phase C — Wire the audit trail

### Root cause

`LLMAuditEvent` (`platform-api/app/models/llm_framework.py:257-271`) is
created by migration 0070 specifically for this feature but is never
written to:

```
$ grep -rn "LLMAuditEvent" platform-api/app/ --include=*.py | grep -v models/
platform-api/app/models/__init__.py:72
platform-api/app/models/__init__.py:178
```
Only the model export — no `session.add(LLMAuditEvent(...))` anywhere.
Every governance mutation (stage, quarantine-release, install, approve,
activate, rollback, and the new register-target from Phase A) currently
leaves no record of who did what, defeating the purpose of gating them
behind two-person approval in the first place.

### Fix

`platform-api/app/services/llm_framework.py`, add a small helper:

```python
from app.models.llm_framework import LLMAuditEvent  # add to existing import


async def record_llm_audit_event(
    session: AsyncSession,
    *,
    actor_user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None,
    details: dict | None = None,
) -> None:
    session.add(
        LLMAuditEvent(
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )
```

Call it from each governance route in
`platform-api/app/routes/llm_framework.py`, before `session.commit()`:
`create_llm_runtime_target` (action `"register_target"`), `stage_llm_artifact_from_catalog`
(`"stage_artifact"`), `release_quarantined_llm_artifact`
(`"quarantine_release"`), `install_llm_artifact` (`"install"`),
`approve_llm_deployment` (`"approve"`), `activate_llm_deployment`
(`"activate"`), `rollback_llm_deployment` (`"rollback"`). Use
`context.user_id` for `actor_user_id` (service callers pass `None` since
`require_human_platform_admin` already excludes them from every route
except stage/quarantine-release, which use `require_human_platform_admin`
too — so `context.user_id` is always a real user here).

Add a read endpoint so the trail is visible:

```python
@router.get("/audit-events", response_model=list[AuditEventSummary])
async def list_llm_audit_events(
    limit: int = 50,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(require_platform_admin),
) -> Any:
    _require_enabled()
    events = (
        await session.scalars(
            select(LLMAuditEvent).order_by(LLMAuditEvent.created_at.desc()).limit(min(limit, 200))
        )
    ).all()
    return events
```

with `AuditEventSummary` added to `schemas/llm_framework.py` mirroring the
model's fields (`from_attributes=True`, same pattern as
`RuntimeTargetSummary`).

### Tests

- Each governance route, called successfully, results in exactly one new
  `LLMAuditEvent` row with the expected `action`/`entity_id`.
- `GET /audit-events` returns them newest-first.

## Phase D — List deployments (needed before the UI can act on them)

### Root cause

There is no way to discover a `deployment_id` to approve/activate/rollback.
`InventoryResponse` (`schemas/llm_framework.py:102-108`) does not include
deployments, and no `GET /deployments` route exists — only
`POST /deployments/{id}/approve|activate|rollback`, all of which require
already knowing the ID. `install_llm_artifact`
(`routes/llm_framework.py:280-306`) queues work asynchronously and returns
a placeholder `"deployment_id": 0` (the real row is created later by the
worker), so the immediate response can't be used to populate an ID either
— a list endpoint is the only way to find it, matching the polling pattern
this codebase already uses for migrations/conversions.

### Fix

**Schema** — `schemas/llm_framework.py`, add:

```python
class DeploymentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    installation_id: int
    artifact_id: int
    artifact_name: str
    target_id: int
    target_name: str
    requested_by_user_id: int | None
    approved_by_user_id: int | None
    status: str
    previous_deployment_id: int | None
    stabilized_at: datetime | None
    created_at: datetime
    updated_at: datetime
```

**Service** — `platform-api/app/services/llm_framework.py`:

```python
async def list_deployments(session: AsyncSession, *, limit: int = 50) -> list[dict]:
    rows = (
        await session.execute(
            select(LLMDeployment, LLMInstallation, LLMModelArtifact, LLMRuntimeTarget)
            .join(LLMInstallation, LLMDeployment.installation_id == LLMInstallation.id)
            .join(LLMModelArtifact, LLMInstallation.artifact_id == LLMModelArtifact.id)
            .join(LLMRuntimeTarget, LLMInstallation.target_id == LLMRuntimeTarget.id)
            .order_by(LLMDeployment.created_at.desc())
            .limit(min(limit, 200))
        )
    ).all()
    return [
        {
            "id": d.id,
            "installation_id": d.installation_id,
            "artifact_id": a.id,
            "artifact_name": a.name,
            "target_id": t.id,
            "target_name": t.name,
            "requested_by_user_id": d.requested_by_user_id,
            "approved_by_user_id": d.approved_by_user_id,
            "status": d.status,
            "previous_deployment_id": d.previous_deployment_id,
            "stabilized_at": d.stabilized_at,
            "created_at": d.created_at,
            "updated_at": d.updated_at,
        }
        for d, i, a, t in rows
    ]
```

Needs `LLMDeployment` added to the `from app.models.llm_framework import
(...)` block in this module (currently imports `LLMInstallation`,
`LLMModelArtifact`, `LLMRoutingProfile`, `LLMRuntimeTarget`, not
`LLMDeployment`).

**Route** — `platform-api/app/routes/llm_framework.py`:

```python
@router.get("/deployments", response_model=list[DeploymentSummary])
async def list_llm_deployments(
    limit: int = 50,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(require_platform_admin),
) -> Any:
    _require_enabled()
    return await list_deployments(session, limit=limit)
```

### Tests

`list_deployments` returns joined artifact/target names, ordered
newest-first, for a deployment created via the existing install→worker
flow (or a directly-inserted fixture row if the worker isn't exercised in
this test module).

## Phase E — Frontend: wire installed endpoints, browse the catalog

### Root cause

`web-ui/app/admin/llm-framework/page.tsx` imports and calls only
`getLLMFrameworkStatus`, `getLLMInventory`, `getLLMCapabilities`,
`searchLLMCatalog`, `stageLLMArtifact`, `reindexLLMArtifact`,
`getLLMEmbeddingMigrations`, `convertLLMCatalogEntry`,
`getLLMModelConversions`. The client library
(`web-ui/lib/api/llm-framework.ts:225-284`) already exports
`preflightLLMInstall`, `installLLMArtifact`, `approveLLMDeployment`,
`activateLLMDeployment`, `rollbackLLMDeployment`,
`upsertLLMRoutingProfile`, `releaseLLMArtifactQuarantine` — none are
referenced from the page. That's the entire "no install button" gap on the
frontend side, on top of the backend gaps closed in Phases A–D.

Separately, `CatalogPanel` (`page.tsx:206-208`) only searches when
`query.length > 0` — there is no default/browse view:

```tsx
const searchQuery = useQuery({
  queryKey: ["llm-framework", "catalog", query],
  queryFn: () => searchLLMCatalog(query),
  enabled: query.length > 0,
});
```

### Fix

**1. Browse by default.** Change `enabled: query.length > 0` to
`enabled: true` and seed `query` with an empty string that the backend
treats as "no filter" plus a sensible default ranking. In
`platform-api/app/services/llm_catalog_client.py:181-186`, add
`sort`/`direction` so an empty query returns popular GGUF models instead
of an arbitrary HF ordering:

```diff
         params: dict[str, Any] = {
             "search": query,
             "limit": limit,
             "full": "full",
             "config": "false",
+            "sort": "downloads",
+            "direction": "-1",
         }
```

In `page.tsx`, add a "Browse popular models" label state so the input
starts empty but the query still fires:

```diff
   const searchQuery = useQuery({
     queryKey: ["llm-framework", "catalog", query],
     queryFn: () => searchLLMCatalog(query),
-    enabled: query.length > 0,
+    enabled: true,
   });
```

(`searchQuery.isSuccess` already gates the results list, so an empty-string
initial fetch renders exactly like a normal search once it resolves — no
other change needed in that branch.)

**2. Runtime targets management.** Add a "Register target" form to the
Inventory tab's Runtime targets section (name, host, runtime type) that
calls a new `registerLLMRuntimeTarget()` client function (mirror the
existing `stageLLMArtifact` mutation pattern) hitting Phase A's
`POST /runtime-targets`. Invalidate the `["llm-framework", "inventory"]`
query on success so the table updates.

**3. Install action on staged/verified artifacts.** In `ArtifactsTable`
(`page.tsx:100-135`), add an "Install" button per row when
`artifact.status === "verified"`. On click, open a small target-picker
(populated from `inventoryQuery.data.targets`) and call
`preflightLLMInstall(artifactId, targetId)` then, if `target_reachable &&
disk_ok && slot_ok`, `installLLMArtifact(artifactId, targetId)`. Surface
the preflight failure reason inline rather than silently blocking, matching
how `MigrationsPanel`/`ConversionsPanel` already surface
`mutation.isError`.

**4. Deployments tab.** Add a fifth tab (`"deployments"`) alongside
inventory/catalog/migrations/conversions, backed by Phase D's `GET
/deployments` (poll every 5s, same pattern as `MigrationsPanel`). Each row
shows artifact/target/status and, depending on status: `"pending"` →
Approve button (`approveLLMDeployment`); `"approved"` → capability select +
Activate button (`activateLLMDeployment`); any activated/stabilizing row →
Rollback button (`rollbackLLMDeployment`). Gate Approve/Activate on
`statusQuery.data?.deployment_enabled` and
`statusQuery.data?.two_person_approval_required` the same way
`MigrationsPanel`/`ConversionsPanel` already gate their forms on
`isEnabled`, so the UI doesn't offer actions the backend will now
correctly reject per Phase B.

**5. Routing profiles.** Add a minimal form to the Inventory tab's routing
profiles section (capability select, target select, installation ID,
priority) calling `upsertLLMRoutingProfile`, so operators can promote a
completed installation into serving traffic without needing direct API
access. Lower priority than 1–4 if time-boxing is needed — routing without
an active deployment mostly matters once installs are actually happening.

### Tests

`web-ui/app/admin/llm-framework/` (new `page.test.tsx`, none currently
exists) using the existing RTL + vitest setup used elsewhere in `web-ui`:
- Catalog panel fires a search on mount with an empty query (browse-by-default).
- Register-target form calls `registerLLMRuntimeTarget` with the entered
  fields and refetches inventory on success.
- Install button only renders for `status === "verified"` artifacts, not
  `"staged"`/`"pending"`/`"quarantined"`.
- Deployments tab renders Approve for `"pending"`, Activate for
  `"approved"`, Rollback for `"stabilizing"`, and shows nothing actionable
  when `deployment_enabled` is `false`.

## Sequencing note

Phase A must land first — nothing downstream is reachable without a
runtime target existing. Phase B (the approval bypass) should land before
Phase E ships an Activate button, so the button is backed by real
enforcement from the moment it appears. C and D can land in either order,
both before E part 4 (Deployments tab needs D's list endpoint; audit
visibility from C is independent but should exist before the UI makes
these actions easy to trigger repeatedly).

## Out of scope

- Multi-target load balancing / weighted routing beyond the existing
  single-active-profile-per-capability model — not requested, no evidence
  the plan that produced Phases 1–6 called for it either.
- The `LLM_DEPLOYMENT_AGENT_URL` remote-agent path
  (`llm_deployment.py` module docstring) — no agent implementation exists
  in this repo to validate against; Phase A's reachability probe only
  covers the local/direct-Ollama path already used by preflight/install.
- Alembic migration coordination: no new migration is required by this
  plan (Phase A adds no columns, only a service function and a route).

## Branch / PR

Branch: `devin/llm-framework-close-deployment-gap`, based on
`origin/devin/r-echarts-e2e-validation` (already contains all of Phases
1–6). This doc is the only change on the branch; Devin implements Phases
A–E.
