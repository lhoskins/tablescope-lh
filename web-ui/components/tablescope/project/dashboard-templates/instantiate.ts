import { apiClient } from "@/lib/api-client";
import type { Dashboard } from "@/lib/ui/use-project-data";
import type {
  DashboardTemplateDefinition,
  DashboardTemplateMetadata,
  DashboardTemplateParameters,
  OperationalInsightWidgetConfig,
} from "./types";

interface ReviewResponse {
  supportStatus: "fully_supported" | "partially_supported" | "not_supported";
  supportSummary: string;
  missingRequirements?: string[];
  suggestion: {
    id: string;
    title?: string;
    description?: string;
    businessPurpose?: string;
    widgets?: Array<{
      title?: string;
      businessQuestion?: string;
      status?: string;
      sql?: string;
    }>;
    knowledgeGraphContext?: {
      opportunities?: string[];
      gaps?: string[];
      risks?: string[];
    };
  };
}

interface ApplyResponse {
  dashboard_id: number;
  dashboard_name: string;
}

export interface InstantiateTemplateRequest {
  projectId: string;
  template: DashboardTemplateDefinition;
  groupName: string;
  parameters: DashboardTemplateParameters;
  onProgress?: (completed: number, total: number, dashboardName: string) => void;
}

function parameterPrompt(parameters: DashboardTemplateParameters): string {
  const values =
    parameters.valueSource === "manual"
      ? `Available ${parameters.dimensionLabel} values: ${(parameters.manualValues ?? []).join(", ")}.`
      : `Use query "${parameters.queryName ?? parameters.queryId ?? "selected query"}" to supply ${parameters.dimensionLabel} values.`;
  return `${values} Default reporting period: ${parameters.defaultPeriod.replaceAll("_", " ")}.`;
}

function operationalWidgets(
  dashboardName: string,
  prompt: string,
  suggestion: ReviewResponse["suggestion"],
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
      summary:
        suggestion.businessPurpose ||
        suggestion.description ||
        `Operational view of ${dashboardName}.`,
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
      items:
        opportunities.length
          ? opportunities
          : ["Analyze the latest governed data to identify the highest-impact opportunity."],
      updatedAt: now,
    },
  ];
}

async function generateDashboard(
  request: InstantiateTemplateRequest,
  dashboardIndex: number,
  dashboardGroupId: number,
): Promise<number> {
  const definition = request.template.dashboards[dashboardIndex];
  const prompt = [
    definition.aiPrompt,
    `Create exactly the "${definition.name}" dashboard as part of the "${request.groupName}" collection.`,
    "Use the Tablescope Operational Insight presentation: compact KPI cards with real prior-period comparisons, appropriate ECharts, drilldown-ready dimensions, an Operational Brief, and Best Improvement Opportunities.",
    "Ground every metric and query in this project's available data. Do not invent columns or unsupported KPIs.",
    parameterPrompt(request.parameters),
  ].join(" ");

  const review = await apiClient.post<ReviewResponse>(
    "/api/ai/actions/dashboard-designer/review",
    {
      project_id: Number(request.projectId),
      prompt,
      mode: "create",
      audience: definition.audience,
      period: request.parameters.defaultPeriod,
      dimension_label: request.parameters.dimensionLabel,
    },
  );

  if (review.supportStatus === "not_supported") {
    throw new Error(
      review.missingRequirements?.[0] ??
        review.supportSummary ??
        `AI could not build ${definition.name} from the available project data.`,
    );
  }

  const apply = await apiClient.post<ApplyResponse>(
    "/api/ai/actions/dashboard-designer/apply",
    {
      project_id: Number(request.projectId),
      prompt,
      mode: "create",
      dashboard_group_id: dashboardGroupId,
      support_status: review.supportStatus,
      accept_partial: true,
      suggestion: review.suggestion,
      audience: definition.audience,
      period: request.parameters.defaultPeriod,
      dimension_label: request.parameters.dimensionLabel,
    },
  );

  if (!apply.dashboard_id) {
    throw new Error(`AI did not return a saved dashboard for ${definition.name}.`);
  }

  const dashboard = await apiClient.get<Dashboard>(
    `/api/projects/${request.projectId}/dashboards/${apply.dashboard_id}`,
  );

  const existingMetadata = dashboard.config?.dashboardTemplate ?? {};
  const metadata: DashboardTemplateMetadata = {
    schemaVersion: 1,
    presentation: "operational_insight",
    templateId: request.template.id,
    templateName: request.template.name,
    groupId: `group:${dashboardGroupId}`,
    groupName: request.groupName,
    groupIcon: request.template.icon,
    dashboardKey: definition.key,
    dashboardIcon: definition.icon,
    parameters: request.parameters,
    dashboardGroupId,
    ...(existingMetadata as Record<string, unknown>),
  };

  await apiClient.put(`/api/projects/${request.projectId}/dashboards/${apply.dashboard_id}`, {
    name: definition.name,
    description: definition.description,
    status: "published",
    ai_generated: true,
    config: {
      ...dashboard.config,
      presentation: "operational_insight",
      dashboardGroupId,
      dashboardTemplate: metadata,
      operationalWidgets: operationalWidgets(definition.name, prompt, review.suggestion),
    },
  });

  return apply.dashboard_id;
}

export async function instantiateDashboardTemplate(
  request: InstantiateTemplateRequest,
): Promise<number[]> {
  if (request.template.dashboards.some((dashboard) => dashboard.itsmPreset)) {
    throw new Error("This ServiceNow template is already available in the current project.");
  }

  const created: number[] = [];
  let dashboardGroupId: number | undefined;
  try {
    const group = await apiClient.post<{ id: number }>(
      `/api/projects/${request.projectId}/dashboard-groups`,
      {
        name: request.groupName,
        icon: request.template.icon,
        template_id: request.template.id,
        collapsed_default: true,
      },
    );
    dashboardGroupId = group.id;

    for (let index = 0; index < request.template.dashboards.length; index += 1) {
      const id = await generateDashboard(request, index, group.id);
      created.push(id);
      request.onProgress?.(
        index + 1,
        request.template.dashboards.length,
        request.template.dashboards[index].name,
      );
    }

    return created;
  } catch (error) {
    await Promise.allSettled(
      created.map((id) => apiClient.delete(`/api/projects/${request.projectId}/dashboards/${id}`)),
    );
    if (dashboardGroupId) {
      await apiClient
        .delete(`/api/projects/${request.projectId}/dashboard-groups/${dashboardGroupId}`)
        .catch(() => undefined);
    }
    throw error;
  }
}
