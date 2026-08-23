import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { Dashboard } from "@/lib/ui/use-project-data";
import type { DashboardGroup } from "./types";
import { DashboardOverview } from "./dashboard-overview";

function dashboard(id: number, name: string): Dashboard {
  return {
    id,
    project_id: 1,
    tenant_id: 1,
    owner_id: null,
    name,
    description: null,
    status: "published",
    config: { widgets: [] },
    ai_generated: true,
    view_count: 0,
    created_at: "2026-08-15T00:00:00Z",
    updated_at: "2026-08-15T00:00:00Z",
  };
}

function group(id: string, name: string, dashboards: Dashboard[]): DashboardGroup {
  return { id, name, icon: "activity", dashboards, collapsedDefault: true };
}

describe("DashboardOverview", () => {
  it("renders every dashboard from every group as one flat list, with no group headers", () => {
    render(
      <DashboardOverview
        groups={[
          group("g1", "ServiceNow ITSM Operations", [dashboard(-1, "Incident Insights")]),
          group("g2", "Operational Dashboards", [dashboard(1, "Sales Operation Dashboard")]),
        ]}
        loading={false}
        onOpenDashboard={vi.fn()}
        onAddTemplate={vi.fn()}
        onDeleteDashboard={vi.fn()}
      />,
    );

    expect(screen.getByText("Incident Insights")).toBeTruthy();
    expect(screen.getByText("Sales Operation Dashboard")).toBeTruthy();
    expect(screen.queryByText("ServiceNow ITSM Operations")).toBeNull();
    expect(screen.queryByText("Operational Dashboards")).toBeNull();
    expect(screen.queryByText(/collection/i)).toBeNull();
  });

  it("has no group-management affordances (rename, add-to-group, create group)", () => {
    render(
      <DashboardOverview
        groups={[group("g1", "Operational Dashboards", [dashboard(1, "Sales Operation Dashboard")])]}
        loading={false}
        onOpenDashboard={vi.fn()}
        onAddTemplate={vi.fn()}
        onDeleteDashboard={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: /add dashboard$/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /create dashboard group/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /create dashboard with ai/i })).toBeNull();
  });

  it("opening and deleting a dashboard call the right callbacks", () => {
    const onOpenDashboard = vi.fn();
    const onDeleteDashboard = vi.fn();
    const target = dashboard(1, "Sales Operation Dashboard");
    render(
      <DashboardOverview
        groups={[group("g1", "Operational Dashboards", [target])]}
        loading={false}
        onOpenDashboard={onOpenDashboard}
        onAddTemplate={vi.fn()}
        onDeleteDashboard={onDeleteDashboard}
      />,
    );

    fireEvent.click(screen.getByText("Sales Operation Dashboard"));
    expect(onOpenDashboard).toHaveBeenCalledWith(1);

    fireEvent.click(screen.getByRole("button", { name: /delete dashboard sales operation dashboard/i }));
    expect(onDeleteDashboard).toHaveBeenCalledWith(target);
  });

  it("shows an empty state with only an Add dashboard template action when there are no dashboards", () => {
    const onAddTemplate = vi.fn();
    render(
      <DashboardOverview
        groups={[]}
        loading={false}
        onOpenDashboard={vi.fn()}
        onAddTemplate={onAddTemplate}
        onDeleteDashboard={vi.fn()}
      />,
    );

    expect(screen.getByText(/create your first dashboard/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /add dashboard template/i }));
    expect(onAddTemplate).toHaveBeenCalled();
  });
});
