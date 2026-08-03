import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api/data-source-builder", () => ({
  listMyDataSources: vi.fn().mockResolvedValue([]),
}));
vi.mock("./file-acquisition-panel", () => ({
  FileAcquisitionPanel: () => <div>FileAcquisitionPanel</div>,
}));
vi.mock("./active-sources-table", () => ({
  ActiveSourcesTable: () => <div>ActiveSourcesTable</div>,
}));
vi.mock("./available-sources", () => ({
  AvailableSources: () => <div>AvailableSources</div>,
}));
vi.mock("./connected-databases", () => ({
  ConnectedDatabases: () => <div>ConnectedDatabases</div>,
}));
vi.mock("./connected-saas", () => ({
  ConnectedSaaS: () => <div>ConnectedSaaS</div>,
}));
vi.mock("./projects-column", () => ({
  ProjectsColumn: () => <div>ProjectsColumn</div>,
}));
vi.mock("./confirmation-modal", () => ({
  ConfirmationModal: () => null,
}));
vi.mock("@/components/tablescope/project/new-project-dialog", () => ({
  NewProjectDialog: () => null,
}));

import { DataSourceBuilderWorkspace } from "./workspace";

function renderWorkspace(intent?: "upload" | "database") {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <DataSourceBuilderWorkspace tenantName="Acme" intent={intent} />
    </QueryClientProvider>,
  );
}

describe("DataSourceBuilderWorkspace", () => {
  it("shows connector sections alongside file acquisition by default", () => {
    renderWorkspace();
    expect(screen.getByText("FileAcquisitionPanel")).toBeInTheDocument();
    expect(screen.getByText("ConnectedDatabases")).toBeInTheDocument();
    expect(screen.getByText("ConnectedSaaS")).toBeInTheDocument();
  });

  it("hides connector sections when intent is upload-only", () => {
    renderWorkspace("upload");
    expect(screen.getByText("FileAcquisitionPanel")).toBeInTheDocument();
    expect(screen.queryByText("ConnectedDatabases")).not.toBeInTheDocument();
    expect(screen.queryByText("ConnectedSaaS")).not.toBeInTheDocument();
  });

  it("uses upload-scoped step hint when intent is upload-only", () => {
    renderWorkspace("upload");
    expect(
      screen.getByText(/Upload a file to create a data source/),
    ).toBeInTheDocument();
  });

  it("shows only connected databases when intent is database-only", () => {
    renderWorkspace("database");
    expect(screen.queryByText("FileAcquisitionPanel")).not.toBeInTheDocument();
    expect(screen.getByText("ConnectedDatabases")).toBeInTheDocument();
    expect(screen.queryByText("ConnectedSaaS")).not.toBeInTheDocument();
  });

  it("uses database-scoped step hint when intent is database-only", () => {
    renderWorkspace("database");
    expect(
      screen.getByText(/Choose a connected database and table/),
    ).toBeInTheDocument();
  });
});
