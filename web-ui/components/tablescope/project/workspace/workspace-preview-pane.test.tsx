import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { WorkspacePreviewPane } from "./workspace-preview-pane";
import type { WorkspaceCard } from "@/lib/api/workspaces";

const documents = vi.fn();
const queries = vi.fn();
const dataSources = vi.fn();
const dashboards = vi.fn();

vi.mock("@/lib/ui/use-project-data", () => ({
  useProjectDocuments: () => documents(),
  useProjectQueries: () => queries(),
  useProjectDataSources: () => dataSources(),
  useProjectDashboards: () => dashboards(),
}));

// The embedded views are covered by their own tests; here we only care which
// one the pane chooses for a given card.
vi.mock("@/components/documents/document-preview", () => ({
  DocumentPreview: ({ document }: { document: { id: number } }) => (
    <div>document preview {document.id}</div>
  ),
}));
vi.mock("../detail-views/query-result-view", () => ({
  QueryResultView: ({ query }: { query: { id: number } }) => (
    <div>query result {query.id}</div>
  ),
}));
vi.mock("../detail-views/data-source-result-view", () => ({
  DataSourceResultView: ({ source }: { source: { id: number } }) => (
    <div>data source result {source.id}</div>
  ),
}));

function card(overrides: Partial<WorkspaceCard>): WorkspaceCard {
  return {
    id: 1,
    resource_type: "document",
    resource_id: "9001",
    view_mode: "card",
    position: 0,
    label: "Incident Report",
    ...overrides,
  } as WorkspaceCard;
}

describe("WorkspacePreviewPane", () => {
  beforeEach(() => {
    documents.mockReturnValue({ data: [{ id: 9001, filename: "a.md" }] });
    queries.mockReturnValue({ data: [{ id: 3001, name: "invoices" }] });
    dataSources.mockReturnValue({ data: [{ id: 2, fileName: "orders" }] });
    dashboards.mockReturnValue({ data: [{ id: 5, name: "Exec Overview" }] });
  });

  it("prompts when nothing is selected", () => {
    render(<WorkspacePreviewPane projectId="1" card={null} />);
    expect(screen.getByText(/Click on a file in the Documents pane/)).toBeTruthy();
  });

  it("renders each resource type with its own existing view", () => {
    const { rerender } = render(
      <WorkspacePreviewPane projectId="1" card={card({})} />,
    );
    expect(screen.getByText("document preview 9001")).toBeTruthy();

    rerender(
      <WorkspacePreviewPane
        projectId="1"
        card={card({ resource_type: "table", resource_id: "3001" })}
      />,
    );
    expect(screen.getByText("query result 3001")).toBeTruthy();

    rerender(
      <WorkspacePreviewPane
        projectId="1"
        card={card({ resource_type: "data_source", resource_id: "2" })}
      />,
    );
    expect(screen.getByText("data source result 2")).toBeTruthy();
  });

  it("tells the user dashboards have no pane preview instead of going blank", () => {
    render(
      <WorkspacePreviewPane
        projectId="1"
        card={card({ resource_type: "dashboard", resource_id: "5" })}
      />,
    );
    expect(screen.getByText("Exec Overview")).toBeTruthy();
    expect(screen.getByText(/can't be previewed in a pane yet/)).toBeTruthy();
  });

  it("distinguishes a resource still loading from one that is gone", () => {
    // Project data hasn't arrived yet.
    documents.mockReturnValue({ data: undefined });
    const { rerender } = render(
      <WorkspacePreviewPane projectId="1" card={card({})} />,
    );
    expect(screen.getByText("Loading…")).toBeTruthy();

    // Loaded, but the card outlived the document it points at.
    documents.mockReturnValue({ data: [] });
    rerender(<WorkspacePreviewPane projectId="1" card={card({})} />);
    expect(screen.getByText(/no longer in this project/)).toBeTruthy();
    expect(screen.getByText("Incident Report")).toBeTruthy();
  });
});
