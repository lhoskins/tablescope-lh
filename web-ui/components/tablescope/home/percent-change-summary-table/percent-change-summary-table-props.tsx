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


export interface PercentChangeSummaryTableProps {
  periods: PercentChangeSummaryPeriod[];
  rows: PercentChangeSummaryRow[];
  sort: PercentChangeSummarySort;
  onSort: (sort: PercentChangeSummarySort) => void;
  showStatistics?: boolean;
}