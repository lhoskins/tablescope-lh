"use client";

import { useEffect, useMemo, useState } from "react";
import { useDebounce } from "@/lib/hooks/use-debounce";
import { cn } from "@/lib/cn";
import { InsightPanel, PanelEmpty } from "@/components/tablescope/insight-panel";
import { TimeSeriesIntervalRangeControls } from "@/components/tablescope/insights/time-series-interval-range-controls";
import { IconChartBar } from "@tabler/icons-react";
import { Switch } from "@/components/ui/switch";
import { usePercentChangeSummary } from "@/lib/hooks/use-percent-change-summary";
import type {
  PercentChangeSummarySort,
  TimeSeriesInterval,
  TimeSeriesRange,
} from "@/lib/api/home-intelligence";
import { PercentChangeSummaryTable } from "./percent-change-summary-table";

const SHOW_STATISTICS_STORAGE_KEY = "tablescope-pcs-show-statistics";

interface PercentChangeSummaryPanelProps {
  projectIds: number[];
  snapshotFingerprint?: string | null;
}

const EXCLUSION_REASON_LABELS: Record<string, string> = {
  not_time_series: "No validated time dimension",
  no_numeric_measure: "No numeric measure",
  insufficient_periods: "Insufficient periods",
  unsupported_source_grain: "Unsupported source grain for this interval",
  unavailable_source_chart_data: "Unavailable source chart data",
  duplicate_card: "Duplicate card suppressed",
};

