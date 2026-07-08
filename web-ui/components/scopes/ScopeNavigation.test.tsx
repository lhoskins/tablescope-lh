import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { notifyScopesChanged, updateScopeSet, scopeSet } = vi.hoisted(() => ({
  notifyScopesChanged: vi.fn(),
  updateScopeSet: vi.fn().mockResolvedValue({}),
  scopeSet: {
    id: 7,
    project_id: 1,
    name: "AR → GL",
    type: "manual",
    enabled: true,
    scope_count: 2,
    creator_name: "Leonard",
    creator_email: "leonard@example.com",
    created_at: "2026-05-13T05:00:00+00:00",
    updated_at: "2026-05-13T05:00:00+00:00",
  },
}));

vi.mock("@/lib/api/scopes", () => ({
  scopesApi: {
    listScopeSets: vi.fn().mockResolvedValue([scopeSet]),
    updateScopeSet: (id: number, body: { enabled: boolean }) =>
      updateScopeSet(id, body),
    deleteScopeSet: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock("@/lib/ui/scope-refresh", () => ({
  useNotifyScopesChanged: () => notifyScopesChanged,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { ScopeNavigation } from "./ScopeNavigation";

function renderWithClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ScopeNavigation projectId={1} />
    </QueryClientProvider>,
  );
}

describe("ScopeNavigation", () => {
  beforeEach(() => {
    notifyScopesChanged.mockClear();
    updateScopeSet.mockClear();
  });

  it("notifies scope-icon consumers when a scope set is toggled", async () => {
    renderWithClient();

    const toggle = await screen.findByRole("button", { name: /disable scope/i });
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(updateScopeSet).toHaveBeenCalledWith(7, { enabled: false });
      expect(notifyScopesChanged).toHaveBeenCalledTimes(1);
    });
  });
});
