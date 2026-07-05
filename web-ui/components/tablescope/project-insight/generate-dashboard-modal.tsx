"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  IconSparkles,
  IconX,
  IconLoader2,
  IconDeviceFloppy,
  IconCheck,
  IconAlertTriangle,
  IconBulb,
  IconChecklist,
  IconChartBar,
  IconTable,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { InsightChartBlock } from "@/components/tablescope/home/intelligence-card";
import {
  generateProjectDashboard,
  saveDashboardSuggestion,
  type DashboardSuggestion,
  type DashboardWidgetSuggestion,
} from "@/lib/api/home-intelligence";

/**
 * Generate a real, chart-rendered dashboard for the current project — the same
 * flow as "New Dashboard Suggestions" on the Business Insight page (plan →
 * execute real SQL → render charts), scoped to this project. There is no
 * preview-only stage: widgets that cannot execute are simply omitted, and the
 * user saves the generated dashboard with one click.
 */
export function GenerateDashboardModal({
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
  const [dashboard, setDashboard] = useState<DashboardSuggestion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const generateMutation = useMutation({
    mutationFn: () => generateProjectDashboard(Number(projectId)),
    onSuccess: (res) => {
      setDashboard(res.dashboard);
      setError(
        res.dashboard
          ? null
          : "No dashboard could be generated from this project's data yet. Add data sources with measurable values and try again.",
      );
    },
    onError: (err: Error) => setError(err.message),
  });

  // Generate once when the modal opens; reset when it closes.
  const seededRef = useRef(false);
  useEffect(() => {
    if (!open) {
      seededRef.current = false;
      setDashboard(null);
      setError(null);
      setSaved(false);
      return;
    }
    if (seededRef.current) return;
    seededRef.current = true;
    generateMutation.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const saveMutation = useMutation({
    mutationFn: (d: DashboardSuggestion) =>
      saveDashboardSuggestion({
        project_id: Number(projectId),
        title: d.title,
        summary: d.summary,
        keyFindings: d.keyFindings,
        recommendedActions: d.recommendedActions,
        widgets: d.widgets.map((w) => ({
          title: w.title,
          sql: w.sql,
          chartType: w.chartType,
          explanation: w.explanation,
          labelColumn: w.labelColumn,
          valueColumn: w.valueColumn,
        })),
      }),
    onSuccess: (res) => {
      setSaved(true);
      notify(`Saved dashboard "${res.name}"`, "success");
      onSaved(res.dashboard_id);
    },
    onError: (err: Error) => notify(err.message, "error"),
  });

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4">
      <div className="my-8 w-full max-w-3xl rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="flex items-center gap-2 text-h2 text-ink-primary">
              <IconSparkles size={18} className="text-ai" />
              Generate dashboard
            </h2>
            <p className="mt-1 text-small text-ink-tertiary">
              A dashboard grounded in this project&apos;s data, rendered with live
              charts — the same as New Dashboard Suggestions.
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

        {generateMutation.isPending && (
          <div className="flex items-center justify-center gap-2 py-12 text-small text-ink-tertiary">
            <IconLoader2 size={16} className="animate-spin" />
            Analyzing project data and building the dashboard…
          </div>
        )}

        {error && !generateMutation.isPending && (
          <p className="mt-4 text-small text-danger">{error}</p>
        )}

        {dashboard && dashboard.widgets.length > 0 && (
          <div className="mt-4">
            <div className="mb-3 flex items-start justify-between gap-3">
              <div className="min-w-0 text-h3 text-ink-primary">
                {dashboard.title}
              </div>
              <Button
                variant="primary"
                onClick={() => saveMutation.mutate(dashboard)}
                disabled={saveMutation.isPending || saved}
              >
                {saved ? (
                  <>
                    <IconCheck size={14} /> Saved
                  </>
                ) : saveMutation.isPending ? (
                  <>
                    <IconLoader2 size={14} className="animate-spin" /> Saving…
                  </>
                ) : (
                  <>
                    <IconDeviceFloppy size={14} /> Save dashboard
                  </>
                )}
              </Button>
            </div>
            <DashboardNarrative dashboard={dashboard} />
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {dashboard.widgets.map((w, i) => (
                <WidgetCard key={`${w.title}-${i}`} widget={w} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function DashboardNarrative({
  dashboard,
}: {
  dashboard: DashboardSuggestion;
}) {
  const findings = dashboard.keyFindings ?? [];
  const actions = dashboard.recommendedActions ?? [];
  if (!dashboard.summary && findings.length === 0 && actions.length === 0) {
    return null;
  }
  return (
    <div className="mb-4 rounded-md border border-line-tertiary bg-bg-secondary/40 p-3">
      {dashboard.summary && (
        <p className="text-small text-ink-secondary">{dashboard.summary}</p>
      )}
      {(findings.length > 0 || actions.length > 0) && (
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {findings.length > 0 && (
            <div>
              <div className="mb-1 flex items-center gap-1.5 text-small font-medium text-ink-primary">
                <IconBulb size={14} className="text-ai" />
                Key findings
              </div>
              <ul className="list-disc space-y-0.5 pl-4 text-small text-ink-secondary">
                {findings.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            </div>
          )}
          {actions.length > 0 && (
            <div>
              <div className="mb-1 flex items-center gap-1.5 text-small font-medium text-ink-primary">
                <IconChecklist size={14} className="text-brand-500" />
                Recommended actions
              </div>
              <ul className="list-disc space-y-0.5 pl-4 text-small text-ink-secondary">
                {actions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function WidgetCard({ widget }: { widget: DashboardWidgetSuggestion }) {
  const [showData, setShowData] = useState(false);
  const series = widget.chart?.data?.series ?? [];
  const kpis = widget.chart?.data?.kpis ?? [];
  const canShowData = series.length > 0 || kpis.length > 0;

  return (
    <div className="rounded-md border border-line-tertiary bg-bg-secondary/40 p-3">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0 text-small font-medium text-ink-primary">
          {widget.title}
        </div>
        {canShowData && (
          <button
            type="button"
            onClick={() => setShowData((v) => !v)}
            className="flex shrink-0 items-center gap-1 text-[12px] text-ink-tertiary hover:text-ink-secondary"
          >
            {showData ? (
              <>
                <IconChartBar size={13} /> Chart
              </>
            ) : (
              <>
                <IconTable size={13} /> Show data
              </>
            )}
          </button>
        )}
      </div>
      {showData && canShowData ? (
        <WidgetDataTable widget={widget} />
      ) : (
        <InsightChartBlock chart={widget.chart} />
      )}
      {widget.explanation && (
        <p className="mt-2 text-[12px] leading-relaxed text-ink-secondary">
          {widget.explanation}
        </p>
      )}
    </div>
  );
}

/** Format a numeric metric value per its detected format (mirrors the backend). */
function formatValue(v: number, fmt?: string): string {
  if (fmt === "percent") {
    const pct = Math.abs(v) <= 1 ? v * 100 : v;
    return `${pct.toFixed(1)}%`;
  }
  if (fmt === "currency") return `$${v.toLocaleString()}`;
  if (fmt === "count") return Math.round(v).toLocaleString();
  return v.toLocaleString();
}

function WidgetDataTable({ widget }: { widget: DashboardWidgetSuggestion }) {
  const series = widget.chart?.data?.series ?? [];
  const kpis = widget.chart?.data?.kpis ?? [];
  const metric = widget.valueColumn || "Value";
  const dimension = widget.labelColumn || "Category";

  if (series.length === 0 && kpis.length > 0) {
    return (
      <div className="max-h-[180px] overflow-auto">
        <table className="w-full text-[12px]">
          <tbody>
            {kpis.map((k, i) => (
              <tr key={i} className="border-b border-line-tertiary/60">
                <td className="py-1 pr-2 text-ink-secondary">{k.label}</td>
                <td className="py-1 text-right font-medium text-ink-primary">
                  {k.value}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="max-h-[180px] overflow-auto">
      <table className="w-full text-[12px]">
        <thead className="sticky top-0 bg-bg-secondary">
          <tr className="text-left text-ink-tertiary">
            <th className="py-1 pr-2 font-medium">{dimension}</th>
            <th className="py-1 text-right font-medium">{metric}</th>
          </tr>
        </thead>
        <tbody>
          {series.map((s, i) => (
            <tr key={i} className="border-b border-line-tertiary/60">
              <td className="py-1 pr-2 text-ink-secondary" title={s.label}>
                {s.label}
              </td>
              <td className="py-1 text-right font-medium text-ink-primary">
                {formatValue(s.value, widget.format)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