export function PercentChangeSummaryPanel({
  projectIds,
  snapshotFingerprint,
}: PercentChangeSummaryPanelProps) {
  const [interval, setInterval] = useState<TimeSeriesInterval>("month");
  const [range, setRange] = useState<TimeSeriesRange>("1y");
  const [search, setSearch] = useState("");
  const [debouncedSearch] = useDebounce(search, 250);
  const [sort, setSort] = useState<PercentChangeSummarySort>({
    field: "latest_absolute_change",
    direction: "desc",
  });
  const [cursor, setCursor] = useState<string | null>(null);
  const [pageSize, setPageSize] = useState(25);
  const [showStatistics, setShowStatistics] = useState(false);

  useEffect(() => {
    try {
      setShowStatistics(window.localStorage.getItem(SHOW_STATISTICS_STORAGE_KEY) === "true");
    } catch {
      /* ignore */
    }
  }, []);

  const handleShowStatisticsChange = (next: boolean) => {
    setShowStatistics(next);
    try {
      window.localStorage.setItem(SHOW_STATISTICS_STORAGE_KEY, String(next));
    } catch {
      /* ignore */
    }
  };

  const requestSearch = debouncedSearch.trim();

  const { data, isLoading, isFetching, error, refetch } =
    usePercentChangeSummary({
      projectIds,
      interval,
      range,
      search: requestSearch,
      sort,
      cursor,
      pageSize,
      snapshotFingerprint: snapshotFingerprint ?? null,
      enabled: projectIds.length > 0,
    });

  useEffect(() => {
    setCursor(null);
  }, [projectIds, interval, range, requestSearch, sort, pageSize]);

  const supportCounts = useMemo(() => {
    return data?.interval_support_counts ?? {};
  }, [data]);

  const excludedDetails = useMemo(() => {
    if (!data || data.page.total_excluded === 0) return null;
    return Object.entries(data.excluded_by_reason).map(([reason, count]) => ({
      reason,
      label: EXCLUSION_REASON_LABELS[reason] || reason,
      count,
    }));
  }, [data]);

  const title = "Percent Change Summary";
  const count = data?.page.total_eligible ?? 0;

  const handlePageSize = (size: number) => {
    setPageSize(size);
    setCursor(null);
  };

  const renderContent = () => {
    if (projectIds.length === 0) {
      return <PanelEmpty text="Select one or more projects to view percent changes." />;
    }
    if (isLoading && !data) {
      return (
        <div className="space-y-3">
          <div className="h-8 animate-pulse rounded bg-bg-tertiary" />
          <div className="h-32 animate-pulse rounded bg-bg-tertiary" />
        </div>
      );
    }
    if (error) {
      return (
        <div className="rounded-md border border-error bg-error/5 p-3 text-[13px] text-error">
          <p>Could not load the percent change summary.</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="mt-2 rounded-md bg-error px-3 py-1 text-white hover:bg-error/90"
          >
            Try again
          </button>
        </div>
      );
    }
    if (!data || data.page.total_in_scope === 0) {
      return <PanelEmpty text="No insight cards are available for the selected projects." />;
    }
    if (data.page.total_eligible === 0) {
      return (
        <PanelEmpty text="No eligible time-series cards for the selected interval and range." />
      );
    }
    if (data.rows.length === 0 && requestSearch) {
      return <PanelEmpty text="No insights match your search." />;
    }

    return (
      <div className="space-y-3">
        <PercentChangeSummaryTable
          periods={data.periods}
          rows={data.rows}
          sort={sort}
          onSort={setSort}
          showStatistics={showStatistics}
        />
        {data.page.next_cursor && (
          <div className="flex items-center justify-between text-[13px]">
            <button
              type="button"
              disabled={!cursor}
              onClick={() => setCursor(null)}
              className="rounded-md px-2 py-1 text-ink-secondary hover:bg-bg-tertiary disabled:opacity-50"
            >
              Previous page
            </button>
            <button
              type="button"
              onClick={() => setCursor(data.page.next_cursor)}
              className="rounded-md px-2 py-1 text-ink-secondary hover:bg-bg-tertiary"
            >
              Next page
            </button>
          </div>
        )}
      </div>
    );
  };

  return (
    <InsightPanel
      title={title}
      icon={<IconChartBar size={16} className="text-brand-500" />}
      collapsible
      defaultOpen
      count={count}
    >
      <div className="space-y-3">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <TimeSeriesIntervalRangeControls
            interval={interval}
            range={range}
            supportCounts={supportCounts}
            comparisonLabel={data?.comparison_label}
            loading={isFetching}
            onIntervalChange={(iv) => {
              setInterval(iv);
              setCursor(null);
            }}
            onRangeChange={(r) => {
              setRange(r);
              setCursor(null);
            }}
          />
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <label htmlFor="pcs-search" className="sr-only">
                Search insights
              </label>
              <input
                id="pcs-search"
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search title or project"
                className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-1.5 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
              />
              <select
                aria-label="Rows per page"
                value={pageSize}
                onChange={(e) => handlePageSize(Number(e.target.value))}
                className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5 text-[13px] text-ink-primary"
              >
                <option value={25}>25</option>
                <option value={50}>50</option>
              </select>
            </div>
            <Switch
              id="pcs-show-statistics"
              checked={showStatistics}
              onChange={handleShowStatisticsChange}
              label="Show period statistics"
            />
          </div>
        </div>

        {data && (
          <div className="flex flex-wrap items-center gap-3 text-[11px] text-ink-tertiary">
            <span>
              <strong className="text-ink-primary">{data.page.total_in_scope}</strong> in scope
            </span>
            <span>
              <strong className="text-ink-primary">{data.page.total_eligible}</strong> eligible
            </span>
            <span>
              <strong className="text-ink-primary">{data.page.total_excluded}</strong> excluded
            </span>
            {excludedDetails && excludedDetails.length > 0 && (
              <details className="inline-block">
                <summary className="cursor-pointer text-brand-600 hover:text-brand-700">
                  Exclusion reasons
                </summary>
                <ul className="mt-1 list-disc pl-4">
                  {excludedDetails.map(({ reason, label, count }) => (
                    <li key={reason}>
                      {label}: {count}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}

        {renderContent()}
      </div>
    </InsightPanel>
  );
}
