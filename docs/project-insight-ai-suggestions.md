# Project Insight — Business-Insight Ask & Suggestions (Before / After)

## What changed

The Project Insight page now opens with the same experience as Business
Insight, placed **above the Executive Project Summary**:

- the "**What would you like to analyze?** Ask anything across your connected
  data, documents, and dashboards." hero ask box,
- the three suggestion pills: **New Query Suggestions**, **New Dashboard
  Suggestions**, **Insights & Opportunities**.

Both pages share the **same backend** — the existing Home-intelligence
endpoints (`/api/ai/home/query-suggestions`, `/api/ai/home/dashboard-suggestions`,
`/api/ai/home/insights`) and the existing conversational-analytics assistant.
The only difference is scope:

| | Business Insight | Project Insight |
|---|---|---|
| Ask box | routes the prompt via `/api/ai/route-prompt` | goes straight to this project's AI assistant (`/projects/{id}/ai?q=…`) — the **same shared conversational-analytics engine**, grounded in this project |
| Suggestion pills | generate for **every accessible project** | generate for **this project only** (`project_id` sent to the same endpoints) |
| Per-project section headers | shown | hidden (redundant inside a project) |

Per instruction, **no conversational-analytics or query-generation/preview
logic was changed**. The Preview modal, SQL generation, dashboard widget
build, and the chat engine are untouched — components and endpoints are
reused as-is. The only backend edit is a two-line request filter (below),
identical to the one `/home/insights` already had.

---

## Before / After

### 1. `platform-api/app/routes/home_intelligence.py` — honor the existing `project_id` field

`SuggestRequest` already carried `project_id: int | None` and `/home/insights`
already honored it. The query- and dashboard-suggestion routes ignored it and
always generated for every accessible project.

**Before** (both `/home/query-suggestions` and `/home/dashboard-suggestions`):

```python
async with SessionLocal() as session:
    projects = await _accessible_projects(session, context)
if not projects:
    return {"projects": []}
```

**After** (the same two-line filter `/home/insights` uses; generation logic
untouched — an inaccessible or foreign `project_id` simply yields `[]`):

```python
async with SessionLocal() as session:
    projects = await _accessible_projects(session, context)
if req.project_id is not None:
    projects = [p for p in projects if p.id == req.project_id]
if not projects:
    return {"projects": []}
```

### 2. `web-ui/lib/api/home-intelligence.ts` — pass the scope through

**Before:**

```ts
export function suggestQueries(
  granularity = 3,
): Promise<{ projects: QuerySuggestionsProject[] }> {
  return apiClient.post("/api/ai/home/query-suggestions", {
    granularity,
    max_per_project: 5,
  });
}

export function suggestDashboards(
  granularity = 3,
): Promise<{ projects: DashboardSuggestionsProject[] }> {
  return apiClient.post("/api/ai/home/dashboard-suggestions", {
    granularity,
    max_per_project: 6,
  });
}
```

**After** (mirrors the signature `suggestInsights` already had):

```ts
export function suggestQueries(
  granularity = 3,
  projectId?: number,
): Promise<{ projects: QuerySuggestionsProject[] }> {
  return apiClient.post("/api/ai/home/query-suggestions", {
    granularity,
    max_per_project: 5,
    project_id: projectId ?? null,
  });
}

export function suggestDashboards(
  granularity = 3,
  projectId?: number,
): Promise<{ projects: DashboardSuggestionsProject[] }> {
  return apiClient.post("/api/ai/home/dashboard-suggestions", {
    granularity,
    max_per_project: 6,
    project_id: projectId ?? null,
  });
}
```

### 3. `web-ui/components/tablescope/home/hero-search.tsx` — project-aware ask box

**Before:** always posted to `/api/ai/route-prompt` and navigated wherever the
router decided.

```ts
export function HeroSearch() {
  ...
  async function submit(prompt: string) {
    const q = prompt.trim();
    if (!q || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await apiClient.post<RoutePromptResponse>(
        "/api/ai/route-prompt",
        { prompt: q },
      );
      ...
```

**After:** an optional `projectId` sends the prompt straight to that project's
AI assistant — the shared conversational-analytics engine — so the answer is
grounded in (and isolated to) the project. Without the prop, Business
Insight's behavior is unchanged.

