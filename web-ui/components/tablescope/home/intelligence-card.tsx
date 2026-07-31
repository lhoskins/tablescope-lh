"use client";

import { Fragment, type ReactNode, useMemo, useState } from "react";
import {
  IconChevronRight,
  IconPin,
  IconPinnedFilled,
} from "@tabler/icons-react";

import { useCurrentUser } from "@/lib/ui/use-shell-data";
import { canManageProjectActions } from "@/lib/auth";
import { InsightAnalysisStrip } from "./insight-analysis-strip";
import { InsightTimeSeriesChart } from "../insights/insight-time-series-chart";
import { WidgetRenderer } from "@/components/dashboard/WidgetRenderer";
import type {
  VisualizationOptions,
  WidgetConfig,
  WidgetType,
} from "@/components/dashboard/types";
import type {
  InsightCallout,
  InsightCard as InsightCardData,
  InsightChart,
  TimeSeriesViewState,
  VizCandidate,
} from "@/lib/api/home-intelligence";
import type { GovernanceItem, InsightFeedbackRecord, InsightSentiment } from "@/lib/api/insight-feedback";
import { ChartSuggestionDialog } from "./chart-suggestion-dialog";
import { InsightExplanationPanel } from "./insight-explanation-panel";
import { InsightFeedbackDialog } from "./insight-feedback-dialog";
import {
  InsightFeedbackStatusBadge,
  InsightFeedbackStatusDialog,
  InsightGovernanceBadge,
} from "./insight-feedback-status";
import { InsightCardActionToolbar } from "@/components/tablescope/insights/insight-card-action-toolbar";
import { exportInsightCardPng, insightPngFilename } from "@/lib/insights/export-png";
import {
  canExportInsightCsv,
  exportInsightCardCsv,
  insightCsvFilename,
} from "@/lib/insights/export-csv";
import { useToasts, ToastViewport } from "@/components/ui/toast";
import { CARD_SEVERITY } from "@/lib/ui/insight-tones";

/** Remove every remaining `**` marker (matched pairs handled by renderBold). */
export function stripStars(text: string): string {
  return text.replace(/\*\*/g, "");
}

/** Render a string with `**bold**` markers as bold spans; strip stray `**`. */
export function renderBold(text: string): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-ink-primary">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return <Fragment key={i}>{stripStars(part)}</Fragment>;
  });
}

/** Short text prefix that replaces the old callout icon. */
function calloutLabel(type: InsightCallout["type"]): string {
  if (type === "opportunity") return "Action:";
  if (type === "risk") return "Caution:";
  return "Note:";
}

/**
 * Render a chart through the same `WidgetRenderer` the dashboard uses, so
 * Intelligence cards share the dashboard's full chart catalog and styling.
 * The backend emits a `{label, value}` series plus a dashboard chart
 * `type`/`subtype`; we adapt that into a minimal `WidgetConfig` + rows.
 */
function buildMultiDimWidget(chart: InsightChart, dataRows: Record<string, unknown>[]): WidgetConfig {
  const roles = chart.roles ?? {};
  const type = chart.type as WidgetType;
  const base: WidgetConfig = {
    id: "insight-chart",
    type,
    chartSubtype: (chart.subtype || undefined) as WidgetConfig["chartSubtype"],
    title: "",
    dataSource: { kind: "custom_sql" },
    xColumn: roles.x ?? "",
    yColumn: roles.value ?? roles.y ?? "",
    aggregation: "sum",
    sortBy: "x_asc",
    filters: [],
    visualizationOptions: { showLegend: type === "radar", showGrid: false },
    colSpan: 1,
    position: 0,
  };

  if (type === "scatter" || type === "effect_scatter") {
    return {
      ...base,
      xColumn: roles.x ?? "x",
      yColumn: roles.y ?? "y",
      groupByColumn: roles.group,
      xColumnType: "number",
    };
  }
  if (type === "radar") {
    return { ...base, xColumn: roles.x ?? "subject", yColumn: roles.value ?? "value", groupByColumn: roles.group ?? "metric" };
  }
  if (type === "heatmap") {
    return { ...base, xColumn: roles.x ?? "", yColumn: roles.value ?? "", groupByColumn: roles.y ?? roles.group ?? "" };
  }
  if (type === "treemap" || type === "sankey" || type === "sunburst" || type === "tree" || type === "graph") {
    return { ...base, xColumn: roles.x ?? "", yColumn: roles.value ?? "", groupByColumn: roles.group ?? "" };
  }
  if (type === "funnel" || type === "gauge") {
    return { ...base, xColumn: roles.x ?? (Object.keys(dataRows[0] ?? {})[0] || ""), yColumn: roles.value ?? "" };
  }
  if (type === "parallel" || type === "lines" || type === "candlestick" || type === "boxplot" || type === "pictorial_bar" || type === "theme_river" || type === "map") {
    return { ...base, xColumn: roles.x ?? "", yColumn: roles.value ?? roles.y ?? "", groupByColumn: roles.group ?? "" };
  }
  if (type === "combo" && roles.y2) {
    return { ...base, xColumn: roles.x ?? "label", yColumn: roles.y ?? "value", y2Column: roles.y2, y2Aggregation: "sum" };
  }
  return { ...base, xColumn: roles.x ?? "label", yColumn: roles.value ?? roles.y ?? "value" };
}

