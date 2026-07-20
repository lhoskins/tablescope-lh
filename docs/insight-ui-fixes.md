# AI Dashboard Naming, Sidebar, and Insight/Suggestion Surface Fixes

This document captures the changes made to implement the `Fix+AI+dashboard+naming+sidebar+and+insight:suggestion+surfaces+.docx` plan.

---

## ITEM 4 — Unique AI Dashboard Names

### Goal
Stop dashboards from being saved with the generic title `“{project.name} — AI Dashboard”`; instead preserve the AI-generated descriptive title and derive a meaningful fallback from the widget contents when the title is missing.

### Files changed
- `platform-api/app/routes/home_intelligence.py`
- `platform-api/app/routes/ai_proxy.py`
- `ai-server/tablescope-ai-api/app/routers/ai.py`

### Backend helper (added to both `home_intelligence.py` and `ai_proxy.py`)

```python
def _derive_dashboard_title(
    project_name: str, widgets: list[dict[str, Any]]
) -> str:
    """Build a descriptive, non-generic dashboard title from the widget content."""
    titles = [
        str(w.get("title") or "").strip()
        for w in widgets
        if w.get("title") and str(w.get("title")).strip() not in ("", "Widget")
    ]
    seen: list[str] = []
    for t in titles:
        if t not in seen:
            seen.append(t)
        if len(seen) == 2:
            break
    if seen:
        base = " & ".join(seen)
        if "dashboard" not in base.lower():
            base = f"{base} Dashboard"
        return base
    return f"{project_name} — AI Dashboard"
```

### `home_intelligence.py` — home dashboard suggestions

Before:

```python
"dashboard": (
    {
        "title": f"{project.name} — AI Dashboard",
        "widgets": widgets,
    }
    if widgets
    else None
),
```

After:

```python
"dashboard": (
    {
        "title": _derive_dashboard_title(project.name, widgets),
        "widgets": widgets,
    }
    if widgets
    else None
),
```

### `home_intelligence.py` — project dashboard

Before:

```python
dashboard = (
    {
        "title": f"{project.name} — AI Dashboard",
        "summary": narrative["summary"],
        ...
    }
    if widgets
    else None
)
```

After:

```python
dashboard = (
    {
        "title": _derive_dashboard_title(project.name, widgets),
        "summary": narrative["summary"],
        ...
    }
    if widgets
    else None
)
```

### `home_intelligence.py` — save dashboard

Before:

```python
name=req.title or "AI Dashboard",
```

After:

```python
name=req.title or _derive_dashboard_title(
    project.name, [w.model_dump() for w in req.widgets]
),
```

### `ai_proxy.py` — `ai_generate_and_save_dashboard` title priority

Before:

```python
if req.name:
    dashboard_title = req.name
elif req.prompt:
    dashboard_title = _shorten_ai_name(req.prompt)
else:
    dashboard_title = "AI Dashboard"
```

After:

```python
if req.name:
    dashboard_title = req.name
elif suggestion.get("title"):
    dashboard_title = str(suggestion["title"])
elif req.prompt:
    dashboard_title = _shorten_ai_name(req.prompt)
else:
    dashboard_title = _derive_dashboard_title(
        project.name, suggestion.get("widgets", [])
    )
```

### `ai_proxy.py` — `ai_suggest_dashboards` title fallback

The suggestion title now falls back to a description derived from `business_purpose` or the first widget title instead of the literal string `AI Dashboard`.

### `ai.py` — prompt requirement

The dashboard-suggestion prompts now explicitly instruct the model to produce a non-generic title:

```python
'  "title": "specific, descriptive dashboard name (never generic like AI Dashboard)",\n'
```

```python
'    "title": "specific, descriptive dashboard name (unique, never generic like AI Dashboard)",\n'
```

---

## ITEM 5 — Project Sidebar Restructuring

### Goal
Remove `project-documents` and `project-dashboards` from the project-level sidebar, and add a top-level `Project Insights` item that points to `/projects/{id}/insight`.

### Files changed
- `web-ui/components/tablescope/nav.ts`
- `web-ui/lib/ui/types.ts`
- `web-ui/components/tablescope/project-insight/project-insight-screen.tsx`
- `web-ui/components/tablescope/project-insight/project-insight-nav.test.tsx`

