import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { SourceTab } from "./source-method-tabs";

vi.mock("@/lib/api/data-source-builder", () => ({
  listMyDataSources: vi.fn().mockResolvedValue([]),
}));
vi.mock("./ai-upload-dropzone", () => ({
  AiUploadDropzone: () => <div>UploadFilePanel</div>,
}));
vi.mock("./url-import-form", () => ({
  UrlImportForm: () => <div>FileUrlPanel</div>,
}));
vi.mock("./available-sources", () => ({
  AvailableSources: () => <div>AvailableSources</div>,
}));
vi.mock("./database-connections-panel", () => ({
  DatabaseConnectionsPanel: () => <div>DatabaseConnectionsPanel</div>,
}));
vi.mock("./network-file-connections-panel", () => ({
  NetworkFileConnectionsPanel: () => <div>NetworkFileConnectionsPanel</div>,
}));
vi.mock("./connected-sources-section", () => ({
  ConnectedSourcesSection: () => <div>ConnectedSourcesSection</div>,
}));
vi.mock("./data-source-selection-section", () => ({
  DataSourceSelectionSection: () => <div>DataSourceSelectionSection</div>,
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

function renderWorkspace(initialSourceTab?: SourceTab) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <DataSourceBuilderWorkspace
        tenantName="Acme"
        initialSourceTab={initialSourceTab}
      />
    </QueryClientProvider>,
  );
}

describe("DataSourceBuilderWorkspace", () => {
  it("shows the upload tab by default", () => {
    renderWorkspace();
    expect(screen.getByText("UploadFilePanel")).toBeInTheDocument();
    expect(screen.getByText("ConnectedSourcesSection")).toBeInTheDocument();
    expect(screen.getByText("DataSourceSelectionSection")).toBeInTheDocument();
  });

  it("renders database tab content when initialSourceTab is database", () => {
    renderWorkspace("database");
    expect(screen.getByText("DatabaseConnectionsPanel")).toBeInTheDocument();
    expect(screen.queryByText("UploadFilePanel")).not.toBeInTheDocument();
  });

  it("renders network tab content when initialSourceTab is network", () => {
    renderWorkspace("network");
    expect(screen.getByText("NetworkFileConnectionsPanel")).toBeInTheDocument();
  });
});
