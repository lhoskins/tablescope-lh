"use client";


import { useState, useEffect, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { WidgetConfig, WidgetType, ChartSubtype, WidgetFilter, ColumnInfo, VisualizationOptions, WidgetInteractions, WidgetClickAction, WidgetDateField } from "../types";
import type { QueryScope } from "@/types/query-scope";
import { WidgetRenderer } from "../WidgetRenderer";
import { ChartOptionsPanel } from "../ChartOptionsPanel";
import { getDefaultOptions, getChartDefinition } from "@/lib/visualizations/chartRegistry";

export const SORT_OPTIONS = [
  { value: "x_asc", label: "X ascending" },
  { value: "x_desc", label: "X descending" },
  { value: "y_desc", label: "Y descending" },
  { value: "y_asc", label: "Y ascending" },
];