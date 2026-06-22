import { beforeEach, describe, expect, it } from "vitest";
import {
  useBuilderStore,
  type ProjectAssignment,
  type SessionSource,
} from "./data-source-builder-store";

function dbSource(overrides: Partial<SessionSource> = {}): SessionSource {
  return {
    id: "src-1",
    sourceType: "postgresql",
    displayName: "inventory_db",
    connectionConfig: {},
    status: "connected",
    isFileUpload: false,
    tables: [
      { tableName: "orders", rows: 100, cols: 5, aiEnabled: true, state: "unselected" },
      { tableName: "items", rows: 50, cols: 4, aiEnabled: true, state: "existing" },
    ],
    ...overrides,
  };
}

function fileSource(overrides: Partial<SessionSource> = {}): SessionSource {
  return {
    id: "file-1",
    sourceType: "csv",
    displayName: "forecast.csv",
    connectionConfig: {},
    status: "ready",
    isFileUpload: true,
    viewName: "forecast_csv",
    tables: [
      { tableName: "forecast_csv", rows: 4820, cols: 6, aiEnabled: true, state: "adding" },
    ],
    fileMetadata: { name: "forecast.csv", rows: 4820, columns: ["a", "b"] },
    ...overrides,
  };
}

function project(overrides: Partial<ProjectAssignment> = {}): ProjectAssignment {
  return {
    projectId: "p1",
    projectName: "Supply Chain Q3",
    color: "#185FA5",
    isToggled: false,
    existingSources: [
      { sourceKey: "db:9", kind: "db", backendId: 9, name: "logistics_db", tableCount: 8, aiOn: true },
    ],
    sourcesToRemove: [],
    scopeIds: [],
    ...overrides,
  };
}

