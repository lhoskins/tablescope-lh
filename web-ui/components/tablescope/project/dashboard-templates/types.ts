import type { Dashboard } from "@/lib/ui/use-project-data";

export type DashboardTemplateCategory =
  | "itsm"
  | "finance"
  | "manufacturing"
  | "sales"
  | "hr";

export type DashboardTemplateIcon =
  | "activity"
  | "alert"
  | "availability"
  | "finance"
  | "gauge"
  | "headset"
  | "hr"
  | "manufacturing"
  | "quality"
  | "request"
  | "sales"
  | "trend";

export interface DashboardTemplateDashboard {
  key: string;
  name: string;
  description: string;
  icon: DashboardTemplateIcon;
  audience: "executive" | "manager" | "operational";
  aiPrompt: string;
  itsmPreset?: string;
}

export interface DashboardTemplateDefinition {
  id: string;
  category: DashboardTemplateCategory;
  name: string;
  description: string;
  icon: DashboardTemplateIcon;
  recommended?: boolean;
  defaultDimensionLabel: string;
  defaultPeriod: string;
  dashboards: DashboardTemplateDashboard[];
}

export interface DashboardTemplateParameters {
  dimensionLabel: string;
  dimensionField?: string;
  valueSource: "query" | "manual";
  queryId?: number;
  queryName?: string;
  manualValues?: string[];
  defaultPeriod: string;
}

export interface DashboardTemplateMetadata {
  schemaVersion: 1;
  presentation: "operational_insight";
  templateId: string;
  templateName: string;
  groupId: string;
  groupName: string;
  groupIcon: DashboardTemplateIcon;
  dashboardKey: string;
  dashboardIcon: DashboardTemplateIcon;
  parameters: DashboardTemplateParameters;
  bindingId?: number;
  dashboardGroupId?: number;
}

export interface OperationalInsightWidgetConfig {
  id: string;
  type: "operational_brief" | "improvement_opportunities";
  title: string;
  editable: boolean;
  aiManaged: boolean;
  prompt: string;
  summary?: string;
  items?: Array<string | { label?: string; detail?: string; tone?: "critical" | "warning" | "positive" | "neutral" }>;
  updatedAt?: string;
  layout?: {
    position: number;
    width: "standard" | "wide";
    gridX?: number;
    gridY?: number;
    gridW?: number;
    gridH?: number;
  };
}

export interface TemplateBindingDraft {
  metricManifest: Array<Record<string, unknown>>;
  sourceMapping: Record<string, string>;
  fieldMapping: Record<string, Record<string, string>>;
  dimensionConfig: { label: string; field: string; valueSource: "query" | "manual" };
  validation: { valid: boolean; errors: string[]; warnings?: string[] };
}

export interface DashboardGroupRecord {
  id: number;
  name: string;
  slug: string;
  icon: DashboardTemplateIcon;
  templateId?: string;
  collapsedDefault: boolean;
  dashboardIds: number[];
}

export interface DashboardGroup {
  id: string;
  persistentId?: number;
  name: string;
  icon: DashboardTemplateIcon;
  templateId?: string;
  dashboards: Dashboard[];
  collapsedDefault?: boolean;
}

export function templateMetadataOf(dashboard: Dashboard): DashboardTemplateMetadata | undefined {
  const value = dashboard.config?.dashboardTemplate;
  if (!value || typeof value !== "object") return undefined;
  const metadata = value as Partial<DashboardTemplateMetadata>;
  if (!metadata.groupId || !metadata.groupName || !metadata.dashboardKey) return undefined;
  return metadata as DashboardTemplateMetadata;
}

export function operationalWidgetsOf(dashboard: Dashboard): OperationalInsightWidgetConfig[] {
  const value = dashboard.config?.operationalWidgets;
  return Array.isArray(value) ? (value as OperationalInsightWidgetConfig[]) : [];
}
