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

const AUDIENCES = ["", "executive", "manager", "analyst", "operational"];
const AUDIENCE_LABEL: Record<string, string> = {
  "": "Any audience",
  executive: "Executive",
  manager: "Manager",
  analyst: "Analyst",
  operational: "Operational",
};

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
                      <div className="mt-1 line-clamp-2 text-[12px] text-ink-primary">
                        {w.title || w.businessQuestion || "Untitled widget"}
                      </div>
                    </div>
                  ))}
                </div>
              )}

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
