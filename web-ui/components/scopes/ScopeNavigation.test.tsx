import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ScopeSet } from "@/lib/api/scopes";

const listScopeSets = vi.fn();
const updateScopeSet = vi.fn();
const autoGenerateScopes = vi.fn();

vi.mock("@/lib/api/scopes", () => ({
  scopesApi: {
    listScopeSets: (...a: unknown[]) => listScopeSets(...a),
    updateScopeSet: (...a: unknown[]) => updateScopeSet(...a),
    autoGenerateScopes: (...a: unknown[]) => autoGenerateScopes(...a),
    deleteScopeSet: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

import { ScopeNavigation } from "./ScopeNavigation";

function aiSet(overrides: Partial<ScopeSet> = {}): ScopeSet {
  return {
    id: 7,
    tenant_id: 1,
    project_id: 3,
    name: "AI Generated Scopes",
    description: null,
    type: "ai_generated",
    enabled: false,
    created_by: 1,
    creator_name: "Leonard",
    creator_email: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    can_delete: true,
    scope_count: 0,
    ...overrides,
  };
}

function renderNav() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ScopeNavigation projectId={3} />
    </QueryClientProvider>,
  );
}

describe("ScopeNavigation AI autoscope (Issue 2)", () => {
  beforeEach(() => {
    listScopeSets.mockReset();
    updateScopeSet.mockReset().mockResolvedValue({});
    autoGenerateScopes.mockReset().mockResolvedValue({});
  });

  it("enabling the AI scope set enables it and calls auto-generate", async () => {
    listScopeSets.mockResolvedValue([aiSet()]);
    renderNav();

    const toggle = await screen.findByRole("button", { name: "Enable scope" });
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(updateScopeSet).toHaveBeenCalledWith(7, { enabled: true });
      expect(autoGenerateScopes).toHaveBeenCalledWith(3);
    });
  });

  it("the header Generate action triggers auto-generate for the project", async () => {
    listScopeSets.mockResolvedValue([]);
    renderNav();

    const btn = await screen.findByRole("button", { name: /Generate AI Scopes/ });
    fireEvent.click(btn);

    await waitFor(() => expect(autoGenerateScopes).toHaveBeenCalledWith(3));
  });
});
