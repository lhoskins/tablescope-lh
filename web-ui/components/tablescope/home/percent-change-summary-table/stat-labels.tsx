"use client";


import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { formatPercentChange } from "@/lib/insights/time-series";
import { insightAnchorId } from "@/lib/insights/return-target";
import type {
  PercentChangeSummaryCell,
  PercentChangeSummaryPeriod,
  PercentChangeSummaryRow,
  PercentChangeSummarySort,
  PercentChangeSummaryStatistics,
} from "@/lib/api/home-intelligence";
import {
  IconArrowUp,
  IconArrowDown,
  IconInfoCircle,
} from "@tabler/icons-react";


export const STAT_LABELS: Record<keyof PercentChangeSummaryStatistics, string> = {
  latest: "Latest",
  min: "Min",
  max: "Max",
  median: "Median",
  average: "Avg",
  standard_deviation: "Std Dev",
  cumulative_change: "Cumulative",
  valid_count: "n",
};