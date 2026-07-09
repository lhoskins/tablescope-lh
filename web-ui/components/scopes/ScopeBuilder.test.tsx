import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type {
  ScopeAISuggestion,
  ScopeBuilderTable,
  ScopeMap,
  ScopeMapSavePayload,
} from "@/lib/api/scopes";

const { builderTables, getMap, aiSuggest, saveMap, notifyScopesChanged } =
  vi.hoisted(() => ({
    builderTables: vi.fn(),
    getMap: vi.fn(),
    aiSuggest: vi.fn(),
    saveMap: vi.fn(),
    notifyScopesChanged: vi.fn(),
  }));

vi.mock("@/lib/api/scopes", () => ({
  scopesApi: {
    builderTables: (projectId: number) => builderTables(projectId),
    getMap: (id: number) => getMap(id),
    aiSuggest: (id: number, ids: number[]) => aiSuggest(id, ids),
    saveMap: (id: number, body: ScopeMapSavePayload) => saveMap(id, body),
    deleteScopeSet: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock("@/lib/ui/scope-refresh", () => ({
  useNotifyScopesChanged: () => notifyScopesChanged,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { ScopeBuilder } from "./ScopeBuilder";

const TABLES: ScopeBuilderTable[] = [
  {
    table_key: "query:1",
    table_name: "IT Assets",
    query_id: 1,
    datasource_id: null,
    fields: ["asset_id", "employee_id"],
  },
  {
    table_key: "query:2",
    table_name: "Employees",
    query_id: 2,
    datasource_id: null,
    fields: ["employee_id", "name"],
  },
];

function emptyMap(): ScopeMap {
  return {
    scope_set: {
      id: 9,
      tenant_id: 1,
      project_id: 1,
      name: "IT Scope",
      description: null,
      type: "manual",
      enabled: true,
      created_by: 1,
      creator_name: "Leonard",
      creator_email: "leonard@example.com",
      created_at: null,
      updated_at: null,
      can_delete: true,
      scope_count: 0,
    },
    // Two canvas tables so "AI Suggest Fields" is enabled (needs >= 2 tables).
    tables: [
      {
        table_key: "query:1",
        table_name: "IT Assets",
        query_id: 1,
        datasource_id: null,
        x_position: 40,
        y_position: 40,
        width: 320,
        height: 160,
      },
      {
        table_key: "query:2",
        table_name: "Employees",
        query_id: 2,
        datasource_id: null,
        x_position: 460,
        y_position: 40,
        width: 320,
        height: 160,
      },
    ],
    relationships: [],
  };
}

const SUGGESTION: ScopeAISuggestion = {
  query_id: 1,
  source_field: "employee_id",
  source_table: "IT Assets",
  target_query_id: 2,
  target_field: "employee_id",
  target_table: "Employees",
  match_group_id: null,
  match_mode: "all",
  confidence_score: 0.82,
  rationale: "Shared employee_id column",
};

describe("ScopeBuilder — accepted AI suggestion persists on Save (Issue 1)", () => {
  beforeEach(() => {
    builderTables.mockResolvedValue(TABLES);
    getMap.mockResolvedValue(emptyMap());
    aiSuggest.mockResolvedValue({ suggestions: [SUGGESTION] });
    saveMap.mockResolvedValue(emptyMap());
    notifyScopesChanged.mockClear();
    saveMap.mockClear();
  });

  it("sends the accepted suggestion as a created_by_ai relationship in PUT /map", async () => {
    render(<ScopeBuilder projectId={1} scopeSetId={9} />);

    // Wait for hydration (both canvas tables placed) so the AI Suggest button
    // is enabled — it requires >= 2 tables on the canvas.
    await waitFor(() =>
      expect(screen.getAllByText("IT Assets").length).toBeGreaterThan(0),
    );
    const suggestBtn = screen.getByRole("button", {
      name: /AI Suggest Fields/i,
    });
    await waitFor(() => expect(suggestBtn.hasAttribute("disabled")).toBe(false));
    fireEvent.click(suggestBtn);

    // Accept the returned suggestion.
    const acceptBtn = await screen.findByRole("button", { name: /^Accept$/i });
    fireEvent.click(acceptBtn);

    // Save.
    fireEvent.click(screen.getByRole("button", { name: /Save Scope/i }));

    await waitFor(() => expect(saveMap).toHaveBeenCalledTimes(1));
    const [, body] = saveMap.mock.calls[0] as [number, ScopeMapSavePayload];
    const aiRels = body.relationships.filter((r) => r.created_by_ai === true);
    expect(aiRels).toHaveLength(1);
    expect(aiRels[0]).toMatchObject({
      query_id: 1,
      source_field: "employee_id",
      target_query_id: 2,
      target_field: "employee_id",
      created_by_ai: true,
      confidence_score: 0.82,
    });
    // Both referenced queries must be in the tables payload so the backend's
    // "Queries not in project" validation + reload don't drop the mapping.
    const tableQueryIds = body.tables.map((t) => t.query_id);
    expect(tableQueryIds).toEqual(expect.arrayContaining([1, 2]));
  });
});