export function InsightChartView({
  chart,
  height: heightProp,
  options,
}: {
  chart: InsightChart;
  height?: number;
  /**
   * Extra renderer options merged over the defaults — used to carry annotations
   * an analysis produced (e.g. the exact points a method flagged) through to
   * the chart.
   */
  options?: Partial<VisualizationOptions>;
}) {
  const dataRows = chart.data.rows;
  const series = chart.data.series;

  if (dataRows && dataRows.length > 0) {
    const widget = buildMultiDimWidget(chart, dataRows);
    if (options) {
      widget.visualizationOptions = { ...widget.visualizationOptions, ...options };
    }
    const height =
      heightProp ??
      (chart.type === "funnel" || chart.type === "sankey"
        ? 260
        : chart.type === "heatmap"
          ? 240
          : 220);
    return (
      <div className="w-full" style={{ height }}>
        <WidgetRenderer widget={widget} data={dataRows} />
      </div>
    );
  }

  if (!series || series.length === 0) return null;

  // Two-metric charts (combo/scatter/bubble) carry a second value; expose both
  // columns so the renderer can map them onto the right axes.
  const hasValue2 = series.some((s) => typeof s.value2 === "number");
  const labels = chart.seriesLabels;
  const roles = chart.roles;
  const valueName = labels?.value ?? roles?.y ?? "value";
  const value2Name = labels?.value2 ?? roles?.y2 ?? "value2";
  const xName = roles?.x ?? "label";

  // For scatter, the first metric is the X axis and the second is the Y axis.
  const isScatter = chart.type === "scatter";
  const xColumnName = isScatter ? valueName : xName;
  const yColumnName = isScatter ? value2Name : valueName;

  const rows = series.map((s) => {
    if (isScatter) {
      return { [valueName]: s.value, [value2Name]: s.value2 ?? 0 };
    }
    if (hasValue2) {
      return { [xName]: s.label, [valueName]: s.value, [value2Name]: s.value2 ?? 0 };
    }
    return { [xName]: s.label, [valueName]: s.value };
  });

  const base: WidgetConfig = {
    id: "insight-chart",
    type: chart.type as WidgetType,
    chartSubtype: (chart.subtype || undefined) as WidgetConfig["chartSubtype"],
    title: "",
    dataSource: { kind: "custom_sql" },
    xColumn: xColumnName,
    xColumnType: isScatter ? "number" : "string",
    yColumn: yColumnName,
    aggregation: "sum",
    sortBy: "x_asc",
    filters: [],
    visualizationOptions: { showLegend: false, showGrid: false, ...options },
    colSpan: 1,
    position: 0,
  };

  let widget: WidgetConfig = base;
  if ((chart.type === "combo" && hasValue2) || chart.type === "scatter") {
    widget = { ...base, y2Column: isScatter ? undefined : value2Name, y2Aggregation: "sum" };
  }

  // Horizontal bars stack their category labels down the y-axis, so give each
  // bar vertical room instead of cramming them into a fixed 180px box.
  const isHorizontalBar =
    chart.type === "bar" &&
    (chart.subtype === "horizontal_bar" ||
      chart.subtype === "stacked_horizontal");
  const height =
    heightProp ??
    (isHorizontalBar
      ? Math.min(520, Math.max(180, rows.length * 28 + 48))
      : 180);

  return (
    <div className="w-full" style={{ height }}>
      <WidgetRenderer widget={widget} data={rows} />
    </div>
  );
}

