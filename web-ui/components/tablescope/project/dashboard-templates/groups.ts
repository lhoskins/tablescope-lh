import type { Dashboard } from "@/lib/ui/use-project-data";
import {
  dashboardDefinitionForItsmPreset,
  templateForItsmPreset,
} from "./registry";
import type {
  DashboardGroup,
  DashboardTemplateIcon,
  DashboardTemplateMetadata,
  DashboardTemplateParameters,
  DashboardGroupRecord,
} from "./types";
import { templateMetadataOf } from "./types";

const NAME_ICON_RULES: Array<[RegExp, DashboardTemplateIcon]> = [
  [/incident|risk|problem/i, "alert"],
  [/request|fulfill|recruit/i, "request"],
  [/availability|reliability|uptime/i, "availability"],
  [/service desk|productivity|support/i, "headset"],
  [/finance|budget|cash|margin|profit/i, "finance"],
  [/manufactur|production|plant|oee|downtime/i, "manufacturing"],
  [/quality|yield|defect/i, "quality"],
  [/sales|pipeline|forecast|account/i, "sales"],
  [/workforce|employee|retention|turnover|skills|hr/i, "hr"],
];

export function dashboardIcon(dashboard: Dashboard): DashboardTemplateIcon {
  const metadata = templateMetadataOf(dashboard);
  if (metadata?.dashboardIcon) return metadata.dashboardIcon;
  return NAME_ICON_RULES.find(([pattern]) => pattern.test(dashboard.name))?.[1] ?? "activity";
}

export function virtualItsmDashboardConfig(preset: string): Record<string, unknown> {
  const template = templateForItsmPreset(preset);
  const definition = dashboardDefinitionForItsmPreset(preset);
  if (!template || !definition) return { itsm_dashboard: preset };
  const parameters: DashboardTemplateParameters = {
    dimensionLabel: template.defaultDimensionLabel,
    dimensionField: "site",
    valueSource: "query",
    queryName: "ServiceNow active sites",
    defaultPeriod: template.defaultPeriod,
  };
  const metadata: DashboardTemplateMetadata = {
    schemaVersion: 1,
    presentation: "operational_insight",
    templateId: template.id,
    templateName: template.name,
    groupId: template.id,
    groupName: template.name,
    groupIcon: template.icon,
    dashboardKey: definition.key,
    dashboardIcon: definition.icon,
    parameters,
  };
  return {
    itsm_dashboard: preset,
    presentation: "operational_insight",
    dashboardTemplate: metadata,
  };
}

export function groupDashboards(rows: Dashboard[], persisted: DashboardGroupRecord[] = []): DashboardGroup[] {
  const groups = new Map<string, DashboardGroup>();
  const persistedByDashboard = new Map<number, DashboardGroupRecord>();
  for (const record of persisted) {
    groups.set(`group:${record.id}`, { id: `group:${record.id}`, persistentId: record.id, name: record.name, icon: record.icon, templateId: record.templateId, dashboards: [], collapsedDefault: record.collapsedDefault });
    record.dashboardIds.forEach((dashboardId) => persistedByDashboard.set(dashboardId, record));
  }
  for (const dashboard of rows) {
    const metadata = templateMetadataOf(dashboard);
    const record = persistedByDashboard.get(dashboard.id);
    const configuredId = typeof dashboard.config?.dashboardGroupId === "number" ? dashboard.config.dashboardGroupId : undefined;
    const id = record ? `group:${record.id}` : configuredId ? `group:${configuredId}` : metadata?.groupId ?? "custom-dashboards";
    const current = groups.get(id) ?? {
      id,
      persistentId: record?.id ?? configuredId,
      name: record?.name ?? metadata?.groupName ?? "Custom dashboards",
      icon: record?.icon ?? metadata?.groupIcon ?? metadata?.dashboardIcon ?? "activity",
      templateId: record?.templateId ?? metadata?.templateId,
      dashboards: [],
      collapsedDefault: true,
    };
    current.dashboards.push(dashboard);
    groups.set(id, current);
  }
  return [...groups.values()].sort((left, right) => {
    if (left.id === "servicenow-itsm-operations") return -1;
    if (right.id === "servicenow-itsm-operations") return 1;
    if (left.id === "servicenow-kpi-board") return -1;
    if (right.id === "servicenow-kpi-board") return 1;
    if (left.id === "custom-dashboards") return 1;
    if (right.id === "custom-dashboards") return -1;
    return left.name.localeCompare(right.name);
  });
}
