"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

/** Connector categories supported by the Data Source Builder. */
export type SourceType =
  | "postgresql"
  | "mysql"
  | "rest_api"
  | "csv"
  | "excel"
  | "snowflake"
  | "bigquery"
  | "servicenow"
  | "salesforce"
  | "hubspot"
  | "quickbooks";

export type TableState = "adding" | "removing" | "existing" | "unselected";

export interface TableSelection {
  tableName: string;
  rows: number;
  cols: number;
  aiEnabled: boolean;
  state: TableState;
}

export type SourceStatus =
  | "configuring"
  | "connected"
  | "auth_required"
  | "error"
  | "ready";

export interface FileMetadata {
  name: string;
  rows: number;
  columns: string[];
  sheets?: string[];
  /** Server-side import job id used to finalize the file on apply. */
  importJobId?: string;
  sizeBytes?: number;
  /** How the bytes were acquired; drives the origin badge. */
  acquisitionMethod?: "local_upload" | "url" | "network_path";
  /**
   * Host the file came from, for display only. Full URLs and network paths
   * are deliberately not kept here: this store is persisted to localStorage,
   * and a locator can carry a signed token or a private folder structure.
   */
  sourceHost?: string;
}

export interface PreviewField {
  field_name: string;
  detected_type?: string;
  sample_values?: unknown[];
}

export interface SessionSource {
  /** Client-generated uuid (stable for the session). */
  id: string;
  sourceType: SourceType;
  /** e.g. 'inventory_db' or 'forecast.csv'. */
  displayName: string;
  connectionConfig: Record<string, string>;
  status: SourceStatus;
  tables: TableSelection[];
  isFileUpload: boolean;
  /**
   * True when this source is a SaaS object (ServiceNow, Salesforce, etc.).
   * The tableName is the SaaS object type and selectedFields drives creation.
   */
  isSaaS?: boolean;
  /** SaaS field names selected for sync. */
  selectedFields?: string[];
  fileMetadata?: FileMetadata;
  /** Column preview rows for file sources (CSV/Excel). */
  previewFields?: PreviewField[];
  /** Backend DatabaseDataSource id once the source is created (db sources). */
  backendId?: number;
  /** Sanitized view name used by file sources (the "table"). */
  viewName?: string;
  /**
   * True when this source was loaded from the backend (already created in a
   * previous session). Existing sources are assigned to projects via the
   * association endpoint rather than re-created, and are previewed through
   * their Teiid view.
   */
  existing?: boolean;
  /** Project the existing source currently belongs to (for Teiid routing). */
  projectId?: number | null;
  /** Immutable creation timestamp (ISO 8601). Used for the "New" badge. */
  createdAt?: string | null;
  /** Optional loaded-at timestamp (ISO 8601); falls back to createdAt. */
  loadedAt?: string | null;
}

export interface ExistingProjectSource {
  /** Stable key: viewName for files, `db:<id>` for databases. */
  sourceKey: string;
  kind: "file" | "db";
  /** viewName for files. */
  viewName?: string;
  /** backend id for databases. */
  backendId?: number;
  name: string;
  tableCount: number;
  aiOn: boolean;
}

export interface ProjectAssignment {
  projectId: string;
  projectName: string;
  color: string;
  isToggled: boolean;
  existingSources: ExistingProjectSource[];
  /** sourceKeys (from existingSources) marked for removal. */
  sourcesToRemove: string[];
  scopeIds: string[];
}

/** A single (source × project) addition in the pending change set. */
export interface PendingAddition {
  source: SessionSource;
  projectId: string;
  projectName: string;
  tableNames: string[];
}

/** A single (source × project) removal in the pending change set. */
export interface PendingRemoval {
  projectId: string;
  projectName: string;
  source: ExistingProjectSource;
}

export interface PendingChanges {
  adding: PendingAddition[];
  removing: PendingRemoval[];
}

interface BuilderState {
  sources: SessionSource[];
  activeSourceId: string | null;
  projects: ProjectAssignment[];
  /**
   * Identifier of the tenant the persisted session belongs to. Used to drop a
   * stale session when the user switches tenants (localStorage is shared
   * across tenants on the same origin).
   */
  tenantKey: string | null;
  /** Reset the session if it belongs to a different tenant than `key`. */
  ensureTenant: (key: string) => void;
  /**
   * Keys of data-source items that the user has explicitly created in Step 1.
   * A key is `sourceId` for a file source or `sourceId::tableName` for a
   * connected-database table. Items stay listed even when deselected for
   * assignment in Step 2, so this set is distinct from the per-table state.
   */
  createdKeys: string[];