### `types.ts` — new NavKey

```ts
| "project-ask-tablescope"
| "project-ai-assistant"
| "project-insights"      // new
| "project-relationship-map"
```

### `nav.ts` — `projectNavGroups` Project group

Before:

```ts
{
  heading: "Project",
  items: [
    { key: "overview", label: "Overview", href: base, icon: IconLayoutGrid },
    { key: "project-data-sources", label: "Data Sources", ... },
    { key: "project-queries", label: "Tables", ... },
    { key: "project-scopes", label: "Scopes", ... },
    { key: "project-dashboards", label: "Dashboards", ... },
    { key: "project-documents", label: "Documents", ... },
    { key: "project-business-context", label: "Business Context", ... },
  ],
},
```

After:

```ts
{
  heading: "Project",
  items: [
    { key: "overview", label: "Overview", href: base, icon: IconLayoutGrid },
    {
      key: "project-insights",
      label: "Project Insights",
      href: `${base}/insight`,
      icon: IconSparkles,
    },
    { key: "project-data-sources", label: "Data Sources", ... },
    { key: "project-queries", label: "Tables", ... },
    { key: "project-scopes", label: "Scopes", ... },
    { key: "project-business-context", label: "Business Context", ... },
  ],
},
```

`project-dashboards` and `project-documents` remain valid `NavKey` values so existing screens that pass them as `activeNav` still type-check, but they are no longer rendered in the sidebar.

### `project-insight-screen.tsx` — `activeNav`

```tsx
<ProjectShell
  projectId={projectId}
  activeNav="project-insights"
  breadcrumbLabel="Project Insight"
```

---

## ITEM 6 — Home Page Ask Box

### Goal
Add a `“What would you like to analyze?”` ask box above the three pills on the Home page and wire it to the shared `/api/ai/route-prompt` conversation analytics endpoint.

### Files changed
- `web-ui/components/tablescope/home/ai-suggestions.tsx`
- `web-ui/app/page.tsx`
- `web-ui/app/business-insight/page.tsx`

### `ai-suggestions.tsx` — new `HomeAskBox` component

```tsx
interface RoutePromptResponse {
  route: string;
  prefilled: string;
}

function HomeAskBox({ projectId }: { projectId?: number }) {
  const router = useRouter();
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(prompt: string) {
    const q = prompt.trim();
    if (!q || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await apiClient.post<RoutePromptResponse>(
        "/api/ai/route-prompt",
        { prompt: q, project_id: projectId ?? null },
      );
      const sep = res.route.includes("?") ? "&" : "?";
      router.push(`${res.route}${sep}q=${encodeURIComponent(res.prefilled)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ask failed");
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-3 text-center">
      <div className="space-y-1">
        <h2 className="text-h2 text-ink-primary">
          What would you like to analyze?
        </h2>
        <p className="text-small text-ink-secondary">
          Ask anything across your connected data, documents, and dashboards
        </p>
      </div>
      <div className="mx-auto flex w-full max-w-2xl items-center gap-2 rounded-xl border border-line-secondary bg-bg-primary px-4 py-2.5 focus-within:border-brand-100 focus-within:ring-2 focus-within:ring-brand-100">
        <IconSparkles size={18} className="shrink-0 text-ai" />
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void submit(value);
            }
          }}
          placeholder="Ask anything across your connected data, documents, and dashboards"
          aria-label="Ask anything across your connected data, documents, and dashboards"
          className="min-w-0 flex-1 bg-transparent text-[14px] text-ink-primary placeholder:text-ink-tertiary focus:outline-none"
        />
        <button
          type="button"
          onClick={() => void submit(value)}
          disabled={submitting || !value.trim()}
          aria-label="Ask"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand text-brand-fg hover:bg-brand-700 disabled:opacity-50"
        >
          <IconArrowUp size={16} />
        </button>
      </div>
      {error && <p className="text-small text-danger">{error}</p>}
    </div>
  );
}
```

### `ai-suggestions.tsx` — `HomeAiSuggestions` now renders the ask box

```tsx
return (
  <div className="space-y-4">
    <HomeAskBox projectId={projectId} />
    <div className="flex flex-wrap justify-center gap-2">
      {PILLS.map((p) => ( ... ))}
    </div>
    ...
  </div>
);
```

### `page.tsx` — Home now renders `HomeAiSuggestions` above the pinned cards

```tsx
import { HomeAiSuggestions } from "@/components/tablescope/home/ai-suggestions";
import { HomePinsGrid } from "@/components/tablescope/home/home-pins-grid";

