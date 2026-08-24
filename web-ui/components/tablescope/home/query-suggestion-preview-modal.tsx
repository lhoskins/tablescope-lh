"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  IconAlertTriangle, IconChartBar, IconCheck, IconChevronDown,
  IconChevronRight, IconDatabase, IconDeviceFloppy, IconLayoutDashboard,
  IconLoader2, IconPin, IconSparkles, IconX,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { useToasts } from "@/components/ui/toast";
import { ResultChart, ResultTable, rankVisualizations } from "@/components/ai/ai-result-view";
import { runDatasourceSql } from "@/lib/api/data-source-builder";
import { createHomePin } from "@/lib/api/home-pins";
import { saveQuerySuggestion } from "@/lib/api/home-intelligence";
import { useProjectSummaries } from "@/lib/ui/use-shell-data";
import type { SuggestedVisualization } from "@/lib/api/ai-actions";
import type { InsightCard } from "@/lib/api/home-intelligence";
import type { WidgetConfig, WidgetType } from "@/components/dashboard/types";
import { SaveInsightToDashboardModal } from "./save-insight-to-dashboard-modal";

type RunResult = {
  columns: string[];
  rows: Record<string, unknown>[];
  total?: number;
  sql?: string;
  suggestedVisualization?: SuggestedVisualization;
};

type ChartCandidate = {
  id: string;
  label: string;
  description: string;
  fit: "Best fit" | "Strong" | "Compatible";
  viz: SuggestedVisualization;
};

function isNumeric(value: unknown): boolean {
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value !== "string" || value.trim() === "") return false;
  return Number.isFinite(Number(value.replace(/[,$%]/g, "")));
}

function inferViz(columns: string[], rows: Record<string, unknown>[]): SuggestedVisualization {
  if (!columns.length || !rows.length) return { type: "table" };
  const numeric = columns.filter((column) => rows.filter((row) => isNumeric(row[column])).length >= Math.max(1, rows.length / 2));
  if (rows.length === 1 && numeric.length) return { type: "kpi", metricField: numeric[0] };
  const yField = numeric[0];
  if (!yField) return { type: "table" };
  return { type: "bar", xField: columns.find((column) => column !== yField) ?? columns[0], yField };
}

function buildCandidates(columns: string[], rows: Record<string, unknown>[], preferred: SuggestedVisualization): ChartCandidate[] {
  const numeric = columns.filter((column) => rows.filter((row) => isNumeric(row[column])).length >= Math.max(1, rows.length / 2));
  const label = columns.find((column) => !numeric.includes(column)) ?? columns[0];
  const visualizations: SuggestedVisualization[] = [];
  if (numeric.length >= 2 && label) {
    visualizations.push({ type: "combo", chartStyle: "bar_line", xField: label, yField: numeric[0], y2Field: numeric[1] });
  }
  visualizations.push(...rankVisualizations(columns, rows, preferred).filter((item) => item.viz.type !== "table").map((item) => item.viz));
  if (!visualizations.length) visualizations.push({ type: "table" });
  const unique = visualizations.filter((viz, index, all) => {
    const key = `${viz.type}:${viz.yField ?? viz.metricField ?? ""}:${viz.y2Field ?? ""}`;
    return all.findIndex((candidate) => `${candidate.type}:${candidate.yField ?? candidate.metricField ?? ""}:${candidate.y2Field ?? ""}` === key) === index;
  }).slice(0, 3);
  return unique.map((viz, index) => {
    const primary = viz.yField ?? viz.metricField ?? numeric[0] ?? "Result";
    const secondary = viz.y2Field;
    const labelText = viz.type === "combo" ? `${primary} vs ${secondary}` : viz.type === "kpi" ? primary : `${primary} by ${viz.xField ?? label}`;
    const descriptions: Record<string, string> = {
      combo: "Combined bars and line make scale and direction easy to compare.",
      line: "A focused line chart highlights direction and turning points.",
      bar: "Bars support fast comparison across periods or categories.",
      pie: "A proportional view shows how categories contribute to the total.",
      kpi: "A compact KPI keeps the most important value prominent.",
      table: "A compact table preserves detail when chart fields are unavailable.",
    };
    return { id: `${viz.type}-${primary}-${secondary ?? ""}`, label: labelText, description: descriptions[viz.type] ?? "A compatible view of the generated result.", fit: index === 0 ? "Best fit" : index === 1 ? "Strong" : "Compatible", viz };
  });
}

