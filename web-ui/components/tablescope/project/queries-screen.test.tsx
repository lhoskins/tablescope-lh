import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

/**
 * "Query Wizard" must open the parameterized AI Query Designer dialog -- the
 * same "describe -> preview -> save" pattern the AI Dashboard Designer uses,
 * not a single-line prompt bar -- and the manual SQL query builder must
 * remain reachable from the action center as "Create Query".
 */

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/projects/42/queries",
  useSearchParams: () => new URLSearchParams(),
}));

const queriesData = vi.hoisted(() => ({ rows: [] as unknown[] }));

vi.mock("@/lib/ui/use-project-data", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/ui/use-project-data")>();
  return {
    ...actual,
    useProjectQueries: () => ({ data: queriesData.rows, isLoading: false }),
    useProjectArchivedQueries: () => ({ data: [] }),
    useProjectDataSources: () => ({ data: [] }),
  };
});

vi.mock("@/components/tablescope/project-shell", () => ({
  ProjectShell: ({
    children,
    actions,
  }: {
    children?: ReactNode;
    actions?: ReactNode;
  }) => (
    <div data-testid="project-shell">
      <div data-testid="header-actions">{actions}</div>
      {children}
    </div>
  ),
}));

vi.mock("@/components/datasource/AddDatasourceModal", () => ({
  AddDatasourceModal: () => null,
}));

const aiQueryDesignerProps = vi.hoisted(() => ({
  current: null as null | { open: boolean },
}));

vi.mock("@/components/tablescope/project/ai-query-designer", () => ({
  AIQueryDesigner: (props: { open: boolean }) => {
    aiQueryDesignerProps.current = props;
    return props.open ? <div data-testid="ai-query-designer" /> : null;
  },
}));

vi.mock("@/components/tablescope/project/detail-views", () => ({
  QueryResultView: () => null,
  QueryBuilderEdit: () => null,
  QueryBuilderCreate: () => <div data-testid="query-builder-create" />,
}));

import { QueriesScreen } from "./queries-screen";

function renderScreen() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <QueriesScreen projectId="42" />
    </QueryClientProvider>,
  );
}

function savedQuery(id: number, name: string) {
  return {
    id,
    project_id: 42,
    owner_id: null,
    name,
    description: null,
    left_datasource: null,
    right_datasource: null,
    join_type: null,
    left_column: null,
    right_column: null,
    sql_text: "SELECT 1",
    ai_generated: false,
    is_shared: false,
    run_count: 0,
    last_run_at: null,
    avg_runtime_ms: null,
    is_archived: false,
    archived_at: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    owner_name: null,
    origin: "manual",
    origin_label: "Manual",
    source_name: null,
    has_outgoing_scope: false,
    outgoing_scope_count: 0,
    has_incoming_scope: false,
    incoming_scope_count: 0,
    has_active_scope: false,
    active_scope_count: 0,
  };
}

describe("QueriesScreen", () => {
  it("opens the AI Query Designer dialog instead of a single-line prompt bar", () => {
    renderScreen();

    expect(screen.queryByTestId("ai-query-designer")).not.toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText("Describe the query you want to generate…"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /query wizard/i }));

    expect(screen.getByTestId("ai-query-designer")).toBeInTheDocument();
    expect(aiQueryDesignerProps.current).toMatchObject({ open: true });
  });

  it("keeps the manual query builder reachable from the action center", () => {
    renderScreen();

    expect(screen.queryByTestId("query-builder-create")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /create query/i }));

    expect(screen.getByTestId("query-builder-create")).toBeInTheDocument();
  });

  it("keeps the URL in sync when a table is opened by clicking its row", async () => {
    queriesData.rows = [savedQuery(7, "Monthly Revenue")];
    router.replace.mockClear();
    renderScreen();

    fireEvent.click(screen.getByText("Monthly Revenue"));

    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith(
        "/projects/42/queries?q=7",
        { scroll: false },
      ),
    );

    queriesData.rows = [];
  });
});
