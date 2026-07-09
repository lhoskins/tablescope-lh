import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { SavedQuery } from "@/lib/ui/use-project-data";

function makeQuery(overrides: Partial<SavedQuery>): SavedQuery {
  return {
    id: 1,
    project_id: 1,
    owner_id: 1,
    name: "Query",
    description: null,
    left_datasource: "assets",
    right_datasource: null,
    join_type: null,
    left_column: null,
    right_column: null,
    sql_text: "select 1",
    ai_generated: false,
    is_shared: true,
    run_count: 0,
    last_run_at: null,
    avg_runtime_ms: null,
    is_archived: false,
    archived_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    owner_name: "Leonard",
    origin: "manual",
    origin_label: "Manual",
    source_name: "assets",
    has_outgoing_scope: false,
    outgoing_scope_count: 0,
    has_incoming_scope: false,
    incoming_scope_count: 0,
    has_active_scope: false,
    active_scope_count: 0,
    ...overrides,
  };
}

const SCOPED = makeQuery({
  id: 10,
  name: "IT Assets",
  has_outgoing_scope: true,
  outgoing_scope_count: 2,
  has_active_scope: true,
  active_scope_count: 2,
});
const UNSCOPED = makeQuery({ id: 11, name: "Employees" });

vi.mock("@/lib/ui/use-project-data", () => ({
  useProjectQueries: () => ({ data: [SCOPED, UNSCOPED], isLoading: false }),
  useProjectArchivedQueries: () => ({ data: [] }),
  useProjectDataSources: () => ({ data: [] }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/components/tablescope/project-shell", () => ({
  ProjectShell: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

vi.mock("@/components/tablescope/project/detail-views", () => ({
  QueryResultView: () => <div />,
  QueryBuilderEdit: () => <div />,
  QueryBuilderCreate: () => <div />,
}));

vi.mock("@/components/datasource/AddDatasourceModal", () => ({
  AddDatasourceModal: () => <div />,
}));

import { QueriesScreen } from "./queries-screen";

const ICON_TITLE = "This table has an active outgoing scope relationship.";

function renderScreen() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <QueriesScreen projectId="1" />
    </QueryClientProvider>,
  );
}

describe("QueriesScreen scope indicator (Issue 3)", () => {
  it("renders the scope icon only for a query that has an enabled outgoing scope", () => {
    renderScreen();

    // Exactly one icon — on the scoped query, not the unscoped one.
    const icons = screen.getAllByTitle(ICON_TITLE);
    expect(icons).toHaveLength(1);

    // The single icon sits in the scoped query's row, not the unscoped one.
    const iconRow = icons[0].closest("tr");
    expect(iconRow?.textContent).toContain("IT Assets");
    const unscopedRow = screen.getByText("Employees").closest("tr");
    expect(unscopedRow).not.toBe(iconRow);
  });
});