function KpiGridView({
  kpis,
}: {
  kpis: { value: string; label: string; delta?: string }[];
}) {
  return (
    <div className="grid grid-cols-3 gap-2">
      {kpis.map((k, i) => (
        <div
          key={i}
          className="rounded-md border border-line-tertiary bg-bg-secondary p-3"
        >
          <div className="text-h2 font-semibold text-ink-primary">
            {k.value}
          </div>
          <div className="mt-0.5 text-small text-ink-tertiary">{k.label}</div>
          {k.delta && (
            <div className="mt-1 text-small font-medium text-ink-secondary">
              {k.delta}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/**
 * Render an {@link InsightChart} (kpi grid or any dashboard chart) standalone.
 * Shared by the Intelligence feed and the Home dashboard-suggestion previews.
 */
export function InsightChartBlock({
  chart,
  options,
}: {
  chart: InsightChart;
  options?: Partial<VisualizationOptions>;
}) {
  return (
    <>
      {chart.title && (
        <div className="mb-1 text-small text-ink-tertiary">{chart.title}</div>
      )}
      {chart.type === "kpi_grid" && chart.data.kpis ? (
        <KpiGridView kpis={chart.data.kpis} />
      ) : (
        <InsightChartView chart={chart} options={options} />
      )}
    </>
  );
}

export interface IntelligenceCardProps {
  card: InsightCardData;
  /** Hide the "Add to dashboard / Pin / Add to report" actions, but keep Explain and feedback. */
  hideActions?: boolean;
  onAddToReport?: (card: InsightCardData) => void;
  onPin?: (card: InsightCardData) => void;
  onUnpin?: (card: InsightCardData) => void;
  onSaveToDashboard?: (card: InsightCardData) => void;
  pinned?: boolean;
  /** Whether this card is a frozen snapshot (Home pin). Used by the Explain panel. */
  frozen?: boolean;
  /** The current user's feedback for this card, if any. */
  feedback?: InsightFeedbackRecord | null;
  onFeedbackSave?: (payload: {
    sentiment: InsightSentiment;
    reason_codes: string[];
    comment: string;
  }) => void | Promise<void>;
  onFeedbackRemove?: () => void | Promise<void>;
  /** Respond to a reviewer request for more information. */
  onFeedbackRespond?: (response: string) => void | Promise<void>;
  savingFeedback?: boolean;
  responding?: boolean;
  /** Governance summary for this insight (visible to all project members). */
  governance?: GovernanceItem | null;
  /** If provided and the user may create actions, shows a "+ Action" button. */
  onCreateAction?: () => void;
  /** Collapse data sources and actions behind a "More Actions" toggle. */
  actionsDisclosure?: "always-visible" | "collapsible";
}

export function IntelligenceCard({
  card,
  hideActions,
  onPin,
  onUnpin,
  onSaveToDashboard,
  pinned,
  frozen,
  feedback,
  onFeedbackSave,
  onFeedbackRemove,
  onFeedbackRespond,
  savingFeedback = false,
  responding = false,
  governance,
  onCreateAction,
  actionsDisclosure,
}: IntelligenceCardProps) {
  const [explainOpen, setExplainOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [statusDialogOpen, setStatusDialogOpen] = useState(false);
  const [feedbackInitial, setFeedbackInitial] = useState<InsightSentiment>("agree");
  const [chartDialogOpen, setChartDialogOpen] = useState(false);
  const [selectedChart, setSelectedChart] = useState<VizCandidate | null>(null);
  const [timeSeriesView, setTimeSeriesView] = useState<TimeSeriesViewState | undefined>(
    card.timeSeriesView,
  );
  const [pngExporting, setPngExporting] = useState(false);
  const [csvExporting, setCsvExporting] = useState(false);
  const { toasts, push: pushToast, dismiss } = useToasts();
  const { data: identity } = useCurrentUser();

  const projectIdNumber = Number(card.projectId);
  const stableInsightId = card.insightId || card.id;

  const displayCard = useMemo<InsightCardData>(() => {
    const base = timeSeriesView ? { ...card, timeSeriesView } : card;
    if (!selectedChart || !card.chart) return base;
    const d = selectedChart.decision;
    return {
      ...base,
      chart: {
        ...card.chart,
        type: d.chartType as InsightChart["type"],
        subtype: d.chartStyle || undefined,
      },
      chartType: d.chartType,
      visualizationDecision: d,
    };
  }, [card, selectedChart, timeSeriesView]);

  const sev = CARD_SEVERITY[card.severity] ?? CARD_SEVERITY.info;

  const canCreateAction = Boolean(
    onCreateAction &&
      canManageProjectActions(identity?.user?.rawRole, identity?.user?.isSuperAdmin),
  );

  const handleFeedbackClick = (sentiment: InsightSentiment) => {
    setFeedbackInitial(sentiment);
    setFeedbackOpen(true);
  };

  const handleDownloadPng = async () => {
    setPngExporting(true);
    try {
      await exportInsightCardPng(stableInsightId, insightPngFilename(displayCard));
    } catch (err) {
      pushToast(err instanceof Error ? err.message : "Failed to download PNG", "error");
    } finally {
      setPngExporting(false);
    }
  };

  const handleExportCsv = async () => {
    setCsvExporting(true);
    try {
      await exportInsightCardCsv(displayCard);
      pushToast(`CSV downloaded: ${insightCsvFilename(displayCard)}`, "success");
    } catch (err) {
      pushToast(err instanceof Error ? err.message : "Failed to export CSV", "error");
    } finally {
      setCsvExporting(false);
    }
  };

  const canExportCsv = useMemo(
    () => canExportInsightCsv(displayCard),
    [displayCard],
  );

  return (
    <article
      data-insight-card-id={stableInsightId}
      className={
        frozen
          ? "flex h-full flex-col p-3"
          : "rounded-lg border border-line-tertiary bg-white p-4"
      }
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-small text-ink-tertiary">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: card.projectColor }}
            />
            <span className="truncate">{card.projectName}</span>
          </div>
          <h3 className="mt-1 text-h3 text-ink-primary">
            <span className="text-ink-tertiary">Title: </span>
            {renderBold(card.title)}
          </h3>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <div className="flex items-center gap-1.5">
            <InsightGovernanceBadge status={governance?.governance_status} />
            <span
              className={`rounded-full px-2 py-0.5 text-small font-medium ${sev.chip}`}
            >
              {sev.label}
            </span>
          </div>
          {card.explanation?.governance?.decision === "fallback" && (
            <span className="rounded-full bg-sky-50 px-2 py-0.5 text-small font-medium text-sky-700">
              AI fallback
            </span>
          )}
          {pinned ? (
            <button
              type="button"
              data-export-hide
              onClick={onUnpin ? () => onUnpin(displayCard) : undefined}
              aria-label={onUnpin ? "Unpin from Home" : "Pinned to Home"}
              title={onUnpin ? "Unpin from Home" : "Pinned to Home"}
              className="rounded-md p-1 text-danger focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-100"
              disabled={!onUnpin}
            >
              <IconPinnedFilled size={18} />
            </button>
          ) : onPin ? (
            <button
              type="button"
              data-export-hide
              onClick={() => onPin(displayCard)}
              aria-label="Pin to Home"
              title="Pin to Home"
              className="rounded-md p-1 text-ink-tertiary transition-colors hover:bg-bg-tertiary hover:text-ink-secondary focus:outline-none focus:ring-2 focus:ring-brand-500"
            >
              <IconPin size={18} />
            </button>
          ) : null}
        </div>
      </header>

      <p className="mt-2 text-body text-ink-secondary">
        <span className="text-ink-tertiary">Summary: </span>
        {renderBold(card.summary)}
      </p>

      {displayCard.chart && (
        <div className="mt-3">
          {displayCard.chart.title && displayCard.chart.type !== "kpi_grid" && (
            <div className="mb-1 text-small text-ink-tertiary">
              {displayCard.chart.title}
            </div>
          )}
          {displayCard.chart.type === "kpi_grid" && displayCard.chart.data.kpis ? (
            <KpiGridView kpis={displayCard.chart.data.kpis} />
          ) : (
            <InsightTimeSeriesChart
              card={displayCard}
              projectId={Number(displayCard.projectId)}
              onViewChange={setTimeSeriesView}
            />
          )}
        </div>
      )}

      {card.callout && (
        <div
          className={`mt-3 flex items-start gap-2 rounded-md p-3 text-small ${
            card.callout.type === "opportunity"
              ? "bg-success/10 text-success"
              : "bg-warning/10 text-warning"
          }`}
        >
          <span className="shrink-0 font-semibold">
            {calloutLabel(card.callout.type)}
          </span>
          <span className="text-ink-secondary">
            {renderBold(card.callout.text)}
          </span>
        </div>
      )}

      {/* Lead finding + top action; the full dissection lives on its own route.
          Suppressed with the other actions — a shared report is read by people
          who cannot open an authenticated drill-down. */}
      {!hideActions && <InsightAnalysisStrip card={card} />}

      {!hideActions && (
        <InsightCardActionToolbar
          card={displayCard}
          actionsDisclosure={actionsDisclosure}
          canCreateAction={canCreateAction}
          onCreateAction={canCreateAction ? onCreateAction : undefined}
          onExplain={() => setExplainOpen(true)}
          onChartOptions={() => setChartDialogOpen(true)}
          onAddToDashboard={
            onSaveToDashboard ? () => onSaveToDashboard(displayCard) : undefined
          }
          onDownloadPng={handleDownloadPng}
          isPngExporting={pngExporting}
          onExportCsv={canExportCsv ? handleExportCsv : undefined}
          isCsvExporting={csvExporting}
          feedback={feedback}
          onFeedbackClick={
            onFeedbackSave ? handleFeedbackClick : undefined
          }
          feedbackStatus={
            feedback ? (
              <InsightFeedbackStatusBadge
                feedback={feedback}
                onClick={() => setStatusDialogOpen(true)}
              />
            ) : undefined
          }
          selectedChart={selectedChart}
        />
      )}

      <ToastViewport toasts={toasts} onDismiss={dismiss} />

      <InsightExplanationPanel
        card={displayCard}
        open={explainOpen}
        onClose={() => setExplainOpen(false)}
        frozen={frozen}
      />

      {onFeedbackSave && (
        <InsightFeedbackDialog
          card={card}
          open={feedbackOpen}
          onClose={() => setFeedbackOpen(false)}
          feedback={feedback || null}
          initialSentiment={feedbackInitial}
          onSave={onFeedbackSave}
          onRemove={async () => {
            await onFeedbackRemove?.();
            setFeedbackOpen(false);
          }}
          saving={savingFeedback}
        />
      )}

      {feedback && (
        <InsightFeedbackStatusDialog
          open={statusDialogOpen}
          onClose={() => setStatusDialogOpen(false)}
          feedback={feedback}
          title={card.title}
          onRespond={onFeedbackRespond ? (response) => void onFeedbackRespond(response) : undefined}
          onEdit={() => {
            setStatusDialogOpen(false);
            setFeedbackOpen(true);
          }}
          onWithdraw={async () => {
            await onFeedbackRemove?.();
            setStatusDialogOpen(false);
          }}
          responding={responding}
          withdrawing={savingFeedback}
        />
      )}

      <ChartSuggestionDialog
        card={card}
        projectId={projectIdNumber}
        open={chartDialogOpen}
        onClose={() => setChartDialogOpen(false)}
        onApplied={(candidate) => setSelectedChart(candidate)}
      />
    </article>
  );
}

export function LoadingCard({ projectName }: { projectName: string }) {
  return (
    <div className="rounded-lg border border-line-tertiary bg-white p-4">
      <div className="flex items-center gap-2 text-small text-ink-tertiary">
        <span className="h-2 w-2 animate-pulse rounded-full bg-line-secondary" />
        <span>{projectName}</span>
        <IconChevronRight size={13} />
        <span className="text-ink-tertiary">Analyzing…</span>
      </div>
      <div className="mt-3 space-y-2">
        <div className="h-3 w-2/3 animate-pulse rounded bg-bg-tertiary" />
        <div className="h-3 w-full animate-pulse rounded bg-bg-tertiary" />
        <div className="h-20 w-full animate-pulse rounded bg-bg-tertiary" />
      </div>
    </div>
  );
}
