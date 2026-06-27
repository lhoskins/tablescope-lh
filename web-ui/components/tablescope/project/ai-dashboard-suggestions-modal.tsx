"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  IconSparkles,
  IconX,
  IconChartBar,
  IconDatabase,
} from "@tabler/icons-react";
import { apiClient } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export interface SuggestionWidget {
  title: string;
  chartType: string;
  businessQuestion: string;
}

export interface KnowledgeGraphContextChips {
  risks?: string[];
  opportunities?: string[];
  gaps?: string[];
  measuredKpis?: string[];
  recommendedKpis?: string[];
  governingDocuments?: string[];
}

export interface DashboardSuggestion {
  id: string;
  title: string;
  description: string;
  businessPurpose: string;
  audience: string;
  widgets: SuggestionWidget[];
  kpis: string[];
  dataSources: string[];
  confidence: number;
  qualityScore: number;
  validationSummary: string;
  knowledgeGraphContext?: KnowledgeGraphContextChips;
  savePayload?: Record<string, unknown>;
}

const CHART_GLYPH: Record<string, string> = {
  bar: "▬",
  column: "▬",
  horizontal_bar: "▬",
  line: "↗",
  area: "↗",
  pie: "◐",
  donut: "◐",
  kpi: "#",
  table: "☷",
  scatter: "⋰",
  narrative: "¶",
};

// Chart-family classification so each widget renders a representative visual
// preview (not just text). Previews are not executed, so these are schematic
// mockups of the chosen chart type.
function chartFamily(chartType: string): string {
  const t = (chartType || "").toLowerCase();
  if (/kpi|gauge|bullet|metric|number|stat/.test(t)) return "kpi";
  if (/line|area|spark|trend/.test(t)) return "line";
  if (/pie|donut/.test(t)) return "pie";
  if (/table|pivot|grid/.test(t)) return "table";
  if (/narrative|insight|text|prose/.test(t)) return "narrative";
  if (/scatter|bubble/.test(t)) return "scatter";
  return "bar";
}

function WidgetPreviewGlyph({ chartType }: { chartType: string }) {
  const fam = chartFamily(chartType);
  const cls = "h-10 w-full text-brand-500";
  if (fam === "kpi") {
    return (
      <div className="flex h-10 items-center justify-center">
        <span className="text-[18px] font-semibold text-ink-primary">123.4</span>
      </div>
    );
  }
  if (fam === "line") {
    return (
      <svg viewBox="0 0 100 40" className={cls} preserveAspectRatio="none" aria-hidden>
        <polyline points="0,32 20,24 40,28 60,12 80,18 100,4" fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
    );
  }
  if (fam === "pie") {
    return (
      <svg viewBox="0 0 40 40" className="mx-auto h-10" aria-hidden>
        <circle cx="20" cy="20" r="16" fill="none" stroke="currentColor" className="text-line-secondary" strokeWidth="8" />
        <circle cx="20" cy="20" r="16" fill="none" stroke="currentColor" className="text-brand-500" strokeWidth="8" strokeDasharray="60 100" transform="rotate(-90 20 20)" />
      </svg>
    );
  }
  if (fam === "table") {
    return (
      <div className="grid h-10 grid-rows-3 gap-0.5" aria-hidden>
        {[0, 1, 2].map((r) => (
          <div key={r} className="grid grid-cols-3 gap-0.5">
            {[0, 1, 2].map((c) => (
              <div key={c} className="rounded-[1px] bg-line-secondary" />
            ))}
          </div>
        ))}
      </div>
    );
  }
  if (fam === "narrative") {
    return (
      <div className="flex h-10 flex-col justify-center gap-1" aria-hidden>
        <div className="h-1.5 w-full rounded bg-line-secondary" />
        <div className="h-1.5 w-4/5 rounded bg-line-secondary" />
        <div className="h-1.5 w-3/5 rounded bg-line-secondary" />
      </div>
    );
  }
  if (fam === "scatter") {
    return (
      <svg viewBox="0 0 100 40" className={cls} aria-hidden>
        {[[12, 30], [28, 18], [44, 24], [60, 10], [76, 20], [90, 6]].map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r="3" fill="currentColor" />
        ))}
      </svg>
    );
  }
  // bar (default)
  return (
    <svg viewBox="0 0 100 40" className={cls} preserveAspectRatio="none" aria-hidden>
      {[8, 26, 44, 62, 80].map((x, i) => {
        const h = [16, 28, 12, 34, 22][i];
        return <rect key={x} x={x} y={40 - h} width="10" height={h} fill="currentColor" />;
      })}
    </svg>
  );
}

