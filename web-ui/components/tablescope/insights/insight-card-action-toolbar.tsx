"use client";

import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  IconChartBar,
  IconChevronDown,
  IconChevronUp,
  IconClipboardPlus,
  IconDownload,
  IconFileSpreadsheet,
  IconFileText,
  IconInfoCircle,
  IconLayoutDashboard,
  IconLoader2,
  IconTable,
  IconThumbDown,
  IconThumbDownFilled,
  IconThumbUp,
  IconThumbUpFilled,
} from "@tabler/icons-react";
import type { SVGProps } from "react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import type { InsightCard, VizCandidate } from "@/lib/api/home-intelligence";
import type {
  InsightFeedbackRecord,
  InsightSentiment,
} from "@/lib/api/insight-feedback";

export interface InsightCardActionToolbarProps {
  card: InsightCard;
  actionsDisclosure?: "always-visible" | "collapsible";
  canCreateAction: boolean;
  onCreateAction?: () => void;
  onExplain?: () => void;
  onChartOptions?: () => void;
  onAddToDashboard?: () => void;
  onDownloadPng?: () => void;
  isPngExporting?: boolean;
  onExportCsv?: () => void;
  isCsvExporting?: boolean;
  feedback?: InsightFeedbackRecord | null;
  onFeedbackClick?: (sentiment: InsightSentiment) => void;
  feedbackStatus?: ReactNode;
  selectedChart?: VizCandidate | null;
}

function SourceTooltip({ sources }: { sources: string[] }) {
  if (sources.length === 0) return null;
  return (
    <ul className="list-disc space-y-0.5 pl-4">
      {sources.map((s) => (
        <li key={s}>{s}</li>
      ))}
    </ul>
  );
}

function InsightCardSourceRow({ card }: { card: InsightCard }) {
  const tables = card.sources?.tables ?? [];
  const documents = card.sources?.documents ?? [];
  const allSources = [...tables, ...documents];

  if (allSources.length === 0) {
    return (
      <div className="flex min-h-5 items-center gap-1 text-[12px] text-ink-tertiary">
        <IconDatabase size={13} />
        <span className="italic">No data sources</span>
      </div>
    );
  }

  const primary = allSources[0];
  const isTable = tables.includes(primary);
  const remaining = allSources.slice(1);

  return (
    <div className="flex min-h-5 items-center gap-1 text-[12px] text-ink-tertiary">
      <span className="inline-flex min-w-0 items-center gap-1">
        {isTable ? <IconTable size={13} /> : <IconFileText size={13} />}
        <span className="truncate" title={primary}>
          {primary}
        </span>
      </span>
      {remaining.length > 0 && (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className="shrink-0 rounded px-1 text-[11px] text-ink-tertiary hover:bg-bg-tertiary hover:text-ink-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
              aria-label={`${remaining.length} more source${remaining.length === 1 ? "" : "s"}`}
            >
              +{remaining.length} source{remaining.length === 1 ? "" : "s"}
            </button>
          </TooltipTrigger>
          <TooltipContent>
            <SourceTooltip sources={remaining} />
          </TooltipContent>
        </Tooltip>
      )}
    </div>
  );
}

function IconButton({
  label,
  tooltip,
  icon,
  onClick,
  disabled,
  active,
  busy,
  className,
  ariaPressed,
}: {
  label: string;
  tooltip?: string;
  icon: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  active?: boolean;
  busy?: boolean;
  className?: string;
  ariaPressed?: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onClick}
          disabled={disabled || busy}
          aria-label={label}
          aria-pressed={ariaPressed}
          aria-busy={busy}
          className={cn(
            "h-11 w-11 shrink-0 transition-colors focus-visible:ring-2 focus-visible:ring-brand-500",
            active
              ? "bg-brand-50 text-brand-700 hover:bg-brand-100"
              : "text-ink-tertiary hover:bg-bg-tertiary hover:text-ink-secondary",
            disabled && "opacity-50",
            className,
          )}
        >
          {busy ? <IconLoader2 size={18} className="animate-spin" /> : icon}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom">{tooltip ?? label}</TooltipContent>
    </Tooltip>
  );
}

function ToolbarDivider() {
  return (
    <div
      className="mx-1 h-6 w-px bg-line-tertiary"
      aria-hidden="true"
    />
  );
}

