import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));
vi.mock("@/lib/api/data-source-builder", () => ({
  listMyDataSources: vi.fn().mockResolvedValue([]),
}));
// A stable reference: the store-sync effects key off `summaries` identity, and
// react-query hands back the same array between renders. A fresh [] per render
// would loop them -- an artifact of the mock, not of the component.
const NO_PROJECTS: never[] = [];
const SUMMARIES_RESULT = { data: NO_PROJECTS, isLoading: false };
vi.mock("@/lib/ui/use-shell-data", () => ({
  useProjectSummaries: () => SUMMARIES_RESULT,
}));
vi.mock("./ai-upload-dropzone", () => ({
  AiUploadDropzone: ({ projectId }: { projectId?: number }) => (
    <div>dropzone projectId={String(projectId)}</div>
  ),
}));
vi.mock("./url-import-form", () => ({ UrlImportForm: () => <div /> }));
vi.mock("./database-connections-panel", () => ({
  DatabaseConnectionsPanel: () => <div>DatabaseConnectionsPanel</div>,
}));
vi.mock("./network-file-connections-panel", () => ({
  NetworkFileConnectionsPanel: () => <div />,
}));
vi.mock("./connected-sources-section", () => ({
  ConnectedSourcesSection: () => <div>ConnectedSourcesSection</div>,
}));
vi.mock("./all-data-sources-panel", () => ({
  AllDataSourcesPanel: () => <div>AllDataSourcesPanel</div>,
}));
vi.mock("./home-assign-panel", () => ({
  HomeAssignPanel: () => <div>HomeAssignPanel</div>,
}));
vi.mock("./confirmation-modal", () => ({ ConfirmationModal: () => null }));
vi.mock("@/components/tablescope/project/new-project-dialog", () => ({
  NewProjectDialog: ({ open }: { open: boolean }) =>
    open ? <div>NewProjectDialog</div> : null,
}));

import { HomeDataBuilder, type HomeBuilderTab } from "./home-data-builder";

function renderBuilder(tab: HomeBuilderTab = "builder") {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <HomeDataBuilder tenantName="Acme" tab={tab} onTabChange={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("HomeDataBuilder", () => {
  beforeEach(() => {
    useBuilderStore.getState().reset();
    push.mockClear();
  });

  it("runs without a project, so uploads carry no project_id", () => {
    renderBuilder();
    // The dropzone is what refuses documents when there's no project; it has
    // to actually receive undefined rather than NaN from Number(undefined).
    expect(screen.getByText("dropzone projectId=undefined")).toBeTruthy();
  });

  it("offers both endings instead of one 'Add to Project'", () => {
    renderBuilder();
    expect(screen.getByRole("button", { name: "Add to Existing Project" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start Project" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add to Project" })).toBeNull();
  });

  it("disables both until something has been staged", () => {
    renderBuilder();
    expect(
      screen.getByRole("button", { name: "Add to Existing Project" }),
    ).toHaveProperty("disabled", true);
    expect(
      screen.getByRole("button", { name: "Start Project" }),
    ).toHaveProperty("disabled", true);
  });

  it("swaps the staging area for the assignment step, keeping the session", () => {
    useBuilderStore.getState().markCreated(["src-1"]);
    renderBuilder();
    fireEvent.click(screen.getByRole("button", { name: "Add to Existing Project" }));
    expect(screen.getByText("HomeAssignPanel")).toBeTruthy();
    // Back returns to staging rather than navigating, so the staged session
    // -- which lives in the store -- is never unmounted mid-flow.
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.queryByText("HomeAssignPanel")).toBeNull();
  });

  it("renders the other two tabs from the same components a project uses", () => {
    renderBuilder("connected");
    expect(screen.getByText("ConnectedSourcesSection")).toBeTruthy();
    renderBuilder("all");
    expect(screen.getByText("AllDataSourcesPanel")).toBeTruthy();
  });
});
