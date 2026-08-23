import { beforeEach, describe, expect, it } from "vitest";
import {
  closeWorkspaceTab,
  loadWorkspaceTabs,
  saveWorkspaceTabs,
  upsertWorkspaceTab,
  WORKSPACE_TABS_MAX,
  type WorkspaceTab,
} from "./workspace-tabs-storage";

function tab(type: WorkspaceTab["type"], id: string): WorkspaceTab {
  return { type, id, label: `${type}-${id}`, href: `/x/${id}` };
}

describe("workspace tabs storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("round-trips tabs through localStorage per project", () => {
    saveWorkspaceTabs("7", [tab("table", "1"), tab("dashboard", "2")]);
    expect(loadWorkspaceTabs("7")).toHaveLength(2);
    expect(loadWorkspaceTabs("8")).toHaveLength(0);
  });

  it("returns an empty list for corrupt or missing storage", () => {
    window.localStorage.setItem("tablescope:workspace-tabs:7", "not json");
    expect(loadWorkspaceTabs("7")).toEqual([]);
    window.localStorage.setItem("tablescope:workspace-tabs:7", JSON.stringify({ not: "an array" }));
    expect(loadWorkspaceTabs("7")).toEqual([]);
  });

  it("upsert appends a newly opened tab at the end", () => {
    const t1 = tab("table", "1");
    const t2 = tab("dashboard", "2");
    let tabs = upsertWorkspaceTab([], t1);
    tabs = upsertWorkspaceTab(tabs, t2);

    expect(tabs.map((t) => t.id)).toEqual(["1", "2"]);
  });

  it("re-activating an already-open tab updates it in place without moving it", () => {
    const t1 = tab("table", "1");
    const t2 = tab("dashboard", "2");
    let tabs = upsertWorkspaceTab([], t1);
    tabs = upsertWorkspaceTab(tabs, t2);
    // Switching back to the first tab must not reorder the strip -- it
    // should stay exactly where the user left it, just with fresh data.
    tabs = upsertWorkspaceTab(tabs, { ...t1, label: "renamed" });

    expect(tabs.map((t) => t.id)).toEqual(["1", "2"]);
    expect(tabs[0].label).toBe("renamed");
  });

  it("caps the tab list at WORKSPACE_TABS_MAX", () => {
    let tabs: WorkspaceTab[] = [];
    for (let i = 0; i < WORKSPACE_TABS_MAX + 5; i++) {
      tabs = upsertWorkspaceTab(tabs, tab("table", String(i)));
    }
    expect(tabs).toHaveLength(WORKSPACE_TABS_MAX);
    // The oldest tabs were evicted; the most recent ones remain.
    expect(tabs[0].id).toBe("5");
    expect(tabs[tabs.length - 1].id).toBe(String(WORKSPACE_TABS_MAX + 4));
  });

  it("closeWorkspaceTab removes only the matching type+id", () => {
    const tabs = [tab("table", "1"), tab("data_source", "1"), tab("dashboard", "2")];
    const next = closeWorkspaceTab(tabs, "table", "1");
    expect(next).toHaveLength(2);
    expect(next.find((t) => t.type === "table")).toBeUndefined();
    expect(next.find((t) => t.type === "data_source")).toBeDefined();
  });
});