export function InsightCardActionToolbar({
  card,
  actionsDisclosure = "always-visible",
  canCreateAction,
  onCreateAction,
  onExplain,
  onChartOptions,
  onAddToDashboard,
  onDownloadPng,
  isPngExporting,
  onExportCsv,
  isCsvExporting,
  feedback,
  onFeedbackClick,
  feedbackStatus,
  selectedChart,
}: InsightCardActionToolbarProps) {
  const insightId = card.insightId || card.id;
  const regionId = useMemo(() => `insight-actions-${insightId}`, [insightId]);
  const [expanded, setExpandedState] = useState(actionsDisclosure === "always-visible");
  const toggleRef = useRef<HTMLButtonElement>(null);
  const regionRef = useRef<HTMLDivElement>(null);
  const returnFocus = useRef(false);

  useEffect(() => {
    if (actionsDisclosure === "always-visible") {
      setExpandedState(true);
    }
  }, [actionsDisclosure]);

  useEffect(() => {
    if (!expanded && returnFocus.current && toggleRef.current) {
      returnFocus.current = false;
      toggleRef.current.focus();
    }
  }, [expanded]);

  const setExpanded = (next: boolean) => {
    if (!next && regionRef.current?.contains(document.activeElement)) {
      returnFocus.current = true;
    }
    setExpandedState(next);
  };

  const toggleExpanded = () => setExpanded(!expanded);

  const hasChart = card.chart != null;
  const isKpiGrid = card.chart?.type === "kpi_grid";

  const canChangeChart = hasChart && !isKpiGrid;
  const chartDisabledReason = isKpiGrid
    ? "Chart options are not available for KPI grid cards"
    : !hasChart
      ? "No chart available for this insight"
      : undefined;

  const canAddToDashboard = Boolean(
    onAddToDashboard && card.sql?.trim() && card.valueColumn?.trim(),
  );
  const dashboardDisabledReason = !onAddToDashboard
    ? "Dashboard placement is not available here"
    : !card.sql?.trim()
      ? "This insight does not have a query to place on a dashboard"
      : !card.valueColumn?.trim()
        ? "This insight does not have a value column and cannot be added to a dashboard"
        : undefined;

  const canExportCsv = Boolean(onExportCsv);
  const csvDisabledReason = !onExportCsv
    ? "CSV export is not available for this insight"
    : undefined;

  const agreeSelected =
    feedback?.sentiment === "agree" && feedback?.status === "active";
  const disagreeSelected =
    feedback?.sentiment === "disagree" && feedback?.status === "active";

  const showDisclosure = actionsDisclosure === "collapsible";

  return (
    <TooltipProvider delayDuration={300}>
      <div className="mt-3">
        {showDisclosure && (
          <button
            ref={toggleRef}
            type="button"
            aria-expanded={expanded}
            aria-controls={regionId}
            onClick={toggleExpanded}
            className="inline-flex h-11 items-center gap-1 rounded-md px-3 text-[13px] font-medium text-ink-tertiary transition-colors hover:bg-bg-secondary hover:text-ink-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
          >
            More Actions
            {expanded ? (
              <IconChevronUp size={16} aria-hidden />
            ) : (
              <IconChevronDown size={16} aria-hidden />
            )}
          </button>
        )}

        {(!showDisclosure || expanded) && (
          <div
            ref={regionRef}
            id={regionId}
            className={cn(
              "space-y-2 border-t border-line-tertiary pt-3",
              showDisclosure && "mt-2",
            )}
          >
            <InsightCardSourceRow card={card} />

            <div
              className="flex flex-wrap items-center gap-1"
              data-export-hide
            >
              <IconButton
                label="Create Action"
                tooltip={
                  canCreateAction
                    ? "Create Action"
                    : "You do not have permission to create actions"
                }
                icon={<IconClipboardPlus size={18} />}
                onClick={onCreateAction}
                disabled={!canCreateAction || !onCreateAction}
              />

              <IconButton
                label="Explain"
                icon={<IconInfoCircle size={18} />}
                onClick={onExplain}
                disabled={!onExplain}
              />

              <ToolbarDivider />

              {onFeedbackClick && (
                <>
                  <IconButton
                    label={agreeSelected ? "Edit Agree" : "Agree"}
                    tooltip="Agree"
                    icon={
                      agreeSelected ? (
                        <IconThumbUpFilled size={18} />
                      ) : (
                        <IconThumbUp size={18} />
                      )
                    }
                    onClick={() => onFeedbackClick("agree")}
                    active={agreeSelected}
                    ariaPressed={agreeSelected}
                    className={
                      agreeSelected ? "text-success hover:bg-success/10" : undefined
                    }
                  />
                  <IconButton
                    label={disagreeSelected ? "Edit Disagree" : "Disagree"}
                    tooltip="Disagree"
                    icon={
                      disagreeSelected ? (
                        <IconThumbDownFilled size={18} />
                      ) : (
                        <IconThumbDown size={18} />
                      )
                    }
                    onClick={() => onFeedbackClick("disagree")}
                    active={disagreeSelected}
                    ariaPressed={disagreeSelected}
                    className={
                      disagreeSelected ? "text-danger hover:bg-danger/10" : undefined
                    }
                  />
                </>
              )}

              {feedbackStatus}

              {canChangeChart ? (
                <IconButton
                  label="Chart options"
                  icon={<IconChartBar size={18} />}
                  onClick={onChartOptions}
                  active={selectedChart != null}
                />
              ) : (
                <IconButton
                  label="Chart options"
                  tooltip={chartDisabledReason}
                  icon={<IconChartBar size={18} />}
                  disabled
                />
              )}

              <ToolbarDivider />

              {canAddToDashboard ? (
                <IconButton
                  label="Add to dashboard"
                  icon={<IconLayoutDashboard size={18} />}
                  onClick={onAddToDashboard}
                />
              ) : (
                <IconButton
                  label="Add to dashboard"
                  tooltip={dashboardDisabledReason}
                  icon={<IconLayoutDashboard size={18} />}
                  disabled
                />
              )}

              <IconButton
                label={isPngExporting ? "Downloading PNG" : "Download PNG"}
                tooltip="Download PNG"
                icon={<IconDownload size={18} />}
                onClick={onDownloadPng}
                busy={isPngExporting}
                disabled={isPngExporting}
              />

              {canExportCsv ? (
                <IconButton
                  label={isCsvExporting ? "Exporting CSV" : "Export to CSV"}
                  tooltip="Export to CSV"
                  icon={<IconFileSpreadsheet size={18} />}
                  onClick={onExportCsv}
                  busy={isCsvExporting}
                  disabled={isCsvExporting}
                />
              ) : (
                <IconButton
                  label="Export to CSV"
                  tooltip={csvDisabledReason}
                  icon={<IconFileSpreadsheet size={18} />}
                  disabled
                />
              )}
            </div>
          </div>
        )}
      </div>
    </TooltipProvider>
  );
}

function IconDatabase({ size = 24, ...props }: SVGProps<SVGSVGElement> & { size?: number }) {
  return (
    <svg
      {...props}
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M3 5v14a9 3 0 0 0 18 0V5" />
      <path d="M3 12a9 3 0 0 0 18 0" />
    </svg>
  );
}