  // ── source actions ──
  addSource: (source: SessionSource) => void;
  removeSource: (sourceId: string) => void;
  setActiveSource: (sourceId: string | null) => void;
  hasSource: (predicate: (s: SessionSource) => boolean) => boolean;
  markCreated: (keys: string[]) => void;
  unmarkCreated: (key: string) => void;
  /**
   * Replace the set of backend-loaded ("existing") sources with `incoming`,
   * preserving per-table selection for ones already present and leaving
   * session-created (non-existing) sources untouched. Existing sources are
   * marked as created so they appear in the Active list.
   */
  syncExisting: (incoming: SessionSource[]) => void;

  // ── table actions ──
  updateTableState: (
    sourceId: string,
    tableName: string,
    state: TableState,
  ) => void;
  toggleTableAi: (sourceId: string, tableName: string) => void;
  clearTableSelection: (sourceId: string) => void;
  selectAllTables: (sourceId: string) => void;

  // ── project actions ──
  setProjects: (projects: ProjectAssignment[]) => void;
  setProjectExisting: (
    projectId: string,
    existingSources: ExistingProjectSource[],
  ) => void;
  toggleProject: (projectId: string) => void;
  markSourceForRemoval: (projectId: string, sourceKey: string) => void;
  undoRemoval: (projectId: string, sourceKey: string) => void;
  updateScope: (projectId: string, scopeIds: string[]) => void;

  // ── selectors ──
  getActiveSource: () => SessionSource | null;
  getPendingChanges: () => PendingChanges;

  reset: () => void;
}

function selectedTableNames(source: SessionSource): string[] {
  return source.tables
    .filter((t) => t.state === "adding")
    .map((t) => t.tableName);
}

/** createdKeys entry for a source's single created item. */
function createdKeyOf(source: SessionSource): string {
  return source.isFileUpload
    ? source.id
    : `${source.id}::${source.tables[0]?.tableName ?? ""}`;
}

/**
 * The `ExistingProjectSource.sourceKey` this session source would map to once
 * assigned (`file:<viewName>` / `db:<backendId>`), or null if it can't yet be
 * matched (e.g. a brand-new connected-DB table not created in the backend).
 * Used to skip re-adding a source that already exists in the target project.
 */
export function sourceExistingKey(source: SessionSource): string | null {
  if (source.isFileUpload) {
    return source.viewName ? `file:${source.viewName}` : null;
  }
  return source.backendId != null ? `db:${source.backendId}` : null;
}