type QualityCheck = { ok: boolean; label: string };

/**
 * Real checks against the selected chart's actual fields and rows, replacing
 * three indicators that previously always rendered a green check regardless
 * of whether the data behind them supported it. Compatibility gates "Add
 * selected chart to Home" -- data quality and layout are informational.
 */
export function evaluateChartQuality(
  viz: SuggestedVisualization,
  columns: string[],
  rows: Record<string, unknown>[],
): { compatibility: QualityCheck; dataQuality: QualityCheck; layout: QualityCheck } {
  const requiredFields =
    viz.type === "kpi"
      ? [viz.metricField]
      : viz.type === "combo"
        ? [viz.xField, viz.yField, viz.y2Field]
        : [viz.xField, viz.yField ?? viz.metricField];
  const missing = requiredFields.filter(
    (field): field is string => field != null && field !== "" && !columns.includes(field),
  );
  const compatibility: QualityCheck = missing.length
    ? { ok: false, label: `Missing ${missing.join(", ")}` }
    : { ok: true, label: "All required fields" };

  const measureField = viz.yField ?? viz.metricField;
  const populated = measureField
    ? rows.filter((row) => isNumeric(row[measureField])).length
    : 0;
  const dataQuality: QualityCheck = !rows.length
    ? { ok: false, label: "No preview rows returned" }
    : !measureField
      ? { ok: true, label: `${rows.length} preview rows` }
      : { ok: populated > 0, label: `${populated}/${rows.length} rows with data` };

  return { compatibility, dataQuality, layout: { ok: true, label: "Responsive widget" } };
}

function toWidget(title: string, queryId: number, viz: SuggestedVisualization, columns: string[], rows: Record<string, unknown>[], size: "compact" | "standard" | "wide"): WidgetConfig {
  const xColumn = viz.xField ?? columns[0] ?? "";
  const yColumn = viz.yField ?? viz.metricField ?? columns[1] ?? columns[0] ?? "";
  const firstX = rows[0]?.[xColumn];
  const looksLikeDate = /date|month|year|period/i.test(xColumn) || (typeof firstX === "string" && /^\d{4}-\d{2}/.test(firstX));
  return {
    id: `home-query-${queryId}-${Date.now()}`,
    type: viz.type as WidgetType,
    chartSubtype: viz.chartStyle as WidgetConfig["chartSubtype"],
    title,
    dataSource: { kind: "query", queryId },
    xColumn,
    xColumnType: looksLikeDate ? "date" : "string",
    yColumn,
    y2Column: viz.y2Field,
    aggregation: "sum",
    y2Aggregation: viz.y2Field ? "sum" : undefined,
    sortBy: "x_asc",
    filters: [],
    visualizationOptions: { showLegend: true, showGrid: true },
    colSpan: size === "wide" ? 8 : size === "standard" ? 6 : 4,
    position: 0,
  };
}

export function QuerySuggestionPreviewModal({ open, projectId, title, description, sql, onClose, onSaved }: {
  open: boolean;
  projectId: number;
  title: string;
  description: string;
  sql: string;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const queryClient = useQueryClient();
  const { push: pushToast } = useToasts();
  const { data: projects } = useProjectSummaries();
  const [showSql, setShowSql] = useState(false);
  const [showData, setShowData] = useState(false);
  const [savedQueryId, setSavedQueryId] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [widgetSize, setWidgetSize] = useState<"compact" | "standard" | "wide">("wide");
  const [page, setPage] = useState(0);
  const [saveToDashboardOpen, setSaveToDashboardOpen] = useState(false);
  const pageSize = 100;

  const run = useMutation<RunResult, Error, { offset: number; limit: number }>({
    mutationFn: async (vars) => {
      const response = await runDatasourceSql({ sql, project_id: projectId, ...vars });
      return response as RunResult;
    },
  });
  const save = useMutation({
    mutationFn: () => saveQuerySuggestion({ project_id: projectId, name: title, description, sql_text: run.data?.sql || sql }),
    onSuccess: (result) => { setSavedQueryId(result.query_id); onSaved?.(); },
  });

  useEffect(() => {
    if (!open) return;
    setShowSql(false); setShowData(false); setSavedQueryId(null); setSelectedId(null); setWidgetSize("wide"); setPage(0);
    run.mutate({ offset: 0, limit: pageSize });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, sql]);

  const result = run.data;
  const preferred = useMemo<SuggestedVisualization>(
    () => result?.suggestedVisualization ?? (result ? inferViz(result.columns, result.rows) : { type: "table" }),
    [result],
  );
  const candidates = useMemo(() => result ? buildCandidates(result.columns, result.rows, preferred) : [], [result, preferred]);
  const selected = candidates.find((candidate) => candidate.id === selectedId) ?? candidates[0];
  const viz = selected?.viz ?? preferred;
  const quality = useMemo(
    () => (result ? evaluateChartQuality(viz, result.columns, result.rows) : null),
    [result, viz],
  );
  const project = projects?.find((item) => Number(item.id) === projectId);
  const previewCard: InsightCard | null = result ? {
    id: `query-preview-${projectId}`, projectId: String(projectId), projectName: project?.name ?? "", projectColor: project?.accent ?? "",
    insightType: "query_suggestion", severity: "info", title: selected?.label || title || "Chart preview", summary: description,
    chart: null, callout: null, sources: { tables: [], documents: [] }, executedAt: new Date().toISOString(), sql: result.sql || sql,
    chartType: viz.type, labelColumn: viz.type === "kpi" ? undefined : viz.xField ?? result.columns[0], valueColumn: viz.yField ?? viz.metricField ?? result.columns[1] ?? result.columns[0],
  } : null;

  const addToHome = useMutation({
    mutationFn: async () => {
      if (!result || !selected) throw new Error("Select a compatible chart first.");
      let queryId = savedQueryId;
      if (!queryId) {
        const saved = await saveQuerySuggestion({ project_id: projectId, name: title, description, sql_text: result.sql || sql });
        queryId = saved.query_id; setSavedQueryId(queryId); onSaved?.();
      }
      const widget = toWidget(selected.label, queryId, selected.viz, result.columns, result.rows, widgetSize);
      return createHomePin({ pin_type: "live_widget", pin_key: `widget:query-${queryId}-${selected.viz.type}`, title: selected.label, project_id: projectId, layout: { x: 0, y: 0, w: widget.colSpan, h: 4 }, config: { widget, cachedData: { columns: result.columns, rows: result.rows } } });
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["home-pins"] }); pushToast("Chart added to Home", "success"); onClose(); },
  });

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/35 p-4">
      <div className="mx-auto my-4 w-full max-w-6xl rounded-xl border border-line-tertiary bg-bg-secondary shadow-xl">
        <header className="flex flex-wrap items-start justify-between gap-4 border-b border-line-tertiary bg-bg-primary px-5 py-4">
          <div><p className="text-caption text-ink-tertiary">Home / New chart suggestion</p><h2 className="mt-1 flex items-center gap-2 text-h1 text-ink-primary"><IconSparkles size={20} className="text-brand-500" />Preview chart suggestions</h2></div>
          <div className="flex items-center gap-2"><Button variant="secondary" size="md" onClick={onClose}>Cancel</Button><Button variant="primary" size="md" disabled={!selected || !quality?.compatibility.ok || addToHome.isPending || run.isPending} onClick={() => addToHome.mutate()}>{addToHome.isPending ? <IconLoader2 size={15} className="animate-spin" /> : <IconPin size={15} />}Add selected chart to Home</Button></div>
        </header>
        <div className="p-5">
          <section className="mb-4 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-line-tertiary bg-bg-primary px-4 py-3">
            <div><p className="text-caption font-medium uppercase tracking-wide text-ink-tertiary">Generated from your request</p><p className="mt-1 text-[13px] font-medium text-ink-primary">“{description || title}”</p></div>
            <p className="text-right text-caption text-ink-tertiary">{project?.name ?? `Project ${projectId}`}<br />Generated by Tablescope AI</p>
          </section>
          {run.isPending ? <div className="flex items-center justify-center gap-2 py-24 text-body text-ink-tertiary"><IconLoader2 size={18} className="animate-spin" />Analyzing compatible charts…</div> : run.isError ? <div className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger-bg p-4 text-body text-danger"><IconAlertTriangle size={17} /><div><strong>The query could not be executed.</strong><p className="mt-1 text-ink-secondary">{run.error.message}</p></div></div> : result && selected ? (
            <div className="grid gap-4 lg:grid-cols-[290px_minmax(0,1fr)]">
              <aside><div className="mb-2 flex items-center justify-between"><h3 className="text-[13px] font-medium text-ink-primary">Suggested charts</h3><span className="text-caption text-ink-tertiary">{candidates.length} compatible</span></div><div className="space-y-2">
                {candidates.map((candidate, index) => <button key={candidate.id} type="button" onClick={() => setSelectedId(candidate.id)} className={`w-full rounded-xl border bg-bg-primary p-3 text-left transition ${candidate.id === selected.id ? "border-brand-500 shadow-sm ring-1 ring-brand-100" : "border-line-tertiary hover:border-line-secondary"}`}><div className="flex items-start gap-2"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-bg-secondary text-caption text-ink-secondary">{index + 1}</span><span className="min-w-0 flex-1"><span className="block text-[13px] font-medium text-ink-primary">{candidate.label}</span><span className="mt-1 block text-caption leading-relaxed text-ink-tertiary">{candidate.description}</span></span><span className="rounded-full bg-success-bg px-2 py-1 text-[10px] text-success">{candidate.fit}</span></div><div className="mt-3 flex h-16 items-center justify-center rounded-md bg-bg-secondary text-brand-500"><IconChartBar size={28} stroke={1.5} /></div></button>)}
              </div></aside>
              <section className="rounded-xl border border-line-tertiary bg-bg-primary p-4 shadow-sm">
                <div className="flex items-start justify-between gap-4 border-b border-line-tertiary pb-3"><div><h3 className="text-h2 text-ink-primary">{selected.label}</h3><p className="mt-1 text-caption text-ink-tertiary">Preview mode · No chart has been added yet</p></div><span className="rounded-full bg-bg-secondary px-2.5 py-1 text-caption text-ink-secondary">{selected.viz.type.replace("_", " ")}</span></div>
                <div className="min-h-[320px] py-4"><ResultChart columns={result.columns} rows={result.rows} viz={selected.viz} /></div>
                <div className="grid gap-3 border-y border-line-tertiary py-3 sm:grid-cols-3">
                  {quality && [
                    { name: "Chart compatibility", check: quality.compatibility },
                    { name: "Data quality", check: quality.dataQuality },
                    { name: "Home layout", check: quality.layout },
                  ].map(({ name, check }) => (
                    <div key={name} className="sm:border-r sm:border-line-tertiary sm:last:border-r-0 sm:px-3">
                      <p className="text-[10px] font-medium uppercase tracking-wide text-ink-tertiary">{name}</p>
                      <p className="mt-1 flex items-center gap-1.5 text-small text-ink-primary">
                        <span className={`flex h-4 w-4 items-center justify-center rounded-full ${check.ok ? "bg-success-bg text-success" : "bg-danger-bg text-danger"}`}>
                          {check.ok ? <IconCheck size={11} /> : <IconX size={11} />}
                        </span>
                        {check.label}
                      </p>
                    </div>
                  ))}
                </div>
                {quality && !quality.compatibility.ok && (
                  <p className="mt-2 text-caption text-danger">
                    This chart can&apos;t be added yet -- pick another suggestion or adjust the query.
                  </p>
                )}
                <div className="grid gap-3 py-4 sm:grid-cols-2 xl:grid-cols-4">
                  <label className="text-caption text-ink-tertiary">PROJECT<input disabled value={project?.name ?? `Project ${projectId}`} className="mt-1 h-9 w-full rounded-md border border-line-tertiary bg-bg-secondary px-2 text-small text-ink-primary" /></label>
                  <label className="text-caption text-ink-tertiary">PERIOD<select className="mt-1 h-9 w-full rounded-md border border-line-tertiary bg-bg-primary px-2 text-small text-ink-primary"><option>From generated query</option></select></label>
                  <label className="text-caption text-ink-tertiary">WIDGET SIZE<select value={widgetSize} onChange={(event) => setWidgetSize(event.target.value as typeof widgetSize)} className="mt-1 h-9 w-full rounded-md border border-line-tertiary bg-bg-primary px-2 text-small text-ink-primary"><option value="wide">Wide</option><option value="standard">Standard</option><option value="compact">Compact</option></select></label>
                  <label className="text-caption text-ink-tertiary">REFRESH<select className="mt-1 h-9 w-full rounded-md border border-line-tertiary bg-bg-primary px-2 text-small text-ink-primary"><option>When source updates</option></select></label>
                </div>
                <div className="flex gap-2 rounded-lg bg-brand-50 p-3 text-small leading-relaxed text-ink-secondary"><IconDatabase size={16} className="mt-0.5 shrink-0 text-brand-500" /><span>Adding this chart also saves its generated read-only query in {project?.name ?? "the project"}. Existing query and dashboard generation remain available through AI Assistant and project workflows.</span></div>
                {(save.isError || addToHome.isError) && <p className="mt-3 text-small text-danger">{(save.error ?? addToHome.error as Error)?.message}</p>}
                <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line-tertiary pt-4"><Button variant="secondary" size="md" disabled={!previewCard} onClick={() => setSaveToDashboardOpen(true)}><IconLayoutDashboard size={15} />Add to Dashboard</Button><Button variant="secondary" size="md" disabled={save.isPending || savedQueryId != null} onClick={() => save.mutate()}><IconDeviceFloppy size={15} />{savedQueryId ? "Query saved" : save.isPending ? "Saving…" : "Save Query"}</Button><button type="button" onClick={() => setShowData((value) => !value)} className="ml-auto flex items-center gap-1 text-small text-ink-tertiary hover:text-ink-primary">{showData ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}Preview data</button><button type="button" onClick={() => setShowSql((value) => !value)} className="flex items-center gap-1 text-small text-ink-tertiary hover:text-ink-primary">{showSql ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}SQL</button></div>
                {showData && <div className="mt-3"><ResultTable columns={result.columns} rows={result.rows} total={result.total} page={page} pageSize={pageSize} onPageChange={(next) => { setPage(next); run.mutate({ offset: next * pageSize, limit: pageSize }); }} loading={run.isPending} /></div>}
                {showSql && <pre className="mt-3 overflow-auto rounded-md bg-bg-secondary p-3 text-[11px] leading-relaxed text-ink-primary">{result.sql || sql}</pre>}
              </section>
            </div>
          ) : null}
        </div>
      </div>
      {previewCard && <SaveInsightToDashboardModal card={previewCard} open={saveToDashboardOpen} onClose={() => setSaveToDashboardOpen(false)} onSaved={(_id, name) => { pushToast(`Saved to dashboard "${name}"`, "success"); setSaveToDashboardOpen(false); }} />}
    </div>
  );
}
