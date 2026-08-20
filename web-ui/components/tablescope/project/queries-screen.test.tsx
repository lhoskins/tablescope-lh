import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

/**
 * "Create Query with AI" must open the parameterized AI Query Designer
 * dialog -- the same "describe -> preview -> save" pattern the AI Dashboard
 * Designer uses, not a single-line prompt bar -- and the manual SQL Query
 * Builder must remain reachable as a clearly secondary/legacy action.
 */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/projects/42/queries",
}));

vi.mock("@/lib/ui/use-project-data", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/ui/use-project-data")>();
  return {
    ...actual,
    useProjectQueries: () => ({ data: [], isLoading: false }),
    useProjectArchivedQueries: () => ({ data: [] }),
    useProjectDataSources: () => ({ data: [] }),
  };
});

vi.mock("@/components/tablescope/project-shell", () => ({
  ProjectShell: ({
    children,
    headerActions,
  }: {
    children?: ReactNode;
    headerActions?: ReactNode;
  }) => (
    <div data-testid="project-shell">
      <div data-testid="header-actions">{headerActions}</div>
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

describe("QueriesScreen", () => {
  it("opens the AI Query Designer dialog instead of a single-line prompt bar", () => {
    renderScreen();

    expect(screen.queryByTestId("ai-query-designer")).not.toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText("Describe the query you want to generate…"),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /create query with ai/i }),
    );

    expect(screen.getByTestId("ai-query-designer")).toBeInTheDocument();
    expect(aiQueryDesignerProps.current).toMatchObject({ open: true });
  });

  it("keeps the manual Query Builder reachable as a secondary, legacy action", () => {
    renderScreen();

    expect(screen.queryByTestId("query-builder-create")).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /query builder \(legacy\)/i }),
    );

    expect(screen.getByTestId("query-builder-create")).toBeInTheDocument();
  });
});