...

<HomeAiSuggestions />
<HomePinsGrid />
```

### `business-insight/page.tsx` — `HeroSearch` removed

The standalone `HeroSearch` was removed because `HomeAiSuggestions` now contains the ask box:

```tsx
import { HomeAiSuggestions } from "@/components/tablescope/home/ai-suggestions";

...

<div className="mx-auto w-full max-w-content space-y-6">
  <HomeAiSuggestions />
</div>
```

---

## ITEM 7 — Project Overview Ask Box + Three Pills

### Goal
Replace the old `Ask about your data…` card and `QUICK_PROMPTS` chips on the Project Overview page with the same `HomeAiSuggestions` surface used on the Business Insight page, scoped to the current project.

### Files changed
- `web-ui/components/tablescope/project/overview-screen.tsx`

### Before

```tsx
const QUICK_PROMPTS = [
  "Supplier delay trends",
  "Top suppliers by spend",
  "Quality trends",
  "Compare by region",
];

const [ask, setAsk] = useState("");

const goAsk = (prompt: string) => {
  const q = prompt.trim();
  router.push(
    `/projects/${projectId}/ai${q ? `?q=${encodeURIComponent(q)}` : ""}`,
  );
};

...

<Card className="space-y-3 p-4">
  <div className="flex items-center gap-2 rounded-lg border border-line-secondary bg-bg-primary px-3 py-2.5">
    <input
      value={ask}
      onChange={(e) => setAsk(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") goAsk(ask);
      }}
      placeholder="Ask about your data, documents, or dashboards…"
      ...
    />
    <button
      type="button"
      onClick={() => goAsk(ask)}
      aria-label="Ask AI"
      ...
    >
      <IconArrowUp size={15} />
    </button>
  </div>
  <div className="flex flex-wrap gap-2">
    {QUICK_PROMPTS.map((p) => (
      <button key={p} type="button" onClick={() => goAsk(p)} ...>
        {p}
      </button>
    ))}
  </div>
</Card>
```

### After

```tsx
import { HomeAiSuggestions } from "@/components/tablescope/home/ai-suggestions";

...

<HomeAiSuggestions projectId={Number(projectId)} />

<div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
  <StatTile ... />
