"use client";

import { useState, useCallback, useMemo, DragEvent } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { getUserMeta } from "@/lib/auth";

// ── Types ───────────────────────────────────────────────────────────

type Project = {
  id: number;
  name: string;
  description: string | null;
  is_shared: boolean;
  owner_id: number | null;
};

type Datasource = {
  fileName: string;
  viewName: string;
  size: number;
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

// ── Join types ──────────────────────────────────────────────────────

const JOIN_TYPES = [
  { value: "INNER JOIN", label: "Inner Join" },
  { value: "LEFT JOIN", label: "Left Join" },
  { value: "RIGHT JOIN", label: "Right Join" },
  { value: "FULL OUTER JOIN", label: "Full Outer Join" },
  { value: "CROSS JOIN", label: "Cross Join" },
];

// ── Main Component ──────────────────────────────────────────────────

export default function ProjectWorkspacePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const projectId = Number(params.id);
  const meta = getUserMeta();

  // ── Tab state ─────────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<"datasources" | "queries" | "members">("datasources");

  // ── Query builder state ───────────────────────────────────────────
  const [buildingQuery, setBuildingQuery] = useState(false);
  const [leftDs, setLeftDs] = useState<Datasource | null>(null);
  const [rightDs, setRightDs] = useState<Datasource | null>(null);
  const [showJoinDialog, setShowJoinDialog] = useState(false);
  const [joinType, setJoinType] = useState("INNER JOIN");
  const [leftCol, setLeftCol] = useState("");
  const [rightCol, setRightCol] = useState("");
  const [leftCols, setLeftCols] = useState<string[]>([]);
  const [rightCols, setRightCols] = useState<string[]>([]);

  // ── Save dialog ───────────────────────────────────────────────────
  const [showSave, setShowSave] = useState(false);
  const [queryName, setQueryName] = useState("");
  const [queryDesc, setQueryDesc] = useState("");

  // ── Inline rename ─────────────────────────────────────────────────
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");

  // ── Query execution result ────────────────────────────────────────
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [executing, setExecuting] = useState(false);

  // ── Member assignment ─────────────────────────────────────────────
  const [addUserId, setAddUserId] = useState<number | null>(null);
  const [addRole, setAddRole] = useState("member");

  // ── Data fetching ─────────────────────────────────────────────────

  const projectQuery = useQuery<Project>({
    queryKey: ["project", projectId],
    queryFn: () => apiClient.get<Project>(`/api/projects/${projectId}`),
  });

  const datasourcesQuery = useQuery<Datasource[]>({
    queryKey: ["datasources"],
    queryFn: () => apiClient.get<Datasource[]>("/api/upload/datasources"),
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

  const shareMutation = useMutation({
    mutationFn: (filenames: string[]) =>
      apiClient.post("/api/sharing/share", {
        projectId,
        filenames,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const unshareMutation = useMutation({
    mutationFn: () =>
      apiClient.put(`/api/projects/${projectId}`, { is_shared: false }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
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
      setLeftDs(null);
      setRightDs(null);
      setShowSave(false);
      setShowJoinDialog(false);
      setQueryName("");
      setQueryDesc("");
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

  const removeMemberMutation = useMutation({
    mutationFn: (userId: number) =>
      apiClient.delete(`/api/projects/${projectId}/members/${userId}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["project-members", projectId] }),
  });

  // ── Column fetching ───────────────────────────────────────────────

  const fetchColumns = useCallback(async (viewName: string): Promise<string[]> => {
    try {
      const result = await apiClient.post<QueryResult>("/api/query/datasource", {
        tableName: viewName,
        limit: 1,
      });
      return result.columns;
    } catch {
      return [];
    }
  }, []);

  // ── Drag-and-drop handlers ────────────────────────────────────────

  const handleDragStart = useCallback(
    (e: DragEvent<HTMLDivElement>, ds: Datasource) => {
      e.dataTransfer.setData("application/json", JSON.stringify(ds));
      e.dataTransfer.effectAllowed = "copy";
    },
    []
  );

  const handleDropLeft = useCallback(
    async (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      const data = e.dataTransfer.getData("application/json");
      if (!data) return;
      const ds: Datasource = JSON.parse(data);
      setLeftDs(ds);
      const cols = await fetchColumns(ds.viewName);
      setLeftCols(cols);
      if (rightDs) setShowJoinDialog(true);
    },
    [rightDs, fetchColumns]
  );

  const handleDropRight = useCallback(
    async (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      const data = e.dataTransfer.getData("application/json");
      if (!data) return;
      const ds: Datasource = JSON.parse(data);
      setRightDs(ds);
      const cols = await fetchColumns(ds.viewName);
      setRightCols(cols);
      if (leftDs) setShowJoinDialog(true);
    },
    [leftDs, fetchColumns]
  );

  const allowDrop = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }, []);

  // ── Build SQL from join config ────────────────────────────────────

  const generatedSql = useMemo(() => {
    if (!leftDs || !rightDs) return "";
    const l = `"${leftDs.viewName}"`;
    const r = `"${rightDs.viewName}"`;
    if (joinType === "CROSS JOIN") {
      return `SELECT * FROM ${l} ${joinType} ${r}`;
    }
    if (!leftCol || !rightCol) return "";
    return `SELECT * FROM ${l} ${joinType} ${r} ON ${l}."${leftCol}" = ${r}."${rightCol}"`;
  }, [leftDs, rightDs, joinType, leftCol, rightCol]);

  // ── Execute query ─────────────────────────────────────────────────

  const executeQuery = useCallback(
    async (sql: string) => {
      setExecuting(true);
      setQueryError(null);
      setQueryResult(null);
      try {
        const result = await apiClient.post<QueryResult>("/api/query/datasource", {
          tableName: leftDs?.viewName ?? "",
          limit: 100,
        });
        setQueryResult(result);
      } catch (err) {
        setQueryError((err as Error).message);
      } finally {
        setExecuting(false);
      }
    },
    [leftDs]
  );

  // ── Permission checks ────────────────────────────────────────────

  const project = projectQuery.data;
  const isOwner = project?.owner_id === meta?.user_id;
  const isAdmin = meta?.role === "admin";
  const canManageMembers = isOwner || isAdmin;

  // ── Available users for member assignment ─────────────────────────

  const existingMemberIds = useMemo(
    () => new Set((membersQuery.data ?? []).map((m) => m.user_id)),
    [membersQuery.data]
  );

  const availableUsers = useMemo(
    () => (tenantUsersQuery.data ?? []).filter((u) => !existingMemberIds.has(u.id)),
    [tenantUsersQuery.data, existingMemberIds]
  );

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
            {project.is_shared ? (
              <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
                Shared
              </span>
            ) : (
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                Private
              </span>
            )}
            {isOwner && !project.is_shared && (
              <button
                onClick={() => {
                  const files = (datasourcesQuery.data ?? []).map((d) => d.fileName);
                  shareMutation.mutate(files);
                }}
                disabled={shareMutation.isPending}
                className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
              >
                {shareMutation.isPending ? "Sharing..." : "Share Project"}
              </button>
            )}
            {isOwner && project.is_shared && (
              <button
                onClick={() => unshareMutation.mutate()}
                disabled={unshareMutation.isPending}
                className="rounded-md bg-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-300 disabled:opacity-50"
              >
                {unshareMutation.isPending ? "Unsharing..." : "Unshare"}
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Tabs */}
      <div className="mb-6 flex gap-1 rounded-lg bg-slate-100 p-1">
        {(["datasources", "queries", "members"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
              activeTab === tab
                ? "bg-white text-slate-900 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* ── Datasources Tab ──────────────────────────────────────── */}
      {activeTab === "datasources" && (
        <div>
          {datasourcesQuery.isLoading && <p className="text-sm text-slate-500">Loading datasources...</p>}
          {datasourcesQuery.data && datasourcesQuery.data.length === 0 && (
            <p className="text-sm text-slate-400">No datasources. Upload files first.</p>
          )}
          {datasourcesQuery.data && datasourcesQuery.data.length > 0 && (
            <div className="grid gap-2">
              {datasourcesQuery.data.map((ds) => (
                <div
                  key={ds.viewName}
                  draggable
                  onDragStart={(e) => handleDragStart(e, ds)}
                  className="flex items-center justify-between rounded-md border border-slate-200 bg-white px-4 py-3 cursor-grab active:cursor-grabbing hover:bg-slate-50"
                >
                  <div>
                    <p className="text-sm font-medium text-slate-900">{ds.fileName}</p>
                    <p className="text-xs text-slate-400 font-mono">View: {ds.viewName}</p>
                  </div>
                  <span className="text-xs text-slate-400">{(ds.size / 1024).toFixed(1)} KB</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Queries Tab ──────────────────────────────────────────── */}
      {activeTab === "queries" && (
        <div>
          {!buildingQuery && (
            <button
              onClick={() => setBuildingQuery(true)}
              className="mb-4 rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90"
            >
              Create New Query
            </button>
          )}

          {/* Query Builder */}
          {buildingQuery && (
            <div className="mb-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-medium text-slate-900">Query Builder</h3>
                <button
                  onClick={() => {
                    setBuildingQuery(false);
                    setLeftDs(null);
                    setRightDs(null);
                    setShowJoinDialog(false);
                    setShowSave(false);
                  }}
                  className="text-sm text-slate-500 hover:text-slate-700"
                >
                  Cancel
                </button>
              </div>
              <p className="mb-4 text-sm text-slate-500">
                Drag datasources from the Datasources tab into the boxes below.
              </p>

              <div className="grid grid-cols-2 gap-4 mb-4">
                {/* Left box */}
                <div
                  onDrop={handleDropLeft}
                  onDragOver={allowDrop}
                  className={`flex min-h-[120px] items-center justify-center rounded-lg border-2 border-dashed p-4 transition-colors ${
                    leftDs
                      ? "border-brand bg-brand/5"
                      : "border-slate-300 hover:border-slate-400"
                  }`}
                >
                  {leftDs ? (
                    <div className="text-center">
                      <p className="text-sm font-medium text-slate-900">{leftDs.fileName}</p>
                      <p className="text-xs text-slate-400 font-mono">{leftDs.viewName}</p>
                      <button
                        onClick={() => {
                          setLeftDs(null);
                          setLeftCols([]);
                          setShowJoinDialog(false);
                        }}
                        className="mt-2 text-xs text-red-500 hover:text-red-700"
                      >
                        Remove
                      </button>
                    </div>
                  ) : (
                    <p className="text-sm text-slate-400">Drop left datasource here</p>
                  )}
                </div>

                {/* Right box */}
                <div
                  onDrop={handleDropRight}
                  onDragOver={allowDrop}
                  className={`flex min-h-[120px] items-center justify-center rounded-lg border-2 border-dashed p-4 transition-colors ${
                    rightDs
                      ? "border-brand bg-brand/5"
                      : "border-slate-300 hover:border-slate-400"
                  }`}
                >
                  {rightDs ? (
                    <div className="text-center">
                      <p className="text-sm font-medium text-slate-900">{rightDs.fileName}</p>
                      <p className="text-xs text-slate-400 font-mono">{rightDs.viewName}</p>
                      <button
                        onClick={() => {
                          setRightDs(null);
                          setRightCols([]);
                          setShowJoinDialog(false);
                        }}
                        className="mt-2 text-xs text-red-500 hover:text-red-700"
                      >
                        Remove
                      </button>
                    </div>
                  ) : (
                    <p className="text-sm text-slate-400">Drop right datasource here</p>
                  )}
                </div>
              </div>

              {/* Join Parameters Dialog (Tableau-like) */}
              {showJoinDialog && leftDs && rightDs && (
                <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4">
                  <h4 className="mb-3 text-sm font-semibold text-blue-900">
                    Join Configuration
                  </h4>
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        Left Column ({leftDs.fileName})
                      </label>
                      <select
                        value={leftCol}
                        onChange={(e) => setLeftCol(e.target.value)}
                        className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                      >
                        <option value="">Select column...</option>
                        {leftCols.map((c) => (
                          <option key={c} value={c}>{c}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        Join Type
                      </label>
                      <select
                        value={joinType}
                        onChange={(e) => setJoinType(e.target.value)}
                        className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                      >
                        {JOIN_TYPES.map((jt) => (
                          <option key={jt.value} value={jt.value}>{jt.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        Right Column ({rightDs.fileName})
                      </label>
                      <select
                        value={rightCol}
                        onChange={(e) => setRightCol(e.target.value)}
                        className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                      >
                        <option value="">Select column...</option>
                        {rightCols.map((c) => (
                          <option key={c} value={c}>{c}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {generatedSql && (
                    <div className="mt-3 rounded bg-slate-800 p-3">
                      <p className="text-xs font-mono text-slate-300 break-all">{generatedSql}</p>
                    </div>
                  )}

                  <div className="mt-3 flex gap-2">
                    <button
                      onClick={() => setShowSave(true)}
                      disabled={!generatedSql}
                      className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
                    >
                      Save
                    </button>
                    <button
                      onClick={() => executeQuery(generatedSql)}
                      disabled={!generatedSql || executing}
                      className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                    >
                      {executing ? "Executing..." : "Execute"}
                    </button>
                  </div>
                </div>
              )}

              {/* Save Dialog */}
              {showSave && (
                <div className="mb-4 rounded-lg border border-slate-200 bg-white p-4">
                  <h4 className="mb-3 text-sm font-semibold text-slate-900">Save Query</h4>
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        Query Name
                      </label>
                      <input
                        type="text"
                        value={queryName}
                        onChange={(e) => setQueryName(e.target.value)}
                        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                        placeholder="My Query"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        Description
                      </label>
                      <textarea
                        value={queryDesc}
                        onChange={(e) => setQueryDesc(e.target.value)}
                        rows={2}
                        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                        placeholder="Optional description"
                      />
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          createQueryMutation.mutate({
                            name: queryName,
                            description: queryDesc,
                            left_datasource: leftDs?.viewName ?? "",
                            right_datasource: rightDs?.viewName ?? "",
                            join_type: joinType,
                            left_column: leftCol,
                            right_column: rightCol,
                            sql_text: generatedSql,
                          });
                        }}
                        disabled={!queryName.trim() || createQueryMutation.isPending}
                        className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
                      >
                        {createQueryMutation.isPending ? "Saving..." : "Save Query"}
                      </button>
                      <button
                        onClick={() => setShowSave(false)}
                        className="rounded-md bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Execution results */}
              {queryError && <p className="text-sm text-red-600 mb-4">{queryError}</p>}
              {queryResult && queryResult.rows.length > 0 && (
                <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
                  <table className="min-w-full divide-y divide-slate-200">
                    <thead className="bg-slate-50">
                      <tr>
                        {queryResult.columns.map((col) => (
                          <th key={col} className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {queryResult.rows.slice(0, 50).map((row, i) => (
                        <tr key={i}>
                          {queryResult.columns.map((col) => (
                            <td key={col} className="whitespace-nowrap px-3 py-2 text-sm text-slate-700">
                              {String(row[col] ?? "")}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {queryResult.rows.length > 50 && (
                    <p className="px-3 py-2 text-xs text-slate-400">
                      Showing first 50 of {queryResult.rows.length} rows
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Saved queries list */}
          {queriesQuery.isLoading && <p className="text-sm text-slate-500">Loading queries...</p>}
          {queriesQuery.data && queriesQuery.data.length === 0 && !buildingQuery && (
            <p className="text-sm text-slate-400">No saved queries yet.</p>
          )}
          {queriesQuery.data && queriesQuery.data.length > 0 && (
            <ul className="divide-y divide-slate-200 rounded-md border border-slate-200 bg-white">
              {queriesQuery.data.map((q) => (
                <li key={q.id} className="px-4 py-3">
                  <div className="flex items-center justify-between">
                    {renamingId === q.id ? (
                      <div className="flex items-center gap-2">
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
                        onDoubleClick={() => {
                          setRenamingId(q.id);
                          setRenameValue(q.name);
                        }}
                        className="cursor-pointer"
                        title="Double-click to rename"
                      >
                        <p className="text-sm font-medium text-slate-900">{q.name}</p>
                        {q.description && <p className="text-xs text-slate-500">{q.description}</p>}
                        {q.sql_text && (
                          <p className="mt-1 text-xs font-mono text-slate-400 truncate max-w-md">
                            {q.sql_text}
                          </p>
                        )}
                      </div>
                    )}
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-slate-400">
                        {q.join_type ?? "N/A"}
                      </span>
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
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
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
                    <option value="member">Member</option>
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
          {membersQuery.data && membersQuery.data.length === 0 && (
            <p className="text-sm text-slate-400">No members assigned yet.</p>
          )}
          {membersQuery.data && membersQuery.data.length > 0 && (
            <ul className="divide-y divide-slate-200 rounded-md border border-slate-200 bg-white">
              {membersQuery.data.map((m) => (
                <li key={m.user_id} className="flex items-center justify-between px-4 py-3">
                  <div>
                    <p className="text-sm font-medium text-slate-900">{m.email}</p>
                    {m.display_name && (
                      <p className="text-xs text-slate-500">{m.display_name}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                      {m.role}
                    </span>
                    {canManageMembers && m.role !== "owner" && (
                      <button
                        onClick={() => removeMemberMutation.mutate(m.user_id)}
                        className="text-xs text-red-500 hover:text-red-700"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
