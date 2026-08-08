"use client";


import { useState, useEffect, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { WidgetConfig, WidgetType, ChartSubtype, WidgetFilter, ColumnInfo, VisualizationOptions, WidgetInteractions, WidgetClickAction, WidgetDateField } from "../types";
import type { QueryScope } from "@/types/query-scope";
import { WidgetRenderer } from "../WidgetRenderer";
import { ChartOptionsPanel } from "../ChartOptionsPanel";
import { getDefaultOptions, getChartDefinition } from "@/lib/visualizations/chartRegistry";import { SavedQuery } from "./saved-query";
import { Datasource } from "./datasource";



export type Props = {
  projectId: number;
  savedQueries: SavedQuery[];
  datasources: Datasource[];
  editingWidget?: WidgetConfig | null;
  onSave: (widget: WidgetConfig) => void;
  onCancel: () => void;
};