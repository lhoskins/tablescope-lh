"use client";

import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import type { ItsmMetricValue } from "./types";

export interface ItsmMetricCardProps {
  metric: ItsmMetricValue;
  onClick?: (metric: ItsmMetricValue) => void;
}

export function ItsmMetricCard({ metric, onClick }: ItsmMetricCardProps) {
  const isPositive = metric.outcome === "favorable";
  const isNegative = metric.outcome === "unfavorable";

  return (
    <Card
      onClick={() => onClick?.(metric)}
      className={cn(
        "flex flex-col justify-between p-4 transition-shadow hover:shadow-sm",
        onClick && "cursor-pointer",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium text-ink-secondary">{metric.label}</span>
        {metric.status !== "measured" && (
          <Badge tone="neutral" size="sm" className="capitalize">
            {metric.status}
          </Badge>
        )}
      </div>
      <div className="mt-3">
        <div className="text-2xl font-semibold text-ink-primary">{metric.displayValue}</div>
        {metric.comparisonLabel && (
          <div
            className={cn(
              "mt-1 flex items-center gap-1 text-xs font-medium",
              isPositive && "text-emerald-600",
              isNegative && "text-rose-600",
              !isPositive && !isNegative && "text-slate-500",
            )}
          >
            <span>{metric.comparisonLabel}</span>
          </div>
        )}
      </div>
    </Card>
  );
}
