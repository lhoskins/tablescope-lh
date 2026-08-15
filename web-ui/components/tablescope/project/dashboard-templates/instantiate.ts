import { apiClient } from "@/lib/api-client";
import type { Dashboard } from "@/lib/ui/use-project-data";
import type {
  DashboardTemplateDefinition,
  DashboardTemplateMetadata,
  DashboardTemplateParameters,
  OperationalInsightWidgetConfig,
} from "./types";

interface SuggestionWidget {
  title?: string;
  businessQuestion?: string;
  sql?: string;
}

interface DashboardSuggestion {
  id: string;
  title: string;
  description?: string;
  businessPurpose?: string;
  audience?: string;
  widgets?: SuggestionWidget[];
  kpis?: string[];
  dataSources?: string[];
  knowledgeGraphContext?: {
    opportunities?: string[];
    gaps?: string[];
    risks?: string[];
  };
  savePayload?: Record<string, unknown>;
}

interface SuggestionResponse {
  suggestions: DashboardSuggestion[];
}

interface SaveSuggestionResponse {
  dashboard_id: number;
}

export interface InstantiateTemplateRequest {
  projectId: string;
  template: DashboardTemplateDefinition;
  groupName: string;
  parameters: DashboardTemplateParameters;
  onProgress?: (completed: number, total: number, dashboardName: string) => void;
}

function parameterPrompt(parameters: DashboardTemplateParameters): string {
  const values = parameters.valueSource === "manual"
    ? `Available ${parameters.dimensionLabel} values: ${(parameters.manualValues ?? []).join(", ")}.`
    : `Use query "${parameters.queryName ?? parameters.queryId ?? "selected query"}" to supply ${parameters.dimensionLabel} values.`;
  return `${values} Default reporting period: ${parameters.defaultPeriod.replaceAll("_", " ")}.`;
}

function operationalWidgets(
  dashboardName: string,
  prompt: string,
  suggestion: DashboardSuggestion,
): OperationalInsightWidgetConfig[] {
  const context = suggestion.knowledgeGraphContext;
  const opportunities = [
    ...(context?.opportunities ?? []),
    ...(context?.gaps ?? []),
    ...(suggestion.widgets ?? []).map((widget) => widget.businessQuestion || widget.title || ""),
  ].filter(Boolean).slice(0, 5);
  const now = new Date().toISOString();
  return [
    {
      id: "operational-brief",
      type: "operational_brief",
      title: "Operational Brief",
      editable: true,
      aiManaged: true,
      prompt: `Refresh the operational brief for ${dashboardName}. ${prompt}`,
      summary: suggestion.businessPurpose || suggestion.description || `Operational view of ${dashboardName}.`,
      items: context?.risks?.slice(0, 3) ?? [],
      updatedAt: now,
    },
    {
      id: "improvement-opportunities",
      type: "improvement_opportunities",
      title: "Best Improvement Opportunities",
      editable: true,
      aiManaged: true,
      prompt: `Refresh and prioritize improvement opportunities for ${dashboardName}. ${prompt}`,
      items: opportunities.length ? opportunities : ["Analyze the latest governed data to identify the highest-impact opportunity."],
      updatedAt: now,
    },
  ];
}

async function generateDashboard(
  request: InstantiateTemplateRequest,
  dashboardIndex: number,
): Promise<number> {
  const definition = request.template.dashboards[dashboardIndex];
  const prompt = [
    definition.aiPrompt,
    `Create exactly the "${definition.name}" dashboard as part of the "${request.groupName}" collection.`,
    "Use the Tablescope Operational Insight presentation: compact KPI cards with real prior-period comparisons, appropriate ECharts, drilldown-ready dimensions, an Operational Brief, and Best Improvement Opportunities.",
    "Ground every metric and query in this project's available data. Do not invent columns or unsupported KPIs.",
    parameterPrompt(request.parameters),
  ].join(" ");
  const suggestions = await apiClient.post<SuggestionResponse>(
    "/api/ai/actions/suggest-dashboards",
    {
      project_id: Number(request.projectId),
      prompt,
      audience: definition.audience,
      desired_count: 3,
    },
  );
  const suggestion = suggestions.suggestions?.[0];
  if (!suggestion) throw new Error(`AI could not build ${definition.name} from the available project data.`);
  const saved = await apiClient.post<SaveSuggestionResponse>(
    "/api/ai/actions/save-dashboard-suggestion",
    {
      project_id: Number(request.projectId),
      suggestionId: suggestion.id,
      suggestion: suggestion.savePayload ?? suggestion,
    },
  );
  if (!saved.dashboard_id) throw new Error(`AI did not return a saved dashboard for ${definition.name}.`);
  const dashboard = await apiClient.get<Dashboard>(
    `/api/projects/${request.projectId}/dashboards/${saved.dashboard_id}`,
  );
  const metadata: DashboardTemplateMetadata = {
    schemaVersion: 1,
    presentation: "operational_insight",
    templateId: request.template.id,
    templateName: request.template.name,
    groupId: `${request.template.id}:${request.groupName.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
    groupName: request.groupName,
    groupIcon: request.template.icon,
    dashboardKey: definition.key,
    dashboardIcon: definition.icon,
    parameters: request.parameters,
  };
  await apiClient.put(`/api/projects/${request.projectId}/dashboards/${saved.dashboard_id}`, {
    name: definition.name,
    description: definition.description,
    status: "published",
    ai_generated: true,
    config: {
      ...dashboard.config,
      presentation: "operational_insight",
      dashboardTemplate: metadata,
      operationalWidgets: operationalWidgets(definition.name, prompt, suggestion),
    },
  });
  return saved.dashboard_id;
}

export async function instantiateDashboardTemplate(
  request: InstantiateTemplateRequest,
): Promise<number[]> {
  if (request.template.dashboards.some((dashboard) => dashboard.itsmPreset)) {
    throw new Error("This ServiceNow template is already available in the current project.");
  }
  const created: number[] = [];
  try {
    for (let index = 0; index < request.template.dashboards.length; index += 1) {
      const id = await generateDashboard(request, index);
      created.push(id);
      request.onProgress?.(index + 1, request.template.dashboards.length, request.template.dashboards[index].name);
    }
    return created;
  } catch (error) {
    await Promise.allSettled(
      created.map((id) => apiClient.delete(`/api/projects/${request.projectId}/dashboards/${id}`)),
    );
    throw error;
  }
}
