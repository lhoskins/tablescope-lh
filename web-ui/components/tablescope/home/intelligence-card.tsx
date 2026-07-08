"use client";

import { Fragment, type ReactNode } from "react";
import {
  IconAlertTriangle,
  IconBulb,
  IconChevronRight,
  IconFileText,
  IconPlus,
  IconTable,
} from "@tabler/icons-react";
import { WidgetRenderer } from "@/components/dashboard/WidgetRenderer";
import type { WidgetConfig, WidgetType } from "@/components/dashboard/types";
import type {
  InsightCard as InsightCardData,
  InsightChart,
  InsightSeverity,
} from "@/lib/api/home-intelligence";

/** Render a string with `**bold**` markers as bold spans. */
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
    return <Fragment key={i}>{part}</Fragment>;
  });
}

const SEVERITY: Record<
  InsightSeverity,
  { accent: string; label: string; chip: string }
> = {
  critical: {
    accent: "border-l-danger",
    label: "Critical",
    chip: "bg-danger/10 text-danger",
  },
  urgent: {
    accent: "border-l-warning",
    label: "Urgent",
    chip: "bg-warning/10 text-warning",
  },
  warning: {
    accent: "border-l-warning",
    label: "Warning",
    chip: "bg-warning/10 text-warning",
  },
  watch: {
    accent: "border-l-line-secondary",
    label: "Watch",
    chip: "bg-bg-tertiary text-ink-secondary",
  },
  opportunity: {
    accent: "border-l-success",
    label: "Opportunity",
    chip: "bg-success/10 text-success",
  },
  info: {
    accent: "border-l-line-secondary",
    label: "Info",
    chip: "bg-bg-tertiary text-ink-secondary",
  },
};

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
  /** Hide the "Add to report" action (e.g. inside the report viewer). */
  hideActions?: boolean;
  onAddToReport?: (card: InsightCardData) => void;
}

export function IntelligenceCard({
  card,
  hideActions,
  onAddToReport,
}: IntelligenceCardProps) {
  const sev = SEVERITY[card.severity] ?? SEVERITY.info;
  const tables = card.sources?.tables ?? [];
  const documents = card.sources?.documents ?? [];

  return (
    <article
      className={`rounded-lg border border-line-tertiary border-l-[3px] ${sev.accent} bg-bg-primary p-4`}
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
          <h3 className="mt-1 text-h3 text-ink-primary">{card.title}</h3>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-small font-medium ${sev.chip}`}
        >
          {sev.label}
        </span>
      </header>

      <p className="mt-2 text-body text-ink-secondary">
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
          {card.callout.type === "opportunity" ? (
            <IconBulb size={16} className="mt-0.5 shrink-0" />
          ) : (
            <IconAlertTriangle size={16} className="mt-0.5 shrink-0" />
          )}
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
        {!hideActions && (
          <button
            type="button"
            onClick={() => onAddToReport?.(card)}
            className="inline-flex items-center gap-1 rounded-md border border-line-tertiary px-2.5 py-1 text-small font-medium text-ink-secondary transition-colors hover:border-line-secondary hover:bg-bg-tertiary"
          >
            <IconPlus size={14} /> Add to report
          </button>
        )}
      </footer>
    </article>
  );
}

export function LoadingCard({ projectName }: { projectName: string }) {
  return (
    <div className="rounded-lg border border-line-tertiary bg-bg-primary p-4">
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
