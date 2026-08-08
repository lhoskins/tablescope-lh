"use client";


import { useState, useEffect, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { WidgetConfig, WidgetType, ChartSubtype, WidgetFilter, ColumnInfo, VisualizationOptions, WidgetInteractions, WidgetClickAction, WidgetDateField } from "../types";
import type { QueryScope } from "@/types/query-scope";
import { WidgetRenderer } from "../WidgetRenderer";
import { ChartOptionsPanel } from "../ChartOptionsPanel";
import { getDefaultOptions, getChartDefinition } from "@/lib/visualizations/chartRegistry";


export const CLICK_ACTIONS: { value: WidgetClickAction; label: string }[] = [
  { value: "none", label: "None" },
  { value: "cross_filter", label: "Filter dashboard" },
  { value: "drilldown", label: "Drill down to details" },
  { value: "drilldown_and_filter", label: "Filter + show details" },
];