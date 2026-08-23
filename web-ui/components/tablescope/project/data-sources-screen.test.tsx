import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  within,
  waitFor,
  act,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/projects/42/data-sources",
  useSearchParams: () => new URLSearchParams(),
}));

import { DataSourcesScreen } from "./data-sources-screen";
import { useProjectDataSources } from "@/lib/ui/use-project-data";
import type { DataSource } from "@/lib/ui/use-project-data";

const fileSource: DataSource = {
  fileName: "sales.csv",
  viewName: "sales_CSV",
  size: 1024,
  sourceType: "csv",
  dbType: null,
  connectorType: null,
  id: 1,
  fileMetaId: 1,
  ownerId: 1,
  ownerName: "Leonard",
  columnTypes: [{ name: "amount", type: "double" }],
  archived: false,
  archivedAt: null,
  lifecycleKind: "file",
  lifecycleId: "sales_CSV",
};

const dbSource: DataSource = {
  fileName: "Postgres orders",
  viewName: "orders_POSTGRES",
  size: null,
  sourceType: "database_table",
  dbType: "postgres",
  connectorType: null,
  id: 2,
  ownerId: 1,
  ownerName: "Leonard",
  columnTypes: [{ name: "id", type: "integer" }],
  archived: false,
  archivedAt: null,
  lifecycleKind: "database",
  lifecycleId: "2",
};

const saasSource: DataSource = {
  fileName: "ServiceNow incidents",
  viewName: "incident_SERVICENOW",
  size: null,
  sourceType: "saas_object",
  dbType: "servicenow",
  connectorType: "servicenow",
  id: 3,
  ownerId: 1,
  ownerName: "Leonard",
  columnTypes: [{ name: "sys_id", type: "string" }],
  archived: false,
  archivedAt: null,
  lifecycleKind: "saas",
  lifecycleId: "99",
};

const archivedFile: DataSource = {
  ...fileSource,
  archived: true,
  archivedAt: "2026-07-01T00:00:00Z",
};

const { archiveSource, preflightDelete, deleteSource } = vi.hoisted(() => ({
  archiveSource: vi.fn().mockResolvedValue({ archived: true }),
  preflightDelete: vi.fn().mockResolvedValue({
    safe: true,
    archived: true,
    blockers: [],
    active_query_dependencies: [],
  }),
  deleteSource: vi.fn().mockResolvedValue({ status: "deleted" }),
}));

vi.mock("@/lib/ui/use-project-data", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/ui/use-project-data")>();
  return { ...actual, useProjectDataSources: vi.fn() };
});

vi.mock("./data-sources-screen/archive-source", () => ({ archiveSource }));
vi.mock("./data-sources-screen/preflight-delete", () => ({ preflightDelete }));
vi.mock("./data-sources-screen/delete-source", () => ({ deleteSource }));

vi.mock("@/components/tablescope/project-shell", () => ({
  ProjectShell: ({ children }: { children?: ReactNode }) => (
    <div data-testid="project-shell">{children}</div>
  ),
}));

vi.mock("@/components/datasource/ConnectorsMenu", () => ({
  ConnectorsMenu: () => <div data-testid="connectors-menu" />,
}));

vi.mock("@/components/tablescope/project/data-source-update-dialog", () => ({
  DataSourceUpdateDialog: ({ open }: { open?: boolean }) =>
    open ? <div data-testid="update-dialog" /> : null,
}));

vi.mock("@/components/tablescope/project/detail-views", () => ({
  DataSourceResultView: vi.fn(
    ({ source, onArchive, archiveBusy, archiveError }) => (
      <div data-testid="detail-view">
        <span data-testid="detail-name">{source.fileName}</span>
        {archiveError && (
          <div data-testid="archive-error">{archiveError}</div>
        )}
        <button
          data-testid="detail-archive"
          onClick={onArchive}
          disabled={archiveBusy}
        >
          Archive
        </button>
      </div>
    ),
  ),
}));

function renderScreen(data: DataSource[] = []) {
  vi.mocked(useProjectDataSources).mockReturnValue({
    data,
    isLoading: false,
    isError: false,
    error: null,
  } as ReturnType<typeof useProjectDataSources>);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <DataSourcesScreen projectId="42" />
    </QueryClientProvider>,
  );
}

describe("DataSourcesScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    archiveSource.mockResolvedValue({ archived: true });
    preflightDelete.mockResolvedValue({
      safe: true,
      archived: true,
      blockers: [],
      active_query_dependencies: [],
    });
    deleteSource.mockResolvedValue({ status: "deleted" });
  });

  it("shows the active list with no Archive/Delete and file Update only", () => {
    renderScreen([fileSource, dbSource, saasSource]);
    // The Archive tab filter is present, but no row-level Archive/Delete.
    const archiveButtons = screen.queryAllByRole("button", { name: /Archive/i });
    expect(archiveButtons.length).toBe(1);
    expect(
      screen.queryByRole("button", { name: /Delete/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Update" })).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    // header + 3 data rows
    expect(rows.length).toBeGreaterThanOrEqual(4);
  });

  it("filters the active list by search term", () => {
    renderScreen([fileSource, dbSource]);
    const input = screen.getByPlaceholderText("Search data sources…");
    fireEvent.change(input, { target: { value: "Postgres" } });
    expect(screen.getByText("Postgres orders")).toBeInTheDocument();
    expect(screen.queryByText("sales.csv")).not.toBeInTheDocument();
  });

  it("shows the Archive tab with Restore/Delete and archived metadata columns", () => {
    renderScreen([archivedFile]);
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(
      screen.getByRole("button", { name: "Restore" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Delete" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Archived")).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
  });

  it("shows the empty state for the active list", () => {
    renderScreen([]);
    expect(
      screen.getByText("No data sources yet. Connect a database or upload a file to get started."),
    ).toBeInTheDocument();
  });

  it("shows the empty state for the archive tab", () => {
    renderScreen([]);
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(
      screen.getByText(
        "No archived data sources. Archive a data source to see it here.",
      ),
    ).toBeInTheDocument();
  });

  it("opens the detail view and archives from it", async () => {
    renderScreen([fileSource]);
    fireEvent.click(screen.getByText("sales.csv"));
    await waitFor(() =>
      expect(screen.getByTestId("detail-view")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("detail-archive"));
    await waitFor(() =>
      expect(archiveSource).toHaveBeenCalledWith(fileSource, true),
    );
  });

  it("restores an archived source from the Archive tab", async () => {
    renderScreen([archivedFile]);
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    fireEvent.click(screen.getByRole("button", { name: "Restore" }));
    await waitFor(() =>
      expect(archiveSource).toHaveBeenCalledWith(archivedFile, false),
    );
  });

  it("permanently deletes an archived source after preflight", async () => {
    renderScreen([archivedFile]);
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(preflightDelete).toHaveBeenCalledWith(archivedFile),
    );
    const dialog = screen.getByRole("heading", {
      name: 'Delete "sales.csv"?',
    }).parentElement as HTMLElement;
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleteSource).toHaveBeenCalledWith(archivedFile));
  });

  it("disables the archive action while a lifecycle call is in flight", async () => {
    let release: (() => void) | undefined;
    archiveSource.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = () => resolve({ archived: true });
        }),
    );
    renderScreen([fileSource]);
    fireEvent.click(screen.getByText("sales.csv"));
    await waitFor(() =>
      expect(screen.getByTestId("detail-view")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("detail-archive"));
    const button = await waitFor(() => screen.getByTestId("detail-archive"));
    expect(button).toBeDisabled();
    await act(async () => {
      release?.();
      await Promise.resolve();
    });
    await waitFor(() =>
      expect(screen.queryByTestId("detail-view")).not.toBeInTheDocument(),
    );
  });

  it("surfaces archive errors in the detail view", async () => {
    archiveSource.mockRejectedValue(new Error("Network failure"));
    renderScreen([fileSource]);
    fireEvent.click(screen.getByText("sales.csv"));
    await waitFor(() =>
      expect(screen.getByTestId("detail-view")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("detail-archive"));
    await waitFor(() =>
      expect(screen.getByTestId("archive-error")).toHaveTextContent(
        "Network failure",
      ),
    );
  });
});
