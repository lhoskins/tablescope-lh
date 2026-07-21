"use client";

import { Fragment, type ReactNode, useState } from "react";
import {
  IconChevronRight,
  IconClipboardList,
  IconFileText,
  IconInfoCircle,
  IconLayoutDashboard,
  IconPin,
  IconPinnedOff,
  IconPlus,
  IconTable,
  IconThumbDown,
  IconThumbUp,
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import { canManageProjectActions } from "@/lib/auth";
import { WidgetRenderer } from "@/components/dashboard/WidgetRenderer";
import type { WidgetConfig, WidgetType } from "@/components/dashboard/types";
import type {
  InsightCallout,
  InsightCard as InsightCardData,
  InsightChart,
} from "@/lib/api/home-intelligence";
import type { InsightFeedbackRecord, InsightSentiment } from "@/lib/api/insight-feedback";
import { InsightExplanationPanel } from "./insight-explanation-panel";
import { InsightFeedbackDialog } from "./insight-feedback-dialog";
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
function InsightChartView({ chart }: { chart: InsightChart }) {
  const series = chart.data.series ?? [];
  if (series.length === 0) return null;

  // Two-metric charts (combo/scatter/bubble) carry a second value; expose both
  // columns so the renderer can map them onto the right axes.
  const hasValue2 = series.some((s) => typeof s.value2 === "number");
  const rows = series.map((s) =>
    hasValue2
      ? { label: s.label, value: s.value, value2: s.value2 ?? 0 }
      : { label: s.label, value: s.value },
  );

  const base: WidgetConfig = {
    id: "insight-chart",
    type: chart.type as WidgetType,
    chartSubtype: (chart.subtype || undefined) as WidgetConfig["chartSubtype"],
    title: "",
    dataSource: { kind: "custom_sql" },
    xColumn: "label",
    xColumnType: "string",
    yColumn: "value",
    aggregation: "sum",
    sortBy: "x_asc",
    filters: [],
    visualizationOptions: { showLegend: false, showGrid: false },
    colSpan: 1,
    position: 0,
  };

  let widget: WidgetConfig = base;
  if (chart.type === "combo" && hasValue2) {
    // dual_line -> bars (value) + overlay line (value2) on a shared x axis.
    widget = { ...base, y2Column: "value2", y2Aggregation: "sum" };
  } else if (chart.type === "scatter") {
    // x/y scatter of two metrics; bubble degrades to scatter without a size col.
    widget = {
      ...base,
      xColumn: "value",
      xColumnType: "number",
      yColumn: "value2",
      sortBy: "x_asc",
    };
  }

  // Horizontal bars stack their category labels down the y-axis, so give each
  // bar vertical room instead of cramming them into a fixed 180px box.
  const isHorizontalBar =
    chart.type === "bar" &&
    (chart.subtype === "horizontal_bar" ||
      chart.subtype === "stacked_horizontal");
  const height = isHorizontalBar
    ? Math.min(520, Math.max(180, rows.length * 28 + 48))
    : 180;

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
export function InsightChartBlock({ chart }: { chart: InsightChart }) {
  return (
    <>
      {chart.title && (
        <div className="mb-1 text-small text-ink-tertiary">{chart.title}</div>
      )}
      {chart.type === "kpi_grid" && chart.data.kpis ? (
        <KpiGridView kpis={chart.data.kpis} />
      ) : (
        <InsightChartView chart={chart} />
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
  savingFeedback?: boolean;
  /** If provided and the user may create actions, shows a "+ Action" button. */
  onCreateAction?: () => void;
}

export function IntelligenceCard({
  card,
  hideActions,
  onAddToReport,
  onPin,
  onUnpin,
  onSaveToDashboard,
  pinned,
  frozen,
  feedback,
  onFeedbackSave,
  onFeedbackRemove,
  savingFeedback = false,
  onCreateAction,
}: IntelligenceCardProps) {
  const [explainOpen, setExplainOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedbackInitial, setFeedbackInitial] =
    useState<InsightSentiment>("agree");
  const { data: identity } = useCurrentUser();
  const canCreateAction =
    onCreateAction &&
    canManageProjectActions(identity?.user?.rawRole, identity?.user?.isSuperAdmin);
  const sev = CARD_SEVERITY[card.severity] ?? CARD_SEVERITY.info;
  const canSaveToDashboard = Boolean(
    card.sql?.trim() && card.valueColumn?.trim(),
  );
  const hasFeedback = feedback != null && feedback.status === "active";
  const tables = card.sources?.tables ?? [];
  const documents = card.sources?.documents ?? [];

  const stableInsightId = card.insightId || card.id;

  return (
    <article
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
          <span
            className={`rounded-full px-2 py-0.5 text-small font-medium ${sev.chip}`}
          >
            {sev.label}
          </span>
          {card.explanation?.governance?.decision === "fallback" && (
            <span className="rounded-full bg-sky-50 px-2 py-0.5 text-small font-medium text-sky-700">
              AI fallback
            </span>
          )}
        </div>
      </header>

      <p className="mt-2 text-body text-ink-secondary">
        <span className="text-ink-tertiary">Summary: </span>
        {renderBold(card.summary)}
      </p>

      {card.chart && (
        <div className="mt-3">
          {card.chart.title && (
            <div className="mb-1 text-small text-ink-tertiary">
              {card.chart.title}
            </div>
          )}
          {card.chart.type === "kpi_grid" && card.chart.data.kpis ? (
            <KpiGridView kpis={card.chart.data.kpis} />
          ) : (
            <InsightChartView chart={card.chart} />
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

      <footer className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line-tertiary pt-3">
        <div className="flex flex-wrap items-center gap-3 text-small text-ink-tertiary">
          {tables.map((t) => (
            <span key={t} className="inline-flex items-center gap-1">
              <IconTable size={13} /> {t}
            </span>
          ))}
          {documents.slice(0, 2).map((d) => (
            <span key={d} className="inline-flex items-center gap-1">
              <IconFileText size={13} /> {d}
            </span>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setExplainOpen(true)}
            className="inline-flex items-center gap-1 rounded-md border border-line-tertiary px-2.5 py-1 text-small font-medium text-ink-secondary transition-colors hover:border-line-secondary hover:bg-bg-tertiary"
          >
            <IconInfoCircle size={14} />
            Explain
          </button>

          {canCreateAction && (
            <button
              type="button"
              onClick={onCreateAction}
              className="inline-flex items-center gap-1 rounded-md border border-line-tertiary px-2.5 py-1 text-small font-medium text-ink-secondary transition-colors hover:border-line-secondary hover:bg-bg-tertiary"
            >
              <IconClipboardList size={14} />
              Action
            </button>
          )}

          {onFeedbackSave && stableInsightId && (
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => {
                  setFeedbackInitial("agree");
                  setFeedbackOpen(true);
                }}
                aria-label={
                  hasFeedback && feedback?.sentiment === "agree"
                    ? "Edit agree feedback"
                    : "Agree"
                }
                title={
                  hasFeedback && feedback?.sentiment === "agree"
                    ? "Edit agree feedback"
                    : "Agree"
                }
                className={cn(
                  "inline-flex items-center gap-1 rounded-l-md border px-2.5 py-1 text-small font-medium transition-colors",
                  hasFeedback && feedback?.sentiment === "agree"
                    ? "border-success bg-success/10 text-success hover:bg-success/20"
                    : "border-line-tertiary bg-bg-primary text-ink-secondary hover:border-line-secondary hover:bg-bg-tertiary",
                )}
              >
                <IconThumbUp size={14} />
                Agree
              </button>
              <button
                type="button"
                onClick={() => {
                  setFeedbackInitial("disagree");
                  setFeedbackOpen(true);
                }}
                aria-label={
                  hasFeedback && feedback?.sentiment === "disagree"
                    ? "Edit disagree feedback"
                    : "Disagree"
                }
                title={
                  hasFeedback && feedback?.sentiment === "disagree"
                    ? "Edit disagree feedback"
                    : "Disagree"
                }
                className={cn(
                  "inline-flex items-center gap-1 rounded-r-md border border-l-0 px-2.5 py-1 text-small font-medium transition-colors",
                  hasFeedback && feedback?.sentiment === "disagree"
                    ? "border-danger bg-danger/10 text-danger hover:bg-danger/20"
                    : "border-line-tertiary bg-bg-primary text-ink-secondary hover:border-line-secondary hover:bg-bg-tertiary",
                )}
              >
                <IconThumbDown size={14} />
                Disagree
              </button>
            </div>
          )}

          {!hideActions && (
            <>
              {onSaveToDashboard && (
                <button
                  type="button"
                  disabled={!canSaveToDashboard}
                  title={
                    canSaveToDashboard
                      ? "Add this insight to a project dashboard"
                      : "This insight does not have query data and cannot be added to a dashboard"
                  }
                  onClick={() => onSaveToDashboard(card)}
                  className="inline-flex items-center gap-1 rounded-md border border-line-tertiary px-2.5 py-1 text-small font-medium text-ink-secondary transition-colors hover:border-line-secondary hover:bg-bg-tertiary disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <IconLayoutDashboard size={14} />
                  Add to dashboard
                </button>
              )}
              {onPin && !pinned && (
                <button
                  type="button"
                  onClick={() => onPin(card)}
                  className="inline-flex items-center gap-1 rounded-md border border-line-tertiary px-2.5 py-1 text-small font-medium text-ink-secondary transition-colors hover:border-line-secondary hover:bg-bg-tertiary"
                >
                  <IconPin size={14} />
                  Pin to Home
                </button>
              )}
              {onUnpin && pinned && (
                <button
                  type="button"
                  onClick={() => onUnpin(card)}
                  className="inline-flex items-center gap-1 rounded-md border border-line-tertiary px-2.5 py-1 text-small font-medium text-ink-secondary transition-colors hover:border-line-secondary hover:bg-bg-tertiary"
                >
                  <IconPinnedOff size={14} />
                  Unpin
                </button>
              )}
              {onAddToReport && (
                <button
                  type="button"
                  onClick={() => onAddToReport(card)}
                  className="inline-flex items-center gap-1 rounded-md border border-line-tertiary px-2.5 py-1 text-small font-medium text-ink-secondary transition-colors hover:border-line-secondary hover:bg-bg-tertiary"
                >
                  <IconPlus size={14} /> Add to report
                </button>
              )}
            </>
          )}
        </div>
      </footer>

      <InsightExplanationPanel
        card={card}
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
