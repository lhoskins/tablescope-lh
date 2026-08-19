import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

/**
 * "Create Query with AI" must open the preview-before-save modal instead of
 * blind-saving (the old generate-and-save-query behavior), and the manual
 * SQL Query Builder must be reachable as a clearly secondary/legacy action --
 * mirroring the AI Dashboard Designer's "generate, preview, then save"
 * pattern instead of committing a query the user never got to review.
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

const generateQueryPreviewModalProps = vi.hoisted(() => ({
  current: null as null | { open: boolean; question: string },
}));

vi.mock("@/components/ai/GenerateQueryPreviewModal", () => ({
  GenerateQueryPreviewModal: (props: { open: boolean; question: string }) => {
    generateQueryPreviewModalProps.current = props;
    return props.open ? (
      <div data-testid="generate-query-preview-modal">{props.question}</div>
    ) : null;
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
  it("opens the preview-before-save modal instead of blind-saving on submit", () => {
    renderScreen();

    expect(
      screen.queryByTestId("generate-query-preview-modal"),
    ).not.toBeInTheDocument();

    const input = screen.getByPlaceholderText(
      "Describe the query you want to generate…",
    );
    fireEvent.change(input, {
      target: { value: "Revenue by region last quarter" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /create query with ai/i }),
    );

    expect(screen.getByTestId("generate-query-preview-modal")).toHaveTextContent(
      "Revenue by region last quarter",
    );
    expect(generateQueryPreviewModalProps.current).toMatchObject({
      open: true,
      question: "Revenue by region last quarter",
    });
  });

  it("does not open the modal for an empty prompt", () => {
    renderScreen();

    fireEvent.click(
      screen.getByRole("button", { name: /create query with ai/i }),
    );

    expect(
      screen.queryByTestId("generate-query-preview-modal"),
    ).not.toBeInTheDocument();
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