```

The `goAsk` helper is retained for the `ContextPanel` `onAsk` handler.

---

## ITEM 8 — Project Insight AI-Derived Risks/Trends/Opportunities

### Goal
Stop using the hardcoded `data.risks / data.trends / data.opportunities` arrays on the Project Insight page; derive the three columns from the shared AI insight backend (`/home/insights` → `_run_for_project`) the same way the Home `IntelligenceFeed` filters by `insightType` and `severity`.

### Files changed
- `web-ui/components/tablescope/project-insight/project-insight-screen.tsx`
- `web-ui/lib/api/home-intelligence.ts`

### `home-intelligence.ts` — optional `question` on `InsightCard`

```ts
export interface InsightCard {
  ...
  title: string;
  /** Optional natural-language question that investigating this card should ask. */
  question?: string;
  summary: string;
  ...
}
```

### `project-insight-screen.tsx` — mapping `InsightCard` → `ProjectInsightCard`

```tsx
function toProjectInsightCard(card: InsightCardData): ProjectInsightCard {
  const supporting: string[] = [
    ...(card.sources?.tables ?? []),
    ...(card.sources?.documents ?? []),
  ];
  const severity =
    card.severity === "info" ? "informational" : card.severity;
  return {
    id: card.insightId ?? card.id,
    insightId: card.insightId ?? card.id,
    insightType: card.insightType,
    title: card.title,
    summary: card.summary,
    severity: severity as ProjectInsightCard["severity"],
    recommendedAction: card.callout?.text,
    question: card.question || card.title || card.summary,
    supportingSources: supporting,
    sourceTables: card.sources?.tables,
    explanation: card.explanation as unknown as Record<string, unknown>,
    sql: card.sql,
    chartType: card.chartType,
    labelColumn: card.labelColumn,
    valueColumn: card.valueColumn,
    valueColumn2: card.valueColumn2,
    executedAt: card.executedAt,
  };
}
```

### `project-insight-screen.tsx` — risk / trend / opportunity derivation

Before:

```tsx
const riskCards = (data?.risks ?? []).filter((c) => c.title?.trim());
const trendCards = (data?.trends ?? []).filter((c) => c.title?.trim());
const opportunityCards = (data?.opportunities ?? []).filter((c) =>
  c.title?.trim(),
);
```

After:

```tsx
const allAiCards = useMemo(
  () =>
    insightsQuery.data?.projects?.flatMap((p) =>
      p.insights.map(toProjectInsightCard),
    ) ?? [],
  [insightsQuery.data],
);
const riskCards = useMemo(
  () =>
    allAiCards.filter(
      (c) =>
        c.insightType.startsWith("risk_") ||
        c.severity === "critical" ||
        c.severity === "urgent" ||
        c.severity === "warning",
    ),
  [allAiCards],
);
const trendCards = useMemo(
  () =>
    allAiCards.filter(
      (c) => c.insightType.startsWith("trend_") && !riskCards.includes(c),
    ),
  [allAiCards, riskCards],
);
const opportunityCards = useMemo(
  () =>
    allAiCards.filter(
      (c) =>
        (c.insightType.startsWith("opportunity_") ||
          c.severity === "opportunity") &&
        !riskCards.includes(c) &&
        !trendCards.includes(c),
    ),
  [allAiCards, riskCards, trendCards],
);
const allTrendCards = trendCards;
const allInsightCards = allAiCards;
```

The insight feedback IDs are also now sourced from the same AI-derived card list.

---

## ITEM 9 — Advanced Methods Gated Behind Explain Toggle

### Goal
Move the `MethodEnvelopeBlock` (effect size, p-value, confidence interval, etc.) from the always-visible chart area into the `InsightExplanationPanel`, so it is only revealed when the user clicks **Explain**.

### Files changed
- `web-ui/components/tablescope/home/intelligence-card.tsx`
- `web-ui/components/tablescope/home/insight-explanation-panel.tsx`

### `intelligence-card.tsx` — removed unconditional `MethodEnvelopeBlock`

Before:

```tsx
{card.chart && (
  <div className="mt-3">
    ...
    {card.analyticalMethod && (
      <MethodEnvelopeBlock envelope={card.analyticalMethod} />
    )}
  </div>
)}
```

After:

```tsx
{card.chart && (
  <div className="mt-3">
    ...
  </div>
)}
```

The `MethodEnvelopeBlock` import is also removed from `intelligence-card.tsx`.

### `insight-explanation-panel.tsx` — Advanced Methods section inside the Explain panel

```tsx
import { MethodEnvelopeBlock } from "@/components/ai/method-envelope";

...

{explanation ? (
  <ExplanationContent card={card} explanation={explanation} />
) : (
  <LegacyFallback card={card} />
)}

{card.analyticalMethod && (
  <Section title="Advanced Methods">
    <MethodEnvelopeBlock envelope={card.analyticalMethod} />
  </Section>
)}
```

The gray background and formatted `MethodEnvelopeBlock` container are unchanged; only its visibility changes from always-on to Explain-only.

---

## Verification

- `web-ui`
  - `npm run typecheck` — clean
  - `npm run lint` — clean (only pre-existing warnings in unrelated files)
  - `npm run build` — clean
  - `npm test` — 179 passed
- `platform-api`
  - `ruff check app/routes/home_intelligence.py app/routes/ai_proxy.py tests/test_home_intelligence.py` — clean
  - `pytest` — 671 passed
- `ai-server`
  - `ruff check app/routers/ai.py` — clean
