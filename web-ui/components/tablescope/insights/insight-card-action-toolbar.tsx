"use client";

import type { ReactNode } from "react";
import {
  IconChartBar,
  IconClipboardList,
  IconDownload,
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
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import type { InsightCard, VizCandidate } from "@/lib/api/home-intelligence";
import type { InsightFeedbackRecord, InsightSentiment } from "@/lib/api/insight-feedback";

export interface InsightCardActionToolbarProps {
  card: InsightCard;
  canCreateAction: boolean;
  onCreateAction?: () => void;
  onExplain?: () => void;
  onChartOptions?: () => void;
  onAddToDashboard?: () => void;
  onDownloadPng?: () => void;
  isPngExporting?: boolean;
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
      <TooltipContent>{tooltip ?? label}</TooltipContent>
    </Tooltip>
  );
}

export function InsightCardActionToolbar({
  card,
  canCreateAction,
  onCreateAction,
  onExplain,
  onChartOptions,
  onAddToDashboard,
  onDownloadPng,
  isPngExporting,
  feedback,
  onFeedbackClick,
  feedbackStatus,
  selectedChart,
}: InsightCardActionToolbarProps) {
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

  const agreeSelected = feedback?.sentiment === "agree" && feedback?.status === "active";
  const disagreeSelected = feedback?.sentiment === "disagree" && feedback?.status === "active";

  return (
    <TooltipProvider delayDuration={300}>
      <div className="mt-3 space-y-2 border-t border-line-tertiary pt-3">
        <InsightCardSourceRow card={card} />

        <div className="flex flex-wrap items-center gap-2" data-export-hide>
        {canCreateAction && onCreateAction && (
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={onCreateAction}
            className="gap-1.5"
          >
            <IconClipboardList size={16} />
            Create action
          </Button>
        )}

        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={onExplain}
          className="gap-1.5"
        >
          <IconInfoCircle size={16} />
          Explain
        </Button>

        <div className="grow" aria-hidden="true" />

        {onFeedbackClick && (
          <>
            <IconButton
              label={agreeSelected ? "Edit helpful feedback" : "Helpful"}
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
              className={agreeSelected ? "text-success hover:bg-success/10" : undefined}
            />
            <IconButton
              label={disagreeSelected ? "Edit not helpful feedback" : "Not helpful"}
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
              className={disagreeSelected ? "text-danger hover:bg-danger/10" : undefined}
            />
            {feedbackStatus}
          </>
        )}

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

        <div
          className="mx-1 h-6 w-px bg-line-tertiary"
          aria-hidden="true"
        />

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
          icon={<IconDownload size={18} />}
          onClick={onDownloadPng}
          busy={isPngExporting}
          disabled={isPngExporting}
        />
      </div>
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
