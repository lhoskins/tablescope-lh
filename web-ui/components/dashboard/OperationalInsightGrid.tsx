"use client";

import { Card } from "@/components/ui/card";
import { WidgetRenderer } from "./WidgetRenderer";
import type { WidgetConfig, ChartClickEvent } from "./types";
// Shared operational-insight visual grammar (brief/KPI/chart grid layout) —
// built for the ITSM insight dashboards but purely structural CSS, no ITSM
// logic. Reused here so an AI-Designer-created dashboard of any domain
// renders with the same "ServiceNow style" the ITSM dashboards do, instead
// of the free-form widget grid every other dashboard uses.
import styles from "@/components/tablescope/project/itsm-dashboards/ItsmDashboardScreen.module.css";

interface OperationalNarrativeWidget {
  id?: string;
  type?: string;
  title?: string;
  summary?: string;
  items?: string[];
}

const BRIEF_LABELS = ["Risk", "Primary driver", "Recommended action"];
const BRIEF_DOT_CLASSES = ["bg-rose-500", "bg-amber-500", "bg-emerald-500"];

const EDIT_ICON = (
  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={2}
      d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
    />
  </svg>
);

function findNarrative(
  operationalWidgets: OperationalNarrativeWidget[],
  type: string,
): OperationalNarrativeWidget | undefined {
  return operationalWidgets.find((w) => w.type === type);
}

/**
 * Curated operational-insight layout: brief, KPI grid, a main chart + side
 * stack, then a bottom row pairing charts with Best Improvement
 * Opportunities — the same structure `ItsmInsightsDashboardContent` uses,
 * generalized to any AI-Designer-created dashboard's widgets rather than
 * the bespoke ITSM data source. Rendered instead of the free-form
 * react-grid-layout widget grid when the dashboard carries the narrative
 * `operationalWidgets` the AI Designer already persists at creation time.
 */
export function OperationalInsightGrid({
  widgets,
  widgetData,
  operationalWidgets,
  onEditWidget,
  onElementClick,
}: {
  widgets: WidgetConfig[];
  widgetData: Record<string, Array<Record<string, unknown>>>;
  operationalWidgets: OperationalNarrativeWidget[];
  onEditWidget: (widget: WidgetConfig) => void;
  onElementClick: (widget: WidgetConfig, event: ChartClickEvent) => void;
}) {
  const brief = findNarrative(operationalWidgets, "operational_brief");
  const improvements = findNarrative(operationalWidgets, "improvement_opportunities");

  const kpiWidgets = widgets.filter((w) => w.type === "kpi");
  const chartWidgets = widgets.filter((w) => w.type !== "kpi");
  const [mainChart, ...restCharts] = chartWidgets;
  const sideCharts = restCharts.slice(0, 2);
  const bottomCharts = restCharts.slice(2, 4);
  const overflowCharts = restCharts.slice(4);

  const chartCard = (widget: WidgetConfig, heightClass: string) => (
    <Card key={widget.id} className="overflow-hidden p-3">
      <div className="mb-1 flex items-start justify-between gap-3">
        <h3 className="truncate text-small font-semibold text-ink-primary">
          {widget.title || "Untitled"}
        </h3>
        <button
          type="button"
          onClick={() => onEditWidget(widget)}
          title="Modify with AI"
          className="shrink-0 rounded p-1 text-ink-tertiary transition-colors hover:bg-bg-secondary hover:text-ink-secondary"
        >
          {EDIT_ICON}
        </button>
      </div>
      <div className={heightClass}>
        <WidgetRenderer
          widget={widget}
          data={widgetData[widget.id] ?? []}
          operational
          onElementClick={(event) => onElementClick(widget, event)}
        />
      </div>
    </Card>
  );

  return (
    <div className={styles.dashboardContainer}>
      {brief && (
        <div className={styles.insightBrief}>
          <div>
            <div className="text-small font-semibold text-ink-primary">Operational brief</div>
            <div className="text-[11px] text-ink-tertiary">
              {brief.summary || "The story behind the selected period"}
            </div>
          </div>
          <div className={styles.insightBriefGrid}>
            {(brief.items ?? []).slice(0, 3).map((item, index) => (
              <div key={index} className="grid grid-cols-[auto_1fr] gap-2 text-left">
                <span
                  className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${BRIEF_DOT_CLASSES[index] ?? "bg-blue-500"}`}
                />
                <span>
                  <span className="block text-xs font-semibold text-ink-primary">
                    {BRIEF_LABELS[index] ?? "Insight"}
                  </span>
                  <span className="block text-[11px] leading-4 text-ink-tertiary">{item}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {kpiWidgets.length > 0 && (
        <div className={`${styles.kpiGrid} mt-3`}>
          {kpiWidgets.map((widget) => (
            <div key={widget.id} className={styles.cardStandard}>
              <Card className="h-full p-3">
                <div className="flex items-start justify-between gap-2">
                  <span className="truncate text-[11px] font-semibold uppercase tracking-[0.02em] text-ink-secondary">
                    {widget.title}
                  </span>
                  <button
                    type="button"
                    onClick={() => onEditWidget(widget)}
                    title="Modify with AI"
                    className="shrink-0 rounded p-0.5 text-ink-tertiary hover:bg-bg-secondary"
                  >
                    {EDIT_ICON}
                  </button>
                </div>
                <WidgetRenderer
                  widget={widget}
                  data={widgetData[widget.id] ?? []}
                  operational
                  onElementClick={(event) => onElementClick(widget, event)}
                />
              </Card>
            </div>
          ))}
        </div>
      )}

      {mainChart && (
        <div className={`${styles.insightMainGrid} mt-3`}>
          {chartCard(mainChart, "h-72")}
          <div className={styles.insightSideStack}>
            {sideCharts.map((widget) => chartCard(widget, "h-52"))}
          </div>
        </div>
      )}

      {(bottomCharts.length > 0 || improvements) && (
        <div className={`${styles.insightBottomGrid} mt-3`}>
          {bottomCharts.map((widget) => chartCard(widget, "h-56"))}
          {improvements && (
            <Card className="p-4">
              <div className="text-sm font-semibold text-ink-primary">
                {improvements.title || "Best improvement opportunities"}
              </div>
              <div className="mt-1 text-[11px] text-ink-tertiary">
                Prioritized by operational impact
              </div>
              <div className="mt-4 space-y-3">
                {(improvements.items ?? []).map((item, index) => (
                  <div
                    key={index}
                    className="flex items-start justify-between gap-3 border-b border-line-tertiary pb-3 text-left last:border-0"
                  >
                    <span className="block text-xs font-semibold text-ink-primary">
                      {index + 1}. {item}
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}

      {overflowCharts.length > 0 && (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {overflowCharts.map((widget) => chartCard(widget, "h-56"))}
        </div>
      )}
    </div>
  );
}