const AUDIENCES = ["", "executive", "manager", "analyst", "operational"];
const AUDIENCE_LABEL: Record<string, string> = {
  "": "Any audience",
  executive: "Executive",
  manager: "Manager",
  analyst: "Analyst",
  operational: "Operational",
};

const KG_CHIP_GROUPS: {
  key: keyof KnowledgeGraphContextChips;
  label: string;
  tone: "danger" | "success" | "warning" | "ai" | "outline" | "neutral";
}[] = [
  { key: "risks", label: "Risk", tone: "danger" },
  { key: "gaps", label: "Gap", tone: "warning" },
  { key: "opportunities", label: "Opportunity", tone: "success" },
  { key: "measuredKpis", label: "KPI", tone: "ai" },
  { key: "recommendedKpis", label: "Rec. KPI", tone: "outline" },
  { key: "governingDocuments", label: "Doc", tone: "neutral" },
];

function KnowledgeGraphChips({
  kg,
}: {
  kg?: KnowledgeGraphContextChips;
}) {
  if (!kg) return null;
  const groups = KG_CHIP_GROUPS.map((g) => ({
    ...g,
    items: (kg[g.key] ?? []).filter(Boolean),
  })).filter((g) => g.items.length > 0);
  if (groups.length === 0) return null;

  return (
    <div className="mt-3 rounded-md border border-dashed border-line-secondary bg-bg-secondary/30 p-2">
      <div className="mb-1.5 text-[11px] uppercase text-ink-tertiary">
        Knowledge Graph context
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {groups.flatMap((g) =>
          g.items.slice(0, 3).map((item) => (
            <Badge key={`${g.key}-${item}`} tone={g.tone}>
              <span className="opacity-70">{g.label}:</span>&nbsp;{item}
            </Badge>
          )),
        )}
      </div>
    </div>
  );
}