describe("data-source-builder-store", () => {
  beforeEach(() => {
    useBuilderStore.getState().reset();
  });

  it("addSource appends and sets it active", () => {
    useBuilderStore.getState().addSource(dbSource());
    const s = useBuilderStore.getState();
    expect(s.sources).toHaveLength(1);
    expect(s.activeSourceId).toBe("src-1");
    expect(s.getActiveSource()?.displayName).toBe("inventory_db");
  });

  it("removeSource drops it and re-points the active source", () => {
    const store = useBuilderStore.getState();
    store.addSource(dbSource());
    store.addSource(fileSource());
    store.removeSource("file-1");
    const s = useBuilderStore.getState();
    expect(s.sources.map((x) => x.id)).toEqual(["src-1"]);
    expect(s.activeSourceId).toBe("src-1");
  });

  it("setActiveSource updates the active id", () => {
    const store = useBuilderStore.getState();
    store.addSource(dbSource());
    store.addSource(fileSource());
    store.setActiveSource("src-1");
    expect(useBuilderStore.getState().activeSourceId).toBe("src-1");
  });

  it("hasSource detects duplicates", () => {
    useBuilderStore.getState().addSource(dbSource());
    expect(
      useBuilderStore.getState().hasSource((s) => s.displayName === "inventory_db"),
    ).toBe(true);
    expect(
      useBuilderStore.getState().hasSource((s) => s.displayName === "nope"),
    ).toBe(false);
  });

  it("updateTableState transitions a table", () => {
    const store = useBuilderStore.getState();
    store.addSource(dbSource());
    store.updateTableState("src-1", "orders", "adding");
    const t = useBuilderStore
      .getState()
      .getActiveSource()
      ?.tables.find((x) => x.tableName === "orders");
    expect(t?.state).toBe("adding");
  });

  it("clearTableSelection resets only adding rows", () => {
    const store = useBuilderStore.getState();
    store.addSource(dbSource());
    store.updateTableState("src-1", "orders", "adding");
    store.clearTableSelection("src-1");
    const tables = useBuilderStore.getState().getActiveSource()?.tables ?? [];
    expect(tables.find((t) => t.tableName === "orders")?.state).toBe("unselected");
    expect(tables.find((t) => t.tableName === "items")?.state).toBe("existing");
  });

  it("selectAllTables marks unselected rows as adding", () => {
    const store = useBuilderStore.getState();
    store.addSource(dbSource());
    store.selectAllTables("src-1");
    const tables = useBuilderStore.getState().getActiveSource()?.tables ?? [];
    expect(tables.find((t) => t.tableName === "orders")?.state).toBe("adding");
    // existing rows are untouched
    expect(tables.find((t) => t.tableName === "items")?.state).toBe("existing");
  });

  it("toggleTableAi flips the flag", () => {
    const store = useBuilderStore.getState();
    store.addSource(dbSource());
    store.toggleTableAi("src-1", "orders");
    const t = useBuilderStore
      .getState()
      .getActiveSource()
      ?.tables.find((x) => x.tableName === "orders");
    expect(t?.aiEnabled).toBe(false);
  });

  it("toggleProject flips the toggle", () => {
    const store = useBuilderStore.getState();
    store.setProjects([project()]);
    store.toggleProject("p1");
    expect(useBuilderStore.getState().projects[0].isToggled).toBe(true);
    store.toggleProject("p1");
    expect(useBuilderStore.getState().projects[0].isToggled).toBe(false);
  });

  it("markSourceForRemoval / undoRemoval manage the removal set", () => {
    const store = useBuilderStore.getState();
    store.setProjects([project()]);
    store.markSourceForRemoval("p1", "db:9");
    expect(useBuilderStore.getState().projects[0].sourcesToRemove).toEqual(["db:9"]);
    // idempotent
    store.markSourceForRemoval("p1", "db:9");
    expect(useBuilderStore.getState().projects[0].sourcesToRemove).toEqual(["db:9"]);
    store.undoRemoval("p1", "db:9");
    expect(useBuilderStore.getState().projects[0].sourcesToRemove).toEqual([]);
  });

  it("updateScope sets scope ids", () => {
    const store = useBuilderStore.getState();
    store.setProjects([project()]);
    store.updateScope("p1", ["s1", "s2"]);
    expect(useBuilderStore.getState().projects[0].scopeIds).toEqual(["s1", "s2"]);
  });

  it("getPendingChanges aggregates additions for toggled projects", () => {
    const store = useBuilderStore.getState();
    store.addSource(dbSource());
    store.updateTableState("src-1", "orders", "adding");
    store.setProjects([project({ isToggled: true })]);
    const { adding, removing } = useBuilderStore.getState().getPendingChanges();
    expect(adding).toHaveLength(1);
    expect(adding[0].tableNames).toEqual(["orders"]);
    expect(adding[0].projectId).toBe("p1");
    expect(removing).toHaveLength(0);
  });

  it("getPendingChanges includes file sources without table selection", () => {
    const store = useBuilderStore.getState();
    store.addSource(fileSource());
    store.setProjects([project({ isToggled: true })]);
    const { adding } = useBuilderStore.getState().getPendingChanges();
    expect(adding).toHaveLength(1);
    expect(adding[0].tableNames).toEqual(["forecast_csv"]);
  });

  it("getPendingChanges skips toggled projects with no selected tables", () => {
    const store = useBuilderStore.getState();
    store.addSource(dbSource()); // no table marked adding
    store.setProjects([project({ isToggled: true })]);
    expect(useBuilderStore.getState().getPendingChanges().adding).toHaveLength(0);
  });

  it("getPendingChanges aggregates removals", () => {
    const store = useBuilderStore.getState();
    store.setProjects([project()]);
    store.markSourceForRemoval("p1", "db:9");
    const { removing } = useBuilderStore.getState().getPendingChanges();
    expect(removing).toHaveLength(1);
    expect(removing[0].source.name).toBe("logistics_db");
  });

  it("syncExisting marks backend sources as created and dedups", () => {
    const store = useBuilderStore.getState();
    store.addSource(fileSource()); // a session-created (non-existing) source
    const existing: SessionSource[] = [
      dbSource({ id: "existing-db-7", existing: true, backendId: 7 }),
      fileSource({
        id: "existing-file-3",
        existing: true,
        viewName: "sales_csv",
      }),
    ];
    store.syncExisting(existing);
    const s = useBuilderStore.getState();
    // session source preserved + 2 existing added
    expect(s.sources).toHaveLength(3);
    // existing sources are marked created so they show in the Active list
    expect(s.createdKeys).toContain("existing-file-3");
    expect(s.createdKeys).toContain("existing-db-7::orders");

    // re-syncing with the same id does not duplicate
    store.syncExisting(existing);
    expect(useBuilderStore.getState().sources).toHaveLength(3);

    // dropping one from the backend removes it (and its created key)
    store.syncExisting([existing[0]]);
    const s2 = useBuilderStore.getState();
    expect(s2.sources.filter((x) => x.existing)).toHaveLength(1);
    expect(s2.createdKeys).not.toContain("existing-file-3");
  });

  it("reset clears everything", () => {
    const store = useBuilderStore.getState();
    store.addSource(dbSource());
    store.setProjects([project({ isToggled: true })]);
    store.reset();
    const s = useBuilderStore.getState();
    expect(s.sources).toEqual([]);
    expect(s.projects).toEqual([]);
    expect(s.activeSourceId).toBeNull();
  });
});
