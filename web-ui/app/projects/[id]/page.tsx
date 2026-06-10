"use client";

import { useState, useCallback, useMemo, useEffect, DragEvent } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { getUserMeta } from "@/lib/auth";
import { AddDatasourceModal } from "@/components/datasource/AddDatasourceModal";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { DataGrid } from "@/components/data-grid/DataGrid";
import { TanStackDataGrid } from "@/components/data-grid/TanStackDataGrid";
import { DashboardTab } from "@/components/dashboard/DashboardTab";
import { AIPanel } from "@/components/ai/AIPanel";
import { AIPromptBar } from "@/components/ai/AIPromptBar";
import { ScopesTab } from "@/components/scopes/ScopesTab";
import { QueryBuilder } from "@/components/query-builder/QueryBuilder";

// Small badge describing where a datasource comes from (file type or DB engine).
function SourceBadge({ ds }: { ds: Datasource }) {
  let label: string;
  let cls: string;
  if (ds.sourceType === "saas_object") {
    const c = (ds.connectorType ?? "saas").toLowerCase();
    label =
      c === "hubspot"
        ? "HubSpot"
        : c === "salesforce"
        ? "Salesforce"
        : c === "quickbooks"
        ? "QuickBooks"
        : "SaaS";
    cls =
      c === "hubspot"
        ? "bg-orange-100 text-orange-700"
        : c === "quickbooks"
        ? "bg-green-100 text-green-700"
        : "bg-sky-100 text-sky-700";
  } else if (ds.sourceType === "database_table") {
    const db = (ds.dbType ?? "database").toLowerCase();
    label =
      db === "postgresql"
        ? "PostgreSQL"
        : db === "mysql"
        ? "MySQL"
        : db === "sqlserver"
        ? "SQL Server"
        : db === "oracle"
        ? "Oracle"
        : "Database";
    cls = "bg-indigo-100 text-indigo-700";
  } else {
    label = (ds.sourceType ?? "file").toUpperCase();
    cls = "bg-emerald-100 text-emerald-700";
  }
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${cls}`}>{label}</span>
  );
}

// ── Types ───────────────────────────────────────────────────────────

type Project = {
  id: number;
  name: string;
  description: string | null;
  is_shared: boolean;
  scoping_enabled: boolean;
  owner_id: number | null;
};

type ColumnType = { name: string; field: string; type: string };

type Datasource = {
  fileName: string;
  viewName: string;
  size: number | null;
  sourceType?: string | null;
  dbType?: string | null;
  connectorType?: string | null;
  id?: number | null;
  ownerId?: number | null;
  fileMetaId?: number | null;
  projectId?: number | null;
  archived?: boolean;
  columnTypes?: ColumnType[];
};

type SavedQuery = {
  id: number;
  project_id: number;
  owner_id: number | null;
  name: string;
  description: string | null;
  left_datasource: string | null;
  right_datasource: string | null;
  join_type: string | null;
  left_column: string | null;
  right_column: string | null;
  sql_text: string | null;
};

type Member = {
  project_id: number;
  user_id: number;
  role: string;
  is_active: boolean;
  email: string;
  display_name: string | null;
};

type TenantUser = {
  id: number;
  email: string;
  display_name: string | null;
  role: string;
};

type QueryResult = {
  columns: string[];
  rows: Record<string, unknown>[];
};

// ── Main Component ──────────────────────────────────────────────────

export default function ProjectWorkspacePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const projectId = Number(params.id);
  const meta = getUserMeta();

  // ── Tab state ─────────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<"datasources" | "queries" | "dashboards" | "scopes" | "ai" | "members">("datasources");

  // ── Collapsible panels ──────────────────────────────────────────
  const [dsListOpen, setDsListOpen] = useState(false);
  const [queryListOpen, setQueryListOpen] = useState(false);

  // ── AI generation state ─────────────────────────────────────────
  const [aiQueryLoading, setAiQueryLoading] = useState(false);
  const [aiQueryError, setAiQueryError] = useState<string | null>(null);
  const [aiQuerySuccess, setAiQuerySuccess] = useState<string | null>(null);

  const handleAIGenerateQuery = useCallback(async (prompt: string) => {
    setAiQueryLoading(true);
    setAiQueryError(null);
    setAiQuerySuccess(null);
    try {
      const result = await apiClient.post<{ query_id: number; name: string; sql_text: string; status: string }>(
        "/api/ai/actions/generate-and-save-query",
        { project_id: projectId, prompt },
      );
      const verb = result.status === "updated" ? "updated" : "saved";
      setAiQuerySuccess(`Query ${verb}: ${result.name}`);
      queryClient.invalidateQueries({ queryKey: ["project-queries", projectId] });
    } catch (err) {
      setAiQueryError(err instanceof Error ? err.message : "AI query generation failed");
    } finally {
      setAiQueryLoading(false);
    }
  }, [projectId, queryClient]);

  // ── Query builder state ───────────────────────────────────────────
  const [buildingQuery, setBuildingQuery] = useState(false);

  // ── Inline rename ─────────────────────────────────────────────────
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");

  // ── Saved query click-to-execute ──────────────────────────────────
  const [activeSavedQueryId, setActiveSavedQueryId] = useState<number | null>(null);
  const [savedQueryResult, setSavedQueryResult] = useState<QueryResult | null>(null);
  const [savedQueryError, setSavedQueryError] = useState<string | null>(null);
  const [savedQueryLoading, setSavedQueryLoading] = useState(false);

  // ── Edit query state ──────────────────────────────────────────────
  const [editingQuery, setEditingQuery] = useState<SavedQuery | null>(null);

  // ── Datasource click-to-view result ───────────────────────────────
  const [dsResult, setDsResult] = useState<QueryResult | null>(null);
  const [dsError, setDsError] = useState<string | null>(null);
  const [dsLoading, setDsLoading] = useState(false);
  const [activeDsName, setActiveDsName] = useState<string | null>(null);

  // ── Member assignment ─────────────────────────────────────────────
  const [addUserId, setAddUserId] = useState<number | null>(null);
  const [addRole, setAddRole] = useState("viewer");

  // ── Data fetching ─────────────────────────────────────────────────

  const projectQuery = useQuery<Project>({
    queryKey: ["project", projectId],
    queryFn: () => apiClient.get<Project>(`/api/projects/${projectId}`),
  });

  const datasourcesQuery = useQuery<Datasource[]>({
    queryKey: ["project-datasources", projectId],
    queryFn: () => apiClient.get<Datasource[]>(`/api/projects/${projectId}/datasources`),
  });

  const queriesQuery = useQuery<SavedQuery[]>({
    queryKey: ["project-queries", projectId],
    queryFn: () => apiClient.get<SavedQuery[]>(`/api/projects/${projectId}/queries`),
  });

  const membersQuery = useQuery<Member[]>({
    queryKey: ["project-members", projectId],
    queryFn: () => apiClient.get<Member[]>(`/api/projects/${projectId}/members`),
  });

  const tenantUsersQuery = useQuery<TenantUser[]>({
    queryKey: ["tenant-users", meta?.tenant_id],
    queryFn: () =>
      apiClient.get<TenantUser[]>(`/api/tenants/${meta?.tenant_id}/users`),
    enabled: activeTab === "members" && !!meta?.tenant_id,
  });

  // ── Sharing mutations ─────────────────────────────────────────────

  const toggleShareMutation = useMutation({
    mutationFn: (share: boolean) =>
      apiClient.put<Project>(`/api/projects/${projectId}`, { is_shared: share }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      queryClient.invalidateQueries({ queryKey: ["project-datasources", projectId] });
    },
  });

  // ── Scoping toggle mutation ──────────────────────────────────────
  const [scopingLoading, setScopingLoading] = useState(false);
  const toggleScopingMutation = useMutation({
    mutationFn: async (enabled: boolean) => {
      const result = await apiClient.put<Project>(`/api/projects/${projectId}`, { scoping_enabled: enabled });
      if (enabled) {
        setScopingLoading(true);
        try {
          await apiClient.post(`/api/ai/project/scope-map/auto-create`, { project_id: projectId });
        } catch {
          console.warn("Auto scope creation failed — scoping enabled but no scopes created");
        } finally {
          setScopingLoading(false);
        }
      }
      return result;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });

  // ── Saved query mutations ─────────────────────────────────────────

  const createQueryMutation = useMutation({
    mutationFn: (payload: {
      name: string;
      description: string;
      left_datasource: string;
      right_datasource: string;
      join_type: string;
      left_column: string;
      right_column: string;
      sql_text: string;
    }) => apiClient.post(`/api/projects/${projectId}/queries`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-queries", projectId] });
      setBuildingQuery(false);
    },
  });

  const renameQueryMutation = useMutation({
    mutationFn: ({ queryId, name }: { queryId: number; name: string }) =>
      apiClient.put(`/api/projects/${projectId}/queries/${queryId}`, { name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-queries", projectId] });
      setRenamingId(null);
    },
  });

  const updateQueryMutation = useMutation({
    mutationFn: (payload: {
      queryId: number;
      name?: string;
      description?: string;
      left_datasource?: string;
      right_datasource?: string;
      join_type?: string;
      left_column?: string;
      right_column?: string;
      sql_text?: string;
    }) => {
      const { queryId, ...body } = payload;
      return apiClient.put<SavedQuery>(`/api/projects/${projectId}/queries/${queryId}`, body);
    },
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["project-queries", projectId] });
      setEditingQuery(null);
      // If this query's results are currently displayed, re-run it with the
      // updated SQL so changes (e.g. a removed join) are reflected immediately.
      if (data && activeSavedQueryId === variables.queryId) {
        setSavedQueryLoading(true);
        setSavedQueryError(null);
        setSavedQueryResult(null);
        apiClient
          .post<QueryResult>("/api/query/datasource", {
            tableName: data.left_datasource ?? "",
            limit: 100,
            project_id: projectId,
            sql: data.sql_text || undefined,
          })
          .then((result) => setSavedQueryResult(result))
          .catch((err) => setSavedQueryError((err as Error).message))
          .finally(() => setSavedQueryLoading(false));
      }
    },
  });

  const deleteQueryMutation = useMutation({
    mutationFn: (queryId: number) =>
      apiClient.delete(`/api/projects/${projectId}/queries/${queryId}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["project-queries", projectId] }),
  });

  // ── Member mutations ──────────────────────────────────────────────

  const addMemberMutation = useMutation({
    mutationFn: (payload: { user_id: number; role: string }) =>
      apiClient.post(`/api/projects/${projectId}/members`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-members", projectId] });
      setAddUserId(null);
    },
  });

  const updateMemberRoleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: string }) =>
      apiClient.put(`/api/projects/${projectId}/members/${userId}/role`, { role }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["project-members", projectId] }),
  });

  const deactivateMemberMutation = useMutation({
    mutationFn: (userId: number) =>
      apiClient.put(`/api/projects/${projectId}/members/${userId}/deactivate`, {}),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["project-members", projectId] }),
  });

  const deleteMemberMutation = useMutation({
    mutationFn: (userId: number) =>
      apiClient.delete(`/api/projects/${projectId}/members/${userId}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["project-members", projectId] }),
  });

  // ── Click-to-execute saved query ─────────────────────────────────

  const executeSavedQuery = useCallback(async (q: SavedQuery) => {
    if (activeSavedQueryId === q.id) {
      setActiveSavedQueryId(null);
      setSavedQueryResult(null);
      setSavedQueryError(null);
      return;
    }
    setActiveSavedQueryId(q.id);
    setSavedQueryLoading(true);
    setSavedQueryError(null);
    setSavedQueryResult(null);
    try {
      const tableName = q.left_datasource ?? "";
      const result = await apiClient.post<QueryResult>("/api/query/datasource", {
        tableName,
        limit: 100,
        project_id: projectId,
        sql: q.sql_text || undefined,
      });
      setSavedQueryResult(result);
    } catch (err) {
      setSavedQueryError((err as Error).message);
    } finally {
      setSavedQueryLoading(false);
    }
  }, [activeSavedQueryId]);

  // ── Click-to-view datasource ──────────────────────────────────────

  const viewDatasource = useCallback(async (ds: Datasource) => {
    if (activeDsName === ds.viewName) {
      setActiveDsName(null);
      setDsResult(null);
      setDsError(null);
      return;
    }
    setActiveDsName(ds.viewName);
    setDsLoading(true);
    setDsError(null);
    setDsResult(null);
    try {
      const result = await apiClient.post<QueryResult>("/api/query/datasource", {
        tableName: ds.viewName,
        limit: 100,
        project_id: projectId,
      });
      setDsResult(result);
    } catch (err) {
      setDsError((err as Error).message);
    } finally {
      setDsLoading(false);
    }
  }, [activeDsName]);

  const [dsActionError, setDsActionError] = useState<string | null>(null);
  const [showAddDs, setShowAddDs] = useState(false);

  // ── File data source actions (item 1 archive, item 3 project link) ──
  const isFileSource = useCallback(
    (ds: Datasource) => ds.id == null && !!ds.viewName,
    [],
  );

  // Unified "remove from project" for files, databases and SaaS sources
  // (item 3). Only clears the project association; gated server-side to a
  // project admin or the datasource owner.
  const removeDatasourceFromProject = useCallback(
    async (ds: Datasource) => {
      if (
        !window.confirm(
          `Remove "${ds.fileName}" from this project? It stays in the owner's datasources.`,
        )
      ) {
        return;
      }
      setDsActionError(null);
      try {
        await apiClient.post(`/api/projects/${projectId}/datasources/remove`, {
          kind: ds.id != null ? "db" : "file",
          id: ds.id ?? undefined,
          viewName: ds.viewName,
        });
        queryClient.invalidateQueries({ queryKey: ["project-datasources", projectId] });
      } catch (err) {
        setDsActionError((err as Error).message);
      }
    },
    [queryClient, projectId],
  );

  // Item 5: drag a file onto a file datasource row to replace its data.
  const [dragOverView, setDragOverView] = useState<string | null>(null);
  const [replaceMsg, setReplaceMsg] = useState<string | null>(null);
  // Item 6: confirm before overwriting an existing datasource.
  const [pendingReplace, setPendingReplace] = useState<
    { ds: Datasource; file: File } | null
  >(null);
  const replaceFileFromDrop = useCallback(
    (ds: Datasource, files: FileList | null) => {
      setDragOverView(null);
      if (!files || files.length === 0) return;
      setDsActionError(null);
      setReplaceMsg(null);
      setPendingReplace({ ds, file: files[0] });
    },
    [],
  );
  const confirmReplace = useCallback(async () => {
    if (!pendingReplace) return;
    const { ds, file } = pendingReplace;
    setPendingReplace(null);
    setDsActionError(null);
    setReplaceMsg(null);
    try {
      const res = await apiClient.upload<{ addedColumns?: string[] }>(
        `/api/upload/datasources/${encodeURIComponent(ds.viewName)}/replace`,
        file,
      );
      const added = res.addedColumns ?? [];
      setReplaceMsg(
        `Replaced "${ds.fileName}"${added.length ? ` (added: ${added.join(", ")})` : ""}.`,
      );
      queryClient.invalidateQueries({ queryKey: ["project-datasources", projectId] });
    } catch (err) {
      setDsActionError((err as Error).message);
    }
  }, [pendingReplace, queryClient, projectId]);

  // ── Drag-and-drop handlers (for datasource row drag) ────────────

  const handleDragStart = useCallback(
    (e: DragEvent<HTMLDivElement>, ds: Datasource) => {
      e.dataTransfer.setData("application/json", JSON.stringify(ds));
      e.dataTransfer.effectAllowed = "copy";
    },
    []
  );

  // ── Permission checks ────────────────────────────────────────────

  const project = projectQuery.data;
  const isOwner = project?.owner_id === meta?.user_id;
  const isTenantAdmin = meta?.role === "admin";
  const myMembership = (membersQuery.data ?? []).find((m) => m.user_id === meta?.user_id);
  const myProjectRole = isOwner ? "owner" : (myMembership?.role ?? "viewer");
  const canManageMembers = isOwner || myProjectRole === "admin";
  const canEdit = isOwner || myProjectRole === "admin" || myProjectRole === "editor";
  // Item 3: only a project admin/owner (or tenant admin) — or the datasource's
  // own owner — may remove a datasource from the project.
  const isProjectAdmin = isOwner || myProjectRole === "admin" || isTenantAdmin;

  // ── Available users for member assignment ─────────────────────────

  const existingMemberIds = useMemo(
    () => new Set((membersQuery.data ?? []).map((m) => m.user_id)),
    [membersQuery.data]
  );

  const availableUsers = useMemo(
    () => (tenantUsersQuery.data ?? []).filter((u) => !existingMemberIds.has(u.id)),
    [tenantUsersQuery.data, existingMemberIds]
  );

  // ── Split members into active / inactive ──────────────────────────

  const { activeMembers, inactiveMembers } = useMemo(() => {
    const members = membersQuery.data ?? [];
    return {
      activeMembers: members.filter((m) => m.is_active),
      inactiveMembers: members.filter((m) => !m.is_active),
    };
  }, [membersQuery.data]);

  // ── Project datasources for query builder ─────────────────────────

  const projectDatasources = datasourcesQuery.data ?? [];

  // ── Render ────────────────────────────────────────────────────────

  if (projectQuery.isLoading) return <p>Loading project...</p>;
  if (projectQuery.error)
    return (
      <div>
        <p className="text-red-600">{(projectQuery.error as Error).message}</p>
        <button onClick={() => router.push("/projects")} className="mt-2 text-sm text-brand underline">
          Back to Projects
        </button>
      </div>
    );
  if (!project) return <p>Project not found.</p>;

  return (
    <section>
      {/* Header */}
      <header className="mb-6">
        <button
          onClick={() => router.push("/projects")}
          className="mb-2 text-sm text-slate-500 hover:text-slate-700"
        >
          &larr; Back to Projects
        </button>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">{project.name}</h1>
            {project.description && (
              <p className="mt-1 text-sm text-slate-500">{project.description}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {isOwner ? (
              <button
                onClick={() => toggleShareMutation.mutate(!project.is_shared)}
                disabled={toggleShareMutation.isPending}
                className={`relative inline-flex h-7 w-14 items-center rounded-full transition-colors ${
                  project.is_shared ? "bg-emerald-500" : "bg-slate-300"
                } disabled:opacity-50`}
                title={project.is_shared ? "Click to unshare" : "Click to share"}
              >
                <span
                  className="inline-block h-5 w-5 rounded-full bg-white shadow transition-transform"
                  style={{ transform: project.is_shared ? "translateX(30px)" : "translateX(4px)" }}
                />
              </button>
            ) : null}
            <span className={`text-xs font-medium ${
              project.is_shared ? "text-emerald-700" : "text-slate-500"
            }`}>
              {toggleShareMutation.isPending
                ? "Updating..."
                : project.is_shared ? "Shared" : "Private"}
            </span>
            {/* Scoping toggle */}
            <div className="ml-3 h-5 w-px bg-slate-200" />
            {isOwner ? (
              <button
                onClick={() => toggleScopingMutation.mutate(!project.scoping_enabled)}
                disabled={toggleScopingMutation.isPending || scopingLoading}
                className={`relative inline-flex h-7 w-14 items-center rounded-full transition-colors ${
                  project.scoping_enabled ? "bg-indigo-500" : "bg-slate-300"
                } disabled:opacity-50`}
                title={project.scoping_enabled ? "Click to disable scoping" : "Click to enable scoping"}
              >
                <span
                  className="inline-block h-5 w-5 rounded-full bg-white shadow transition-transform"
                  style={{ transform: project.scoping_enabled ? "translateX(30px)" : "translateX(4px)" }}
                />
              </button>
            ) : null}
            <span className={`text-xs font-medium ${
              project.scoping_enabled ? "text-indigo-700" : "text-slate-500"
            }`}>
              {toggleScopingMutation.isPending || scopingLoading
                ? "Updating..."
                : project.scoping_enabled ? "Scopes On" : "Scopes Off"}
            </span>
          </div>
        </div>
      </header>

      {/* Tabs */}
      <div className="mb-6 flex gap-1 rounded-lg bg-slate-100 p-1">
        {(["datasources", "queries", "dashboards", "scopes", "ai", "members"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => { setActiveTab(tab); setActiveDsName(null); setDsResult(null); setDsError(null); }}
            className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
              activeTab === tab
                ? "bg-white text-slate-900 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {tab === "ai" ? "AI" : tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* ── Datasources Tab ──────────────────────────────────────── */}
      {activeTab === "datasources" && (
        <div>
          {canEdit && (
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => setShowAddDs(true)}
                className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90"
              >
                + Add Datasource
              </button>
            </div>
          )}
          {showAddDs && (
            <AddDatasourceModal
              projectId={projectId}
              onClose={() => setShowAddDs(false)}
              onAdded={() =>
                queryClient.invalidateQueries({ queryKey: ["project-datasources", projectId] })
              }
            />
          )}
          {replaceMsg && <p className="mb-2 text-sm text-green-600">{replaceMsg}</p>}
          {datasourcesQuery.isLoading && <p className="text-sm text-slate-500">Loading datasources...</p>}
          {projectDatasources.length === 0 && !datasourcesQuery.isLoading && (
            <p className="text-sm text-slate-400">No datasources. Upload files or connect a database table.</p>
          )}
          {projectDatasources.length > 0 && (
            <div>
              <p className="mb-2 px-2 text-sm font-medium text-slate-700">
                All Datasources ({projectDatasources.length})
              </p>
            <div className="grid gap-2">
              {projectDatasources.map((ds) => (
                <div
                  key={ds.viewName}
                  draggable
                  onDragStart={(e) => handleDragStart(e, ds)}
                  onDragOver={
                    isFileSource(ds)
                      ? (e) => {
                          if (e.dataTransfer.types.includes("Files")) {
                            e.preventDefault();
                            setDragOverView(ds.viewName);
                          }
                        }
                      : undefined
                  }
                  onDragLeave={
                    isFileSource(ds) ? () => setDragOverView(null) : undefined
                  }
                  onDrop={
                    isFileSource(ds)
                      ? (e) => {
                          if (e.dataTransfer.files.length > 0) {
                            e.preventDefault();
                            replaceFileFromDrop(ds, e.dataTransfer.files);
                          }
                        }
                      : undefined
                  }
                  onClick={() => viewDatasource(ds)}
                  className={`flex items-center justify-between rounded-md border px-4 py-3 cursor-pointer transition-colors ${
                    dragOverView === ds.viewName
                      ? "border-brand border-dashed bg-brand/10 ring-2 ring-brand/30"
                      : activeDsName === ds.viewName
                      ? "border-brand bg-brand/5"
                      : "border-slate-200 bg-white hover:bg-slate-50"
                  }`}
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-slate-900">{ds.fileName}</p>
                      <SourceBadge ds={ds} />
                    </div>
                    <p className="text-xs text-slate-400 font-mono">View: {ds.viewName}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    {typeof ds.size === "number" && (
                      <span className="text-xs text-slate-400">{(ds.size / 1024).toFixed(1)} KB</span>
                    )}
                    <span className="text-xs text-slate-400">
                      {activeDsName === ds.viewName ? "Click to hide" : "Click to view"}
                    </span>
                    {(isProjectAdmin || ds.ownerId === meta?.user_id) && (
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); removeDatasourceFromProject(ds); }}
                        className="text-xs font-medium text-slate-500 hover:text-slate-800"
                        title="Remove this datasource from the project (keeps it in the owner's datasources)"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
            </div>
          )}
          {dsActionError && (
            <p className="mt-2 text-sm text-red-600">{dsActionError}</p>
          )}

          {/* Datasource data view — inline panel with close button */}
          {activeDsName && (
            <div className="mt-4 rounded-lg border border-slate-200 bg-white shadow-sm">
              <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2">
                <span className="text-sm font-medium text-slate-700">
                  {projectDatasources.find((d) => d.viewName === activeDsName)?.fileName ?? activeDsName}
                </span>
                <button
                  onClick={() => { setActiveDsName(null); setDsResult(null); setDsError(null); }}
                  className="rounded-md bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-200"
                >
                  Close
                </button>
              </div>
              <div className="p-4">
                {dsLoading && <p className="text-sm text-slate-500">Loading data...</p>}
                {dsError && <p className="text-sm text-red-600">{dsError}</p>}
                {dsResult && dsResult.rows.length > 0 && (
                  <DataGrid
                    columns={dsResult.columns}
                    rows={dsResult.rows}
                    columnTypes={
                      projectDatasources.find((d) => d.viewName === activeDsName)?.columnTypes
                    }
                  />
                )}
                {dsResult && dsResult.rows.length === 0 && (
                  <p className="text-sm text-slate-400">No data in this datasource.</p>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Queries Tab ──────────────────────────────────────────── */}
      {activeTab === "queries" && (
        <div>
          {!buildingQuery && canEdit && (
            <div className="mb-4 flex items-start gap-4">
              <button
                onClick={() => setBuildingQuery(true)}
                className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 whitespace-nowrap"
              >
                Create New Query
              </button>
              <div className="flex-1">
                <AIPromptBar
                  placeholder="Describe the query you want to generate…"
                  submitLabel="Generate Query"
                  onSubmit={handleAIGenerateQuery}
                  loading={aiQueryLoading}
                />
                {aiQueryError && (
                  <div className="mt-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{aiQueryError}</div>
                )}
                {aiQuerySuccess && (
                  <div className="mt-2 rounded-md bg-green-50 px-3 py-2 text-xs text-green-700">{aiQuerySuccess}</div>
                )}
              </div>
            </div>
          )}

          {/* Query Builder */}
          {buildingQuery && (
            <div className="mb-6">
              <QueryBuilder
                projectId={projectId}
                datasources={projectDatasources}
                onCancel={() => setBuildingQuery(false)}
                onSave={(payload) => {
                  createQueryMutation.mutate(payload);
                }}
                isSaving={createQueryMutation.isPending}
                initialSql=""
              />
            </div>
          )}

          {/* Saved queries list */}
          {queriesQuery.isLoading && <p className="text-sm text-slate-500">Loading queries...</p>}
          {queriesQuery.data && queriesQuery.data.length === 0 && !buildingQuery && (
            <p className="text-sm text-slate-400">No saved queries yet.</p>
          )}
          {queriesQuery.data && queriesQuery.data.length > 0 && (
            <div>
              <p className="mb-2 px-2 text-sm font-medium text-slate-700">
                All Queries ({queriesQuery.data.length})
              </p>
            <ul className="divide-y divide-slate-200 rounded-md border border-slate-200 bg-white">
              {queriesQuery.data.map((q) => (
                <li key={q.id} className="px-4 py-3">
                  <div
                    className={`flex items-center justify-between cursor-pointer rounded-md px-2 py-1 transition-colors ${
                      activeSavedQueryId === q.id
                        ? "bg-brand/5"
                        : "hover:bg-slate-50"
                    }`}
                    onClick={() => {
                      if (renamingId !== q.id) executeSavedQuery(q);
                    }}
                  >
                    {renamingId === q.id ? (
                      <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="text"
                          value={renameValue}
                          onChange={(e) => setRenameValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              renameQueryMutation.mutate({ queryId: q.id, name: renameValue });
                            } else if (e.key === "Escape") {
                              setRenamingId(null);
                            }
                          }}
                          className="rounded-md border border-slate-300 px-2 py-1 text-sm"
                          autoFocus
                        />
                        <button
                          onClick={() => renameQueryMutation.mutate({ queryId: q.id, name: renameValue })}
                          className="text-xs text-brand hover:text-brand/80"
                        >
                          Save
                        </button>
                      </div>
                    ) : (
                      <div
                        onDoubleClick={(e) => {
                          e.stopPropagation();
                          setRenamingId(q.id);
                          setRenameValue(q.name);
                        }}
                        title="Click to run query, double-click to rename"
                      >
                        <p className="text-sm font-medium text-slate-900">{q.name}</p>
                        {q.description && <p className="text-xs text-slate-500">{q.description}</p>}
                        {/* SQL preview removed for cleaner UI */}
                      </div>
                    )}
                    <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                      <span className="text-xs text-slate-400">
                        {q.join_type ?? "N/A"}
                      </span>
                      {canEdit && (
                        <button
                          onClick={() => setEditingQuery(editingQuery?.id === q.id ? null : q)}
                          className="text-xs text-blue-600 hover:text-blue-800"
                        >
                          Edit
                        </button>
                      )}
                      {canEdit && (
                        <button
                          onClick={() => {
                            if (confirm("Delete this query?")) {
                              deleteQueryMutation.mutate(q.id);
                            }
                          }}
                          className="text-xs text-red-500 hover:text-red-700"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Inline edit form */}
                  {editingQuery?.id === q.id && (
                    <div className="mt-3" onClick={(e) => e.stopPropagation()}>
                      <QueryBuilder
                        projectId={projectId}
                        datasources={projectDatasources}
                        editQuery={editingQuery}
                        onSave={(payload) => updateQueryMutation.mutate({ queryId: q.id, ...payload })}
                        onCancel={() => setEditingQuery(null)}
                        isSaving={updateQueryMutation.isPending}
                      />
                    </div>
                  )}

                  {/* Saved query results rendered underneath */}
                  {activeSavedQueryId === q.id && (
                    <div className="mt-3 ml-2">
                      {savedQueryLoading && (
                        <p className="text-sm text-slate-500">Executing query...</p>
                      )}
                      {savedQueryError && (
                        <p className="text-sm text-red-600">{savedQueryError}</p>
                      )}
                      {savedQueryResult && savedQueryResult.rows.length > 0 && (
                        <TanStackDataGrid
                          columns={savedQueryResult.columns}
                          rows={savedQueryResult.rows}
                          queryId={q.id}
                          queryName={q.name}
                          projectId={projectId}
                          availableQueries={(queriesQuery.data ?? []).map((sq) => ({
                            id: sq.id,
                            name: sq.name,
                            sql: sq.sql_text,
                            leftDatasource: sq.left_datasource,
                          }))}
                          canEditScopes={canEdit}
                          scopeEnabled={project?.scoping_enabled ?? false}
                        />
                      )}
                      {savedQueryResult && savedQueryResult.rows.length === 0 && (
                        <p className="text-sm text-slate-400">Query returned no results.</p>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
            </div>
          )}
        </div>
      )}

      {/* ── Dashboards Tab ────────────────────────────────────────── */}
      {activeTab === "dashboards" && (
        <DashboardTab
          projectId={projectId}
          savedQueries={(queriesQuery.data ?? []).map((q) => ({
            id: q.id,
            name: q.name,
            sql_text: q.sql_text,
          }))}
          datasources={projectDatasources.map((ds) => ({
            viewName: ds.viewName,
            fileName: ds.fileName,
          }))}
          canEdit={canEdit}
        />
      )}

      {/* ── Scopes Tab ────────────────────────────────────────── */}
      {activeTab === "scopes" && (
        <ScopesTab projectId={projectId} />
      )}

      {/* ── AI Tab ──────────────────────────────────────────────── */}
      {activeTab === "ai" && (
        <AIPanel
          projectId={projectId}
          onQuerySaved={() => queryClient.invalidateQueries({ queryKey: ["project-queries", projectId] })}
          onDashboardSaved={() => queryClient.invalidateQueries({ queryKey: ["project-dashboards", projectId] })}
          onScopeCreated={() => {}}
        />
      )}

      {/* ── Members Tab ──────────────────────────────────────────── */}
      {activeTab === "members" && (
        <div>
          {canManageMembers && (
            <div className="mb-4 rounded-lg border border-slate-200 bg-white p-4">
              <h3 className="mb-3 text-sm font-semibold text-slate-900">
                Assign Users
              </h3>
              <div className="flex items-end gap-3">
                <div className="flex-1">
                  <label className="block text-xs font-medium text-slate-600 mb-1">User</label>
                  <select
                    value={addUserId ?? ""}
                    onChange={(e) => setAddUserId(Number(e.target.value) || null)}
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  >
                    <option value="">Select user...</option>
                    {availableUsers.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.email} {u.display_name ? `(${u.display_name})` : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="w-32">
                  <label className="block text-xs font-medium text-slate-600 mb-1">Role</label>
                  <select
                    value={addRole}
                    onChange={(e) => setAddRole(e.target.value)}
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  >
                    <option value="viewer">Viewer</option>
                    <option value="editor">Editor</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
                <button
                  onClick={() => {
                    if (addUserId) {
                      addMemberMutation.mutate({ user_id: addUserId, role: addRole });
                    }
                  }}
                  disabled={!addUserId || addMemberMutation.isPending}
                  className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
                >
                  Add
                </button>
              </div>
            </div>
          )}

          {membersQuery.isLoading && <p className="text-sm text-slate-500">Loading members...</p>}

          {/* Active Members */}
          {activeMembers.length > 0 && (
            <div className="mb-4">
              <h4 className="mb-2 text-sm font-semibold text-slate-600">Active Members</h4>
              <ul className="divide-y divide-slate-200 rounded-md border border-slate-200 bg-white">
                {activeMembers.map((m) => (
                  <li key={m.user_id} className="flex items-center justify-between px-4 py-3">
                    <div>
                      <p className="text-sm font-medium text-slate-900">{m.email}</p>
                      {m.display_name && (
                        <p className="text-xs text-slate-500">{m.display_name}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      {canManageMembers && m.role !== "owner" ? (
                        <select
                          value={m.role}
                          onChange={(e) => updateMemberRoleMutation.mutate({ userId: m.user_id, role: e.target.value })}
                          className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs text-slate-700 cursor-pointer hover:border-slate-400"
                        >
                          <option value="viewer">Viewer</option>
                          <option value="editor">Editor</option>
                          <option value="admin">Admin</option>
                        </select>
                      ) : (
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                          {m.role}
                        </span>
                      )}
                      {canManageMembers && m.role !== "owner" && (
                        <button
                          onClick={() => deactivateMemberMutation.mutate(m.user_id)}
                          className="text-xs text-amber-600 hover:text-amber-800"
                        >
                          Deactivate
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Inactive Members */}
          {inactiveMembers.length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold text-slate-400">Inactive Members</h4>
              <ul className="divide-y divide-slate-200 rounded-md border border-slate-200 bg-white">
                {inactiveMembers.map((m) => (
                  <li key={m.user_id} className="flex items-center justify-between px-4 py-3 opacity-60">
                    <div>
                      <p className="text-sm font-medium text-slate-900">{m.email}</p>
                      {m.display_name && (
                        <p className="text-xs text-slate-500">{m.display_name}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-600">
                        inactive
                      </span>
                      {canManageMembers && (
                        <>
                          <button
                            onClick={() => addMemberMutation.mutate({ user_id: m.user_id, role: m.role })}
                            className="text-xs text-emerald-600 hover:text-emerald-800"
                          >
                            Reactivate
                          </button>
                          <button
                            onClick={() => {
                              if (confirm("Permanently remove this member? Their datasources will be moved back to their private folder.")) {
                                deleteMemberMutation.mutate(m.user_id);
                              }
                            }}
                            className="text-xs text-red-500 hover:text-red-700"
                          >
                            Remove
                          </button>
                        </>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {activeMembers.length === 0 && inactiveMembers.length === 0 && !membersQuery.isLoading && (
            <p className="text-sm text-slate-400">No members assigned yet.</p>
          )}
        </div>
      )}

      <ConfirmDialog
        open={pendingReplace !== null}
        title="Overwrite datasource?"
        message={
          pendingReplace ? (
            <>
              Are you sure you want to overwrite{" "}
              <span className="font-medium text-slate-900">
                &quot;{pendingReplace.ds.fileName}&quot;
              </span>{" "}
              with{" "}
              <span className="font-medium text-slate-900">
                &quot;{pendingReplace.file.name}&quot;
              </span>
              ? This replaces the existing data.
            </>
          ) : (
            ""
          )
        }
        confirmLabel="Yes"
        cancelLabel="Cancel"
        onConfirm={confirmReplace}
        onCancel={() => setPendingReplace(null)}
      />
    </section>
  );
}
