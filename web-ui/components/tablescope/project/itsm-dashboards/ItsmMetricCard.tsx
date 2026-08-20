"use client";

import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import type { ItsmCardSize, ItsmMetricValue } from "./types";

export interface ItsmMetricCardProps {
  metric: ItsmMetricValue;
  size: ItsmCardSize;
  editing?: boolean;
  onClick?: (metric: ItsmMetricValue) => void;
  onResize?: (metricKey: string) => void;
  onDragStart?: (metricKey: string) => void;
  onDrop?: (metricKey: string) => void;
}

export function ItsmMetricCard({
  metric,
  size,
  editing = false,
  onClick,
  onResize,
  onDragStart,
  onDrop,
}: ItsmMetricCardProps) {
  const isPositive = metric.outcome === "favorable";
  const isNegative = metric.outcome === "unfavorable";

  return (
    <Card
      draggable={editing}
      onDragStart={() => onDragStart?.(metric.metricKey)}
      onDragOver={(event) => editing && event.preventDefault()}
      onDrop={(event) => {
        if (!editing) return;
        event.preventDefault();
        onDrop?.(metric.metricKey);
      }}
      onClick={() => !editing && onClick?.(metric)}
      className={cn(
        "group flex min-h-[96px] flex-col justify-between p-3 transition-all",
        !editing && onClick && "cursor-pointer hover:-translate-y-0.5 hover:shadow-sm",
        editing && "cursor-grab border-dashed ring-1 ring-brand-100 active:cursor-grabbing",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="truncate text-[11px] font-semibold uppercase tracking-[0.02em] text-ink-secondary">
          {metric.label}
        </span>
        <div className="flex items-center gap-1">
          {metric.status !== "measured" && (
            <Badge tone="neutral" size="sm" className="capitalize">
              {metric.status}
            </Badge>
          )}
          {editing && (
            <button
              type="button"
              className="rounded border border-line-secondary bg-bg-primary px-1.5 py-0.5 text-[10px] text-ink-secondary hover:bg-bg-secondary"
              onClick={(event) => {
                event.stopPropagation();
                onResize?.(metric.metricKey);
              }}
              aria-label={`Resize ${metric.label}; current size ${size}`}
              title="Cycle card size"
            >
              {size === "compact" ? "1×" : size === "standard" ? "1.3×" : "2×"}
            </button>
          )}
        </div>
      </div>
      <div className="mt-1.5">
        <div className="text-xl font-semibold leading-none text-ink-primary">{metric.displayValue}</div>
        {metric.comparisonLabel && (
          <div
            className={cn(
              "mt-1.5 truncate text-[11px] font-semibold",
              isPositive && "text-emerald-600",
              isNegative && "text-rose-600",
              !isPositive && !isNegative && "text-slate-500",
            )}
          >
            {metric.comparisonLabel}
          </div>
        )}
      </div>
    </Card>
  );
}