```ts
export function HeroSearch({
  projectId,
}: {
  /** When set, prompts go straight to this project's AI assistant so the
   *  conversation is grounded in (and isolated to) that project's data. */
  projectId?: string | number;
} = {}) {
  ...
  async function submit(prompt: string) {
    const q = prompt.trim();
    if (!q || submitting) return;
    setSubmitting(true);
    setError(null);
    if (projectId != null) {
      router.push(`/projects/${projectId}/ai?q=${encodeURIComponent(q)}`);
      return;
    }
    try {
      const res = await apiClient.post<RoutePromptResponse>(
        "/api/ai/route-prompt",
        { prompt: q },
      );
      ...
```

### 4. `web-ui/components/tablescope/home/ai-suggestions.tsx` — scoped pills

**Before:** `HomeAiSuggestions()` took no props; every pill generated across
all projects and always rendered per-project headers.

```ts
export function HomeAiSuggestions() {
  ...
  const run = useCallback(async (pill: Pill) => {
    ...
    if (pill === "queries") {
      const res = await suggestQueries();
      ...
  }, []);
```

**After:** an optional `projectId` scopes all three pills to one project,
switches the loading copy, and hides the redundant project headers. The
Preview modal and Save-dashboard flows are reused untouched — they were
already per-project (`projectId` rides on each card).

```ts
export function HomeAiSuggestions({
  projectId,
}: {
  /** When set, every suggestion pill generates for this project only and the
   *  per-project section headers are hidden. Omitted, the original Home
   *  behavior (all accessible projects) applies. */
  projectId?: number;
} = {}) {
  ...
  const run = useCallback(
    async (pill: Pill) => {
      ...
      if (pill === "queries") {
        const res = await suggestQueries(3, projectId);
        ...
    },
    [projectId],
  );

  const scoped = projectId != null;
  ...
  {scoped ? "Generating for this project…" : "Generating across your projects…"}
  ...
  <QuerySuggestionsPanel projects={queryProjects ?? []} showProjectHeader={!scoped} />
  <DashboardSuggestionsPanel projects={dashboardProjects ?? []} showProjectHeader={!scoped} />
  <InsightsPanel projects={insightProjects ?? []} showProjectHeader={!scoped} />
```

(`QuerySuggestionsPanel` and `DashboardSuggestionsPanel` gained the same
`showProjectHeader?: boolean` prop `InsightsPanel` already had.)

### 5. `web-ui/components/tablescope/project-insight/project-insight-screen.tsx` — the new section

**Before:** the page started with the Executive Project Summary.

```tsx
{/* 1. Executive Project Summary */}
<section className="rounded-lg border border-line-tertiary bg-bg-primary p-5">
```

**After:** the Business-Insight hero + pills render first, scoped to the
project:

```tsx
{/* 0. Ask + AI suggestions — same experience as Business Insight,
    scoped to this project. The ask box hands off to the shared
    conversational-analytics assistant; the pills generate query/
    dashboard/insight suggestions for this project only. */}
<div className="space-y-6 py-2">
  <HeroSearch projectId={projectId} />
  <HomeAiSuggestions projectId={Number(projectId)} />
</div>

{/* 1. Executive Project Summary */}
<section className="rounded-lg border border-line-tertiary bg-bg-primary p-5">
```

---

## What was deliberately NOT changed

- **Conversational analytics** — the ask box hands off to the existing shared
  assistant; the engine, intents, and chart handling are untouched.
- **Query generation + preview** — `QuerySuggestionPreviewModal`,
  `_plan_analyses`, SQL generation/repair, and the save flows are reused
  exactly as they run on Business Insight.
- **Dashboard generation** — `plan_and_execute_widgets`, chart building, and
  `saveDashboardSuggestion` are reused as-is; isolation comes purely from the
  request-level project filter.

## Verification

- Backend: `pytest tests/test_home_intelligence.py` — **36 passed**, including
  2 new tests proving `project_id` scopes query- and dashboard-suggestions to
  exactly one project (and that omitting it preserves the all-projects Home
  behavior); `ruff` clean.
- Frontend: `tsc --noEmit` clean; `next lint` clean (one pre-existing
  unrelated warning); `vitest` — **33 passed** across the project-insight and
  home component suites.
