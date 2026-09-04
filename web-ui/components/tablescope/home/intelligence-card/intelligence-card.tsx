"use client";


import { Fragment, type ReactNode, useMemo, useState } from "react";
import {
  IconChevronRight,
  IconPin,
  IconPinnedFilled,
} from "@tabler/icons-react";

import { useCurrentUser } from "@/lib/ui/use-shell-data";
import { canManageProjectActions } from "@/lib/auth";
import { InsightAnalysisStrip } from "../insight-analysis-strip";
import { InsightTimeSeriesChart } from "../../insights/insight-time-series-chart";
import { WidgetRenderer } from "@/components/dashboard/WidgetRenderer";
import type {
  VisualizationOptions,
  WidgetConfig,
  WidgetType,
} from "@/components/dashboard/types";
import type {
  InsightCallout,
  InsightCard as InsightCardData,
  TimeSeriesViewState,
  VizCandidate,
} from "@/lib/api/home-intelligence";
import type { GovernanceItem, InsightFeedbackRecord, InsightSentiment } from "@/lib/api/insight-feedback";
import { ChartSuggestionDialog } from "../chart-suggestion-dialog";
import { InsightExplanationPanel } from "../insight-explanation-panel";
import { InsightFeedbackDialog } from "../insight-feedback-dialog";
import {
  InsightFeedbackStatusBadge,
  InsightFeedbackStatusDialog,
  InsightGovernanceBadge,
} from "../insight-feedback-status";
import { InsightCardActionToolbar } from "@/components/tablescope/insights/insight-card-action-toolbar";
import { exportInsightCardPng, insightPngFilename } from "@/lib/insights/export-png";
import {
  canExportInsightCsv,
  exportInsightCardCsv,
  insightCsvFilename,
} from "@/lib/insights/export-csv";
import { exportInsightCardSql, insightSqlFilename } from "@/lib/insights/export-sql";
import { useToasts, ToastViewport } from "@/components/ui/toast";
import { CARD_SEVERITY } from "@/lib/ui/insight-tones";
import { cn } from "@/lib/cn";
import { renderBold } from "./render-bold";
import { applyCandidateToInsightChart } from "@/lib/insights/chart-candidate";
import { calloutLabel } from "./callout-label";
import { KpiGridView } from "./kpi-grid-view";
import { IntelligenceCardProps } from "./intelligence-card-props";



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
  presentation = "default",
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
  const [sqlExporting, setSqlExporting] = useState(false);
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
      chart: applyCandidateToInsightChart(card.chart, selectedChart),
      chartType: d.chartType,
      visualizationDecision: d,
    };
  }, [card, selectedChart, timeSeriesView]);

  const sev = CARD_SEVERITY[card.severity] ?? CARD_SEVERITY.info;
  const executive = presentation === "executive" && !frozen;

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

  const handleExportSql = async () => {
    setSqlExporting(true);
    try {
      exportInsightCardSql(displayCard);
      pushToast(`SQL downloaded: ${insightSqlFilename(displayCard)}`, "success");
    } catch (err) {
      pushToast(err instanceof Error ? err.message : "Failed to export SQL", "error");
    } finally {
      setSqlExporting(false);
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
          : cn(
              executive
                ? "overflow-hidden rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-sm"
                : "rounded-lg border border-line-tertiary bg-white p-4",
            )
      }
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div
            className={cn(
              "flex items-center gap-2 text-small text-ink-tertiary",
              executive && "font-medium uppercase tracking-wide",
            )}
          >
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: card.projectColor }}
            />
            <span className="truncate">{card.projectName}</span>
          </div>
          <h3
            className={cn(
              "mt-1 text-h3 text-ink-primary",
              executive && "mt-2 text-[20px] leading-7",
            )}
          >
            {!executive && <span className="text-ink-tertiary">Title: </span>}
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

      <p
        className={cn(
          "mt-2 text-body text-ink-secondary",
          executive && "max-w-5xl leading-6",
        )}
      >
        {!executive && <span className="text-ink-tertiary">Summary: </span>}
        {renderBold(card.summary)}
      </p>

      <div className={cn("mt-3 flex flex-col", frozen && "relative flex-1 overflow-hidden")}>
        {displayCard.chart && (
          <div
            className={cn(
              "min-h-0",
              frozen && "flex-1 overflow-hidden",
              executive &&
                "rounded-xl border border-line-tertiary bg-bg-secondary/35 p-3",
            )}
          >
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
                height={executive ? 260 : undefined}
                presentation={executive ? "operational" : "default"}
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
        <div
          className={cn(
            frozen && "mt-auto",
            executive && "mt-4 border-t border-line-tertiary pt-3",
          )}
        >
          <InsightCardActionToolbar
            card={displayCard}
            actionsDisclosure={actionsDisclosure}
            overlay={false}
            canCreateAction={canCreateAction}
            onCreateAction={canCreateAction ? onCreateAction : undefined}
            onExplain={() => setExplainOpen(true)}
            onChartOptions={() => setChartDialogOpen(true)}
            onAddToDashboard={
              onSaveToDashboard ? () => onSaveToDashboard(displayCard) : undefined
            }
            onDownloadPng={handleDownloadPng}
            isPngExporting={pngExporting}
            onExportSql={displayCard.sql?.trim() ? handleExportSql : undefined}
            isSqlExporting={sqlExporting}
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
        </div>
      )}
      </div>

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
