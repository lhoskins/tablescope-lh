import { describe, expect, it } from "vitest";
import type { Dashboard } from "@/lib/ui/use-project-data";
import { groupDashboards, virtualItsmDashboardConfig } from "./groups";

function dashboard(id: number, name: string, config: Record<string, unknown>): Dashboard {
  return {
    id,
    project_id: 1,
    tenant_id: 1,
    owner_id: null,
    name,
    description: null,
    status: "published",
    config,
    ai_generated: true,
    view_count: 0,
    created_at: "2026-08-15T00:00:00Z",
    updated_at: "2026-08-15T00:00:00Z",
  };
}

describe("dashboard template groups", () => {
  it("places ServiceNow insight dashboards in one selectable group", () => {
    const groups = groupDashboards([
      dashboard(-1, "Incident Management Insights", virtualItsmDashboardConfig("incident_insights")),
      dashboard(-2, "Request Management Insights", virtualItsmDashboardConfig("service_request_insights")),
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0].name).toBe("ServiceNow ITSM Operations");
    expect(groups[0].dashboards.map((item) => item.id)).toEqual([-1, -2]);
  });

  it("keeps unassigned dashboards in a custom collection", () => {
    const groups = groupDashboards([dashboard(8, "Supplier Dashboard", { widgets: [] })]);
    expect(groups[0].name).toBe("Operational Dashboards");
    expect(groups[0].dashboards[0].id).toBe(8);
  });

  it("merges legacy and persisted custom collections into one group", () => {
    const groups = groupDashboards(
      [dashboard(8, "Supplier Dashboard", {
        widgets: [],
        dashboardTemplate: {
          groupId: "custom-dashboards",
          groupName: "Custom dashboards",
          dashboardKey: "supplier",
        },
      })],
      [
        { id: 41, slug: "custom-dashboards", name: "Custom dashboards", icon: "activity", collapsedDefault: true, dashboardIds: [] },
        { id: 42, slug: "custom-dashboards-2", name: "Custom dashboards", icon: "activity", collapsedDefault: true, dashboardIds: [8] },
      ],
    );

    expect(groups).toHaveLength(1);
    expect(groups[0].persistentId).toBe(41);
    expect(groups[0].dashboards.map((item) => item.id)).toEqual([8]);
  });
});
