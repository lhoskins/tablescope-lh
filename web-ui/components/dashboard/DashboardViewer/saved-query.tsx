"use client";


import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { useMutation, useQuery, useQueries, useQueryClient } from "@tanstack/react-query";
import {
  ResponsiveGridLayout,
  useContainerWidth,
  type EventCallback,
  type Layout,
  type LayoutItem,
  type ResponsiveLayouts,
} from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import {
  GRID_BREAKPOINTS,
  GRID_COLS,
  GRID_CONTAINER_PADDING,
  GRID_DRAG_CONFIG,
  GRID_MARGIN,
  GRID_RESIZE_CONFIG,
  GRID_ROW_HEIGHT,
} from "@/lib/ui/grid-layout";
import { apiClient } from "@/lib/api-client";
import type {
  Dashboard,
  WidgetConfig,
  DashboardConfig,
  DashboardFilter,
  ColumnInfo,
  WidgetFilter,
  DashboardRuntimeState,
  DashboardDateRange,
  ChartClickEvent,
  CrossFilter,
} from "../types";
import type { QueryScope, QueryScopeFilterResponse } from "@/types/query-scope";
import { WidgetRenderer } from "../WidgetRenderer";
import { WidgetConfigPanel } from "../WidgetConfigPanel";
import { FilterBar } from "../FilterBar";
import { DateRangeControl } from "../DateRangeControl";
import { DrilldownPanel, type DrilldownState } from "../DrilldownPanel";
import { buildRuntimeWidgetFilters } from "@/lib/dashboard/runtimeFilters";


export type SavedQuery = { id: number; name: string; sql_text: string | null };