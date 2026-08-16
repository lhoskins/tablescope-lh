"use client";

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  IconAlertTriangle,
  IconChevronDown,
  IconChevronRight,
  IconCode,
  IconDeviceFloppy,
  IconLayoutDashboard,
  IconLoader2,
  IconX,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { useToasts } from "@/components/ui/toast";
import { ResultChart, ResultTable, ChartOptions } from "@/components/ai/ai-result-view";
import { runDatasourceSql } from "@/lib/api/data-source-builder";
import { saveQuerySuggestion } from "@/lib/api/home-intelligence";
import { useProjectSummaries } from "@/lib/ui/use-shell-data";
import type { SuggestedVisualization } from "@/lib/api/ai-actions";
import type { InsightCard } from "@/lib/api/home-intelligence";
import { SaveInsightToDashboardModal } from "./save-insight-to-dashboard-modal";

type BackendViz = {
  type: string;
  chartStyle?: string;
  xField?: string;
  yField?: string;
  metricField?: string;
  topN?: number;
};

type RunResult = {
  columns: string[];
  rows: Record<string, unknown>[];
  total?: number;
  sql?: string;
  suggestedVisualization?: BackendViz;
};

function isNumeric(value: unknown): boolean {
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "string") {
    const n = Number(value.replace(/,/g, "").trim());
    return value.trim() !== "" && Number.isFinite(n);
  }
  return false;
}

/**
 * Infer a simple chart from a raw result so a preview renders a widget, not just
 * a table: a single numeric scalar -> KPI; a category + measure -> bar; anything
 * else -> table only.
 */
function inferViz(
  columns: string[],
  rows: Record<string, unknown>[],
): SuggestedVisualization {
  if (!columns.length || !rows.length) return { type: "table" };
  const numericCols = columns.filter(
    (c) =>
      rows.filter((r) => isNumeric(r[c])).length >= Math.max(1, rows.length / 2),
  );
  if (rows.length === 1 && numericCols.length >= 1) {
    return { type: "kpi", metricField: numericCols[0] };
  }
  const valueCol = numericCols[0];
  if (!valueCol) return { type: "table" };
  const labelCol = columns.find((c) => c !== valueCol) ?? columns[0];
  return { type: "bar", xField: labelCol, yField: valueCol };
}

/**
 * Preview a suggested query by running its SQL (without an added LIMIT) and,
 * only from here, allow saving it. Used by the Business Insight query
 * suggestions so a user can verify results before persisting the query.
 */
export function QuerySuggestionPreviewModal({
  open,
  projectId,
  title,
  description,
  sql,
  onClose,
  onSaved,
}: {
  open: boolean;
  projectId: number;
  title: string;
  description: string;
  sql: string;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const [showSql, setShowSql] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveToDashboardOpen, setSaveToDashboardOpen] = useState(false);
  const [selectedViz, setSelectedViz] = useState<SuggestedVisualization | null>(null);
  const [page, setPage] = useState(0);
  const [pageSize] = useState(100);
  const { push: pushToast } = useToasts();
  const { data: projects } = useProjectSummaries();

  const run = useMutation<RunResult, Error, { offset: number; limit: number }>({
    mutationFn: (vars) => runDatasourceSql({ sql, project_id: projectId, ...vars }),
  });

  const save = useMutation({
    mutationFn: () =>
      saveQuerySuggestion({
        project_id: projectId,
        name: title,
        description,
        sql_text: result?.sql || sql,
      }),
    onSuccess: () => {
      setSaved(true);
      onSaved?.();
    },
  });

  useEffect(() => {
    if (!open) return;
    setShowSql(false);
    setSaved(false);
    setSelectedViz(null);
    setPage(0);
    run.mutate({ offset: 0, limit: pageSize });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, sql]);

  if (!open) return null;

  const result = run.data;
  const inferredViz: SuggestedVisualization = result?.suggestedVisualization
    ? (result.suggestedVisualization as SuggestedVisualization)
    : result
      ? inferViz(result.columns, result.rows)
      : { type: "table" as const };
  const viz = selectedViz ?? inferredViz;

  const project = projects?.find((p) => Number(p.id) === projectId);
  const previewCard: InsightCard | null = result
    ? {
        id: `query-preview-${projectId}`,
        projectId: String(projectId),
        projectName: project?.name ?? "",
        projectColor: project?.accent ?? "",
        insightType: "query_suggestion",
        severity: "info",
        title: title || "Query Preview",
        summary: description,
        chart: null,
        callout: null,
        sources: { tables: [], documents: [] },
        executedAt: new Date().toISOString(),
        sql: result.sql || sql,
        chartType: viz.type,
        labelColumn:
          viz.type === "kpi"
            ? undefined
            : viz.xField ?? result.columns[0],
        valueColumn:
          viz.yField ?? viz.metricField ?? result.columns[1] ?? result.columns[0],
      }
    : null;

  const canAddToDashboard = Boolean(
    previewCard &&
      previewCard.sql &&
      (viz.type === "kpi" || previewCard.valueColumn),
  );

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4">
      <div className="my-8 w-full max-w-3xl rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-h2 text-ink-primary">
              <IconCode size={18} className="text-brand-500" />
              {title || "Query Preview"}
            </h2>
            {description && (
              <p className="mt-1 text-[13px] text-ink-secondary">{description}</p>
            )}
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

        <div className="mt-4">
          {run.isPending ? (
            <div className="flex items-center justify-center gap-2 py-10 text-[13px] text-ink-tertiary">
              <IconLoader2 size={16} className="animate-spin" />
              Running query…
            </div>
          ) : run.isError ? (
            <div className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger-bg px-3 py-2.5 text-[13px] text-danger">
              <IconAlertTriangle size={16} className="mt-0.5 shrink-0" />
              <div>
                <div className="font-medium">
                  The query could not be executed.
                </div>
                <div className="mt-0.5 text-ink-secondary">
                  {(run.error as Error).message}
                </div>
              </div>
            </div>
          ) : (
            result && (
              <>
                <div className="mb-2 flex justify-end">
                  <ChartOptions
                    columns={result.columns}
                    rows={result.rows}
                    value={viz}
                    onChange={setSelectedViz}
                  />
                </div>
                <ResultChart
                  columns={result.columns}
                  rows={result.rows}
                  viz={viz}
                />
                <ResultTable
                  columns={result.columns}
                  rows={result.rows}
                  total={result.total}
                  page={page}
                  pageSize={pageSize}
                  onPageChange={(nextPage) => {
                    setPage(nextPage);
                    run.mutate({ offset: nextPage * pageSize, limit: pageSize });
                  }}
                  loading={run.isPending}
                />
              </>
            )
          )}

          <div className="mt-3">
            <button
              type="button"
              onClick={() => setShowSql((v) => !v)}
              className="flex items-center gap-1 text-[12px] text-ink-tertiary hover:text-ink-secondary"
            >
              {showSql ? (
                <IconChevronDown size={14} />
              ) : (
                <IconChevronRight size={14} />
              )}
              {showSql ? "Hide SQL" : "Show SQL"}
            </button>
            {showSql && (
              <pre className="mt-1.5 overflow-auto rounded-md bg-bg-secondary p-2.5 text-[11px] leading-relaxed text-ink-primary">
                {result?.sql || sql}
              </pre>
            )}
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-line-tertiary pt-4">
          {save.isError && (
            <span className="mr-auto text-[12px] text-danger">
              {(save.error as Error).message}
            </span>
          )}
          <Button
            variant="secondary"
            size="md"
            disabled={!canAddToDashboard}
            onClick={() => setSaveToDashboardOpen(true)}
          >
            <IconLayoutDashboard size={15} />
            Add to Dashboard
          </Button>
          <Button
            variant="secondary"
            size="md"
            disabled={save.isPending || saved || run.isError}
            onClick={() => save.mutate()}
          >
            <IconDeviceFloppy size={15} />
            {saved ? "Saved" : save.isPending ? "Saving…" : "Save Query"}
          </Button>
          <Button variant="primary" size="md" onClick={onClose}>
            {saved ? "Done" : "Close"}
          </Button>

          {previewCard && (
            <SaveInsightToDashboardModal
              card={previewCard}
              open={saveToDashboardOpen}
              onClose={() => setSaveToDashboardOpen(false)}
              onSaved={(_dashboardId, dashboardName) => {
                pushToast(`Saved to dashboard "${dashboardName}"`, "success");
                setSaveToDashboardOpen(false);
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
