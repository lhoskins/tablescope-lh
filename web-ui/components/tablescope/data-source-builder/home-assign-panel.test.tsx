import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";

const SUMMARIES = [
  { id: "7", name: "API Costs", accent: "#185FA5" },
  { id: "8", name: "IT Tickets", accent: "#2EA66F" },
];
const SUMMARIES_RESULT = { data: SUMMARIES, isLoading: false };
vi.mock("@/lib/ui/use-shell-data", () => ({
  useProjectSummaries: () => SUMMARIES_RESULT,
}));
vi.mock("@/lib/api/data-source-builder", () => ({
  listProjectDataSources: vi.fn().mockResolvedValue([]),
}));

import { HomeAssignPanel } from "./home-assign-panel";

function stageOneFile() {
  const store = useBuilderStore.getState();
  store.addSource({
    id: "src-1",
    displayName: "sales.csv",
    sourceType: "csv",
    isFileUpload: true,
    viewName: "sales_CSV",
    tables: [
      { tableName: "sales_CSV", rows: 10, cols: 3, state: "adding", aiOn: false },
    ],
  } as never);
  store.markCreated(["src-1"]);
}

function renderPanel() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <HomeAssignPanel onNewProject={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("HomeAssignPanel", () => {
  beforeEach(() => useBuilderStore.getState().reset());

  it("shows only the two questions, not project management", () => {
    stageOneFile();
    renderPanel();
    expect(screen.getByText(/Data to assign/)).toBeTruthy();
    expect(screen.getByText("Add to")).toBeTruthy();
    // The wizard's step 2 surfaces these mid-assign; this panel must not.
    expect(screen.queryByText(/ALREADY IN PROJECT/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
    expect(screen.queryByText(/Assigned/)).toBeNull();
  });

  it("drives the same store contract the wizard does", () => {
    stageOneFile();
    renderPanel();

    // Selecting a project must toggle it, because getPendingChanges only
    // emits additions for toggled projects.
    fireEvent.click(screen.getByRole("button", { name: /API Costs/ }));
    const toggled = useBuilderStore
      .getState()
      .projects.filter((p) => p.isToggled)
      .map((p) => p.projectId);
    expect(toggled).toEqual(["7"]);

    const pending = useBuilderStore.getState().getPendingChanges();
    expect(pending.adding).toHaveLength(1);
    expect(pending.adding[0].projectId).toBe("7");
    expect(pending.adding[0].tableNames).toEqual(["sales_CSV"]);
  });

  it("deselecting a source drops it from the pending set", () => {
    stageOneFile();
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /API Costs/ }));
    fireEvent.click(screen.getByRole("button", { name: /sales\.csv/ }));
    expect(useBuilderStore.getState().getPendingChanges().adding).toHaveLength(0);
  });

  it("supports more than one target project", () => {
    stageOneFile();
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /API Costs/ }));
    fireEvent.click(screen.getByRole("button", { name: /IT Tickets/ }));
    const pending = useBuilderStore.getState().getPendingChanges();
    expect(pending.adding.map((a) => a.projectId).sort()).toEqual(["7", "8"]);
  });

  it("says so when nothing has been staged", () => {
    renderPanel();
    expect(screen.getByText(/Nothing staged yet/)).toBeTruthy();
  });
});