export const useBuilderStore = create<BuilderState>()(
  persist(
    (set, get) => ({
      sources: [],
      activeSourceId: null,
      projects: [],
      createdKeys: [],
      tenantKey: null,

  ensureTenant: (key) =>
    set((state) =>
      state.tenantKey === key
        ? {}
        : {
            tenantKey: key,
            sources: [],
            activeSourceId: null,
            projects: [],
            createdKeys: [],
          },
    ),

  addSource: (source) =>
    set((state) => ({
      sources: [...state.sources, source],
      activeSourceId: source.id,
    })),

  markCreated: (keys) =>
    set((state) => ({
      createdKeys: Array.from(new Set([...state.createdKeys, ...keys])),
    })),

  unmarkCreated: (key) =>
    set((state) => ({
      createdKeys: state.createdKeys.filter((k) => k !== key),
    })),

  syncExisting: (incoming) =>
    set((state) => {
      const prevExisting = new Map(
        state.sources.filter((s) => s.existing).map((s) => [s.id, s]),
      );
      // Preserve the user's per-table selection across refetches.
      const merged = incoming.map((s) => {
        const prev = prevExisting.get(s.id);
        return prev ? { ...s, tables: prev.tables } : s;
      });
      const sources = [
        ...state.sources.filter((s) => !s.existing),
        ...merged,
      ];
      const keptKeys = state.createdKeys.filter(
        (k) => !k.startsWith("existing-"),
      );
      const createdKeys = Array.from(
        new Set([...keptKeys, ...merged.map(createdKeyOf)]),
      );
      return { sources, createdKeys };
    }),

  removeSource: (sourceId) =>
    set((state) => {
      const sources = state.sources.filter((s) => s.id !== sourceId);
      const activeSourceId =
        state.activeSourceId === sourceId
          ? (sources[0]?.id ?? null)
          : state.activeSourceId;
      // Drop pending additions of this source from every project.
      const projects = state.projects.map((p) => ({
        ...p,
        sourcesToRemove: p.sourcesToRemove,
      }));
      const createdKeys = state.createdKeys.filter(
        (k) => k !== sourceId && !k.startsWith(`${sourceId}::`),
      );
      return { sources, activeSourceId, projects, createdKeys };
    }),

  setActiveSource: (sourceId) => set({ activeSourceId: sourceId }),

  hasSource: (predicate) => get().sources.some(predicate),

  updateTableState: (sourceId, tableName, tableState) =>
    set((state) => ({
      sources: state.sources.map((s) =>
        s.id !== sourceId
          ? s
          : {
              ...s,
              tables: s.tables.map((t) =>
                t.tableName === tableName ? { ...t, state: tableState } : t,
              ),
            },
      ),
    })),

  toggleTableAi: (sourceId, tableName) =>
    set((state) => ({
      sources: state.sources.map((s) =>
        s.id !== sourceId
          ? s
          : {
              ...s,
              tables: s.tables.map((t) =>
                t.tableName === tableName
                  ? { ...t, aiEnabled: !t.aiEnabled }
                  : t,
              ),
            },
      ),
    })),

  clearTableSelection: (sourceId) =>
    set((state) => ({
      sources: state.sources.map((s) =>
        s.id !== sourceId
          ? s
          : {
              ...s,
              tables: s.tables.map((t) =>
                t.state === "adding" ? { ...t, state: "unselected" } : t,
              ),
            },
      ),
    })),

  selectAllTables: (sourceId) =>
    set((state) => ({
      sources: state.sources.map((s) =>
        s.id !== sourceId
          ? s
          : {
              ...s,
              tables: s.tables.map((t) =>
                t.state === "unselected" ? { ...t, state: "adding" } : t,
              ),
            },
      ),
    })),

  setProjects: (projects) => set({ projects }),

  setProjectExisting: (projectId, existingSources) =>
    set((state) => ({
      projects: state.projects.map((p) =>
        p.projectId === projectId ? { ...p, existingSources } : p,
      ),
    })),

  toggleProject: (projectId) =>
    set((state) => ({
      projects: state.projects.map((p) =>
        p.projectId === projectId ? { ...p, isToggled: !p.isToggled } : p,
      ),
    })),

  markSourceForRemoval: (projectId, sourceKey) =>
    set((state) => ({
      projects: state.projects.map((p) =>
        p.projectId !== projectId || p.sourcesToRemove.includes(sourceKey)
          ? p
          : { ...p, sourcesToRemove: [...p.sourcesToRemove, sourceKey] },
      ),
    })),

  undoRemoval: (projectId, sourceKey) =>
    set((state) => ({
      projects: state.projects.map((p) =>
        p.projectId !== projectId
          ? p
          : {
              ...p,
              sourcesToRemove: p.sourcesToRemove.filter(
                (k) => k !== sourceKey,
              ),
            },
      ),
    })),

  updateScope: (projectId, scopeIds) =>
    set((state) => ({
      projects: state.projects.map((p) =>
        p.projectId === projectId ? { ...p, scopeIds } : p,
      ),
    })),

  getActiveSource: () => {
    const { sources, activeSourceId } = get();
    return sources.find((s) => s.id === activeSourceId) ?? null;
  },

  getPendingChanges: () => {
    const { sources, projects } = get();
    const adding: PendingAddition[] = [];
    const removing: PendingRemoval[] = [];

    for (const project of projects) {
      if (project.isToggled) {
        const alreadyInProject = new Set(
          project.existingSources.map((e) => e.sourceKey),
        );
        for (const source of sources) {
          // Skip sources already assigned to this project (no duplicates).
          const existingKey = sourceExistingKey(source);
          if (existingKey && alreadyInProject.has(existingKey)) continue;
          const tableNames = selectedTableNames(source);
          if (tableNames.length > 0) {
            adding.push({
              source,
              projectId: project.projectId,
              projectName: project.projectName,
              tableNames,
            });
          }
        }
      }
      for (const sourceKey of project.sourcesToRemove) {
        const existing = project.existingSources.find(
          (s) => s.sourceKey === sourceKey,
        );
        if (existing) {
          removing.push({
            projectId: project.projectId,
            projectName: project.projectName,
            source: existing,
          });
        }
      }
    }

    return { adding, removing };
  },

  reset: () =>
    set({ sources: [], activeSourceId: null, projects: [], createdKeys: [] }),
    }),
    {
      name: "tablescope-data-source-builder",
      storage: createJSONStorage(() =>
        typeof window !== "undefined"
          ? window.localStorage
          : (undefined as unknown as Storage),
      ),
      // Hydrate manually after mount to avoid SSR/client markup mismatches.
      skipHydration: true,
      partialize: (state) => ({
        sources: state.sources,
        activeSourceId: state.activeSourceId,
        projects: state.projects,
        createdKeys: state.createdKeys,
        tenantKey: state.tenantKey,
      }),
    },
  ),
);