export function AIDashboardSuggestionsModal({
  open,
  projectId,
  onClose,
  onSaved,
  notify,
}: {
  open: boolean;
  projectId: string;
  onClose: () => void;
  onSaved: (dashboardId: number) => void;
  notify: (message: string, tone?: "success" | "error" | "info") => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [audience, setAudience] = useState("");
  const [suggestions, setSuggestions] = useState<DashboardSuggestion[]>([]);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const generateMutation = useMutation({
    mutationFn: () =>
      apiClient.post<{ suggestions: DashboardSuggestion[] }>(
        "/api/ai/actions/suggest-dashboards",
        {
          project_id: Number(projectId),
          prompt: prompt.trim() || undefined,
          audience: audience || undefined,
          desired_count: 3,
        },
      ),
    onSuccess: (res) => {
      setSuggestions(res.suggestions ?? []);
      setError(null);
      if (!res.suggestions?.length) {
        setError(
          "No dashboard suggestions could be generated. Add data sources or try a more specific request.",
        );
      }
    },
    onError: (err: Error) => setError(err.message),
  });

  const saveMutation = useMutation({
    mutationFn: (s: DashboardSuggestion) =>
      apiClient.post<{ dashboard_id: number; dashboard_name: string; dashboard_url?: string }>(
        "/api/ai/actions/save-dashboard-suggestion",
        {
          project_id: Number(projectId),
          suggestionId: s.id,
          suggestion: s.savePayload ?? {
            title: s.title,
            description: s.description,
            businessPurpose: s.businessPurpose,
            audience: s.audience,
            widgets: s.widgets,
            kpis: s.kpis,
            dataSources: s.dataSources,
          },
        },
      ),
    onSuccess: (res) => {
      notify(`Saved dashboard "${res.dashboard_name}"`, "success");
      onSaved(res.dashboard_id);
    },
    onError: (err: Error) => notify(err.message, "error"),
    onSettled: () => setSavingId(null),
  });

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4">
      <div className="my-8 w-full max-w-3xl rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="flex items-center gap-2 text-h2 text-ink-primary">
              <IconSparkles size={18} className="text-ai" />
              Generate dashboards with AI
            </h2>
            <p className="mt-1 text-small text-ink-tertiary">
              Describe what you want to monitor (optional) and pick an audience.
              We&apos;ll suggest at least 3 dashboards grounded in this
              project&apos;s data.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="shrink-0 text-ink-tertiary hover:text-ink-primary"
          >
            <IconX size={18} />
          </button>
        </div>

        <form
          className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            generateMutation.mutate();
          }}
        >
          <div className="flex-1">
            <label className="mb-1 block text-small font-medium text-ink-secondary">
              What should these dashboards show?
            </label>
            <input
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. supplier quality and on-time delivery"
              className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-small font-medium text-ink-secondary">
              Audience
            </label>
            <select
              value={audience}
              onChange={(e) => setAudience(e.target.value)}
              className="h-9 rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
            >
              {AUDIENCES.map((a) => (
                <option key={a} value={a}>
                  {AUDIENCE_LABEL[a]}
                </option>
              ))}
            </select>
          </div>
          <Button
            variant="primary"
            type="submit"
            disabled={generateMutation.isPending}
          >
            <IconSparkles size={14} />
            {generateMutation.isPending ? "Generating…" : "Generate"}
          </Button>
        </form>

        {error && <p className="mt-3 text-small text-red-600">{error}</p>}

        <div className="mt-5 space-y-3">
          {generateMutation.isPending && (
            <div className="py-10 text-center text-small text-ink-tertiary">
              Analyzing project data and drafting dashboard ideas…
            </div>
          )}

          {suggestions.map((s) => (
            <div
              key={s.id}
              className="rounded-lg border border-line-secondary bg-bg-primary p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-h3 text-ink-primary">{s.title}</div>
                  {s.description && (
                    <div className="mt-0.5 text-small text-ink-secondary">
                      {s.description}
                    </div>
                  )}
                </div>
                <Button
                  variant="primary"
                  onClick={() => {
                    setSavingId(s.id);
                    saveMutation.mutate(s);
                  }}
                  disabled={savingId !== null}
                >
                  {savingId === s.id ? "Saving…" : "Save"}
                </Button>
              </div>

              {s.businessPurpose && (
                <p className="mt-2 text-small text-ink-tertiary">
                  {s.businessPurpose}
                </p>
              )}

              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                {s.audience && (
                  <Badge tone="brand">{AUDIENCE_LABEL[s.audience] ?? s.audience}</Badge>
                )}
                <Badge tone="neutral">
                  <IconChartBar size={12} />
                  {s.widgets.length} widget{s.widgets.length === 1 ? "" : "s"}
                </Badge>
                {s.qualityScore > 0 && (
                  <Badge tone="success">Quality {s.qualityScore}</Badge>
                )}
                {s.confidence > 0 && (
                  <Badge tone="outline">
                    {Math.round(s.confidence * 100)}% confidence
                  </Badge>
                )}
              </div>

              {s.widgets.length > 0 && (
                <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {s.widgets.slice(0, 6).map((w, i) => (
                    <div
                      key={`${s.id}-w-${i}`}
                      className="rounded-md border border-line-secondary bg-bg-secondary/40 p-2"
                      title={w.businessQuestion || w.title}
                    >
                      <div className="flex items-center gap-1.5 text-[11px] uppercase text-ink-tertiary">
                        <span aria-hidden className="text-ink-secondary">
                          {CHART_GLYPH[(w.chartType || "").toLowerCase()] ?? "▭"}
                        </span>
                        {w.chartType || "widget"}
                      </div>
                      <div className="mt-1.5">
                        <WidgetPreviewGlyph chartType={w.chartType} />
                      </div>
                      <div className="mt-1 line-clamp-2 text-[12px] text-ink-primary">
                        {w.title || w.businessQuestion || "Untitled widget"}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <KnowledgeGraphChips kg={s.knowledgeGraphContext} />

              {s.kpis.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <span className="text-[11px] uppercase text-ink-tertiary">
                    KPIs
                  </span>
                  {s.kpis.slice(0, 8).map((k) => (
                    <Badge key={k} tone="ai">
                      {k}
                    </Badge>
                  ))}
                </div>
              )}

              {s.dataSources.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <span className="text-[11px] uppercase text-ink-tertiary">
                    Sources
                  </span>
                  {s.dataSources.slice(0, 8).map((d) => (
                    <Badge key={d} tone="neutral">
                      <IconDatabase size={12} />
                      {d}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
