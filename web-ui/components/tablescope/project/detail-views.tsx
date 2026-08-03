"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  IconArrowLeft,
  IconFileText,
  IconDatabase,
  IconPencil,
  IconX,
} from "@tabler/icons-react";
import { DataGrid } from "@/components/data-grid/DataGrid";
import { TanStackDataGrid } from "@/components/data-grid/TanStackDataGrid";
import { DashboardViewer } from "@/components/dashboard/DashboardViewer";
import { QueryBuilder } from "@/components/query-builder/QueryBuilder";
import type { Dashboard as ViewerDashboard, WidgetConfig } from "@/components/dashboard/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiClient } from "@/lib/api-client";
import { timeAgo } from "@/lib/ui/format";
import {
  columnLabel,
  useProjectQueries,
  type SavedQuery,
  type DataSource,
  type Dashboard,
  type ProjectAsset,
} from "@/lib/ui/use-project-data";

type QueryResult = {
  columns: string[];
  rows: Record<string, unknown>[];
};

function safeTableName(name: string | null | undefined): string {
  return name && /^[A-Za-z0-9_][A-Za-z0-9_$.]*$/.test(name) ? name : "data";
}

export function DetailBackBar({
  label,
  onBack,
}: {
  label: string;
  onBack: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onBack}
      className="inline-flex items-center gap-1.5 text-small font-medium text-brand-700 hover:underline"
    >
      <IconArrowLeft size={15} />
      {label}
    </button>
  );
}

// ── Query result ─────────────────────────────────────────────────────

export function QueryResultView({
  projectId,
  query,
  backLabel,
  onBack,
  onEdit,
}: {
  projectId: string;
  query: SavedQuery;
  backLabel: string;
  onBack: () => void;
  onEdit?: () => void;
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["query-result", projectId, query.id],
    queryFn: () =>
      apiClient.post<QueryResult>("/api/query/datasource", {
        tableName: safeTableName(query.left_datasource),
        sql: query.sql_text,
        project_id: Number(projectId),
        limit: 500,
      }),
    enabled: Boolean(projectId),
    retry: false,
  });

  const { data: allQueries } = useProjectQueries(projectId);
  const availableQueries = (allQueries ?? []).map((q) => ({
    id: q.id,
    name: q.name,
    sql: q.sql_text,
    leftDatasource: q.left_datasource,
  }));

  return (
    <div className="space-y-4">
      <DetailBackBar label={backLabel} onBack={onBack} />
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-h1 text-ink-primary">{query.name}</h1>
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-small text-ink-tertiary">
            {query.ai_generated && <Badge tone="ai">AI generated</Badge>}
            {query.is_shared && <Badge tone="success">Shared</Badge>}
            <span>
              {query.left_datasource ?? "—"} · {query.run_count} runs
            </span>
          </p>
        </div>
        {onEdit && (
          <Button variant="secondary" size="sm" onClick={onEdit}>
            <IconPencil size={14} />
            Edit
          </Button>
        )}
      </header>

      <Card className="overflow-hidden p-0">
        {error ? (
          <div className="px-4 py-12 text-center text-small text-danger">
            {(error as Error).message || "Failed to run query."}
          </div>
        ) : (
          <TanStackDataGrid
            columns={data?.columns ?? []}
            rows={data?.rows ?? []}
            loading={isLoading}
            height={520}
            queryId={query.id}
            queryName={query.name}
            projectId={Number(projectId)}
            availableQueries={availableQueries}
            canEditScopes
          />
        )}
      </Card>
    </div>
  );
}

// ── Query builder (edit an existing saved query) ─────────────────────

export function QueryBuilderEdit({
  projectId,
  query,
  datasources,
  backLabel,
  onBack,
  onSaved,
}: {
  projectId: string;
  query: SavedQuery;
  datasources: DataSource[];
  backLabel: string;
  onBack: () => void;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const [lifecycleError, setLifecycleError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (payload: {
      name: string;
      description: string;
      left_datasource: string;
      right_datasource: string;
      join_type: string;
      left_column: string;
      right_column: string;
      sql_text: string;
    }) =>
      apiClient.put(`/api/projects/${projectId}/queries/${query.id}`, {
        name: payload.name,
        description: payload.description,
        left_datasource: payload.left_datasource || null,
        right_datasource: payload.right_datasource || null,
        join_type: payload.join_type || null,
        left_column: payload.left_column || null,
        right_column: payload.right_column || null,
        sql_text: payload.sql_text,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["project", projectId, "queries"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["query-result", projectId, query.id],
      });
      onSaved();
    },
  });

  const invalidateLists = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["project", projectId, "queries"],
    });
    await queryClient.invalidateQueries({
      queryKey: ["query-result", projectId, query.id],
    });
  };

  const archive = useMutation({
    mutationFn: () =>
      apiClient.post(
        `/api/projects/${projectId}/queries/${query.id}/archive`,
        {},
      ),
    onSuccess: async () => {
      setLifecycleError(null);
      await invalidateLists();
      onSaved();
    },
    onError: (e: Error) => setLifecycleError(e.message),
  });

  const restore = useMutation({
    mutationFn: () =>
      apiClient.post(
        `/api/projects/${projectId}/queries/${query.id}/restore`,
        {},
      ),
    onSuccess: async () => {
      setLifecycleError(null);
      await invalidateLists();
      onSaved();
    },
    onError: (e: Error) => setLifecycleError(e.message),
  });

  const remove = useMutation({
    mutationFn: () =>
      apiClient.delete(`/api/projects/${projectId}/queries/${query.id}`),
    onSuccess: async () => {
      setLifecycleError(null);
      await invalidateLists();
      onSaved();
    },
    onError: (e: Error) => setLifecycleError(e.message),
  });

  const handleDelete = () => {
    if (
      window.confirm(
        "Delete this archived query permanently? This cannot be undone.",
      )
    ) {
      remove.mutate();
    }
  };

  return (
    <div className="space-y-4">
      <DetailBackBar label={backLabel} onBack={onBack} />
      {lifecycleError && (
        <div className="rounded-lg border border-danger/30 bg-danger/5 px-4 py-2.5 text-small text-danger">
          {lifecycleError}
        </div>
      )}
      <QueryBuilder
        projectId={Number(projectId)}
        datasources={datasources.map((d) => ({
          fileName: d.fileName,
          viewName: d.viewName || d.fileName,
          sourceType: d.sourceType,
          dbType: d.dbType,
          connectorType: d.connectorType,
        }))}
        editQuery={{
          name: query.name,
          description: query.description ?? null,
          left_datasource: query.left_datasource ?? null,
          right_datasource: query.right_datasource ?? null,
          join_type: query.join_type ?? null,
          left_column: query.left_column ?? null,
          right_column: query.right_column ?? null,
          sql_text: query.sql_text ?? null,
        }}
        onCancel={onBack}
        onSave={(payload) => save.mutate(payload)}
        isSaving={save.isPending}
        saveLabel="Save changes"
        isArchived={query.is_archived}
        onArchive={() => archive.mutate()}
        onRestore={() => restore.mutate()}
        onDelete={handleDelete}
        lifecycleBusy={
          archive.isPending || restore.isPending || remove.isPending
        }
      />
    </div>
  );
}

// ── Query builder (create a new saved query) ─────────────────────────

export function QueryBuilderCreate({
  projectId,
  datasources,
  backLabel,
  onBack,
  onSaved,
}: {
  projectId: string;
  datasources: DataSource[];
  backLabel: string;
  onBack: () => void;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const create = useMutation({
    mutationFn: (payload: {
      name: string;
      description: string;
      left_datasource: string;
      right_datasource: string;
      join_type: string;
      left_column: string;
      right_column: string;
      sql_text: string;
    }) =>
      apiClient.post(`/api/projects/${projectId}/queries`, {
        name: payload.name,
        description: payload.description,
        left_datasource: payload.left_datasource || null,
        right_datasource: payload.right_datasource || null,
        join_type: payload.join_type || null,
        left_column: payload.left_column || null,
        right_column: payload.right_column || null,
        sql_text: payload.sql_text,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["project", projectId, "queries"],
      });
      onSaved();
    },
  });

  return (
    <div className="space-y-4">
      <DetailBackBar label={backLabel} onBack={onBack} />
      <QueryBuilder
        projectId={Number(projectId)}
        datasources={datasources.map((d) => ({
          fileName: d.fileName,
          viewName: d.viewName || d.fileName,
          sourceType: d.sourceType,
          dbType: d.dbType,
          connectorType: d.connectorType,
        }))}
        onCancel={onBack}
        onSave={(payload) => create.mutate(payload)}
        isSaving={create.isPending}
        saveLabel="Save query"
      />
    </div>
  );
}

// ── Data source rows ─────────────────────────────────────────────────

export function DataSourceResultView({
  projectId,
  source,
  backLabel,
  onBack,
}: {
  projectId: string;
  source: DataSource;
  backLabel: string;
  onBack: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const tableName = source.viewName || source.fileName;
  const { data, isLoading, error } = useQuery({
    queryKey: ["datasource-rows", projectId, tableName],
    queryFn: () =>
      apiClient.post<QueryResult>("/api/query/datasource", {
        tableName: safeTableName(tableName),
        project_id: Number(projectId),
        limit: 10000,
      }),
    enabled: Boolean(projectId && tableName),
    retry: false,
  });

  return (
    <div className="space-y-4">
      <DetailBackBar label={backLabel} onBack={onBack} />
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-bg-secondary text-ink-tertiary">
            <IconDatabase size={18} />
          </span>
          <div className="min-w-0">
            <h1 className="text-h1 text-ink-primary">{tableName}</h1>
            <p className="mt-0.5 text-small text-ink-tertiary">
              {source.columnTypes?.length ?? 0} columns
            </p>
          </div>
        </div>
        <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
          <IconPencil size={14} />
          Edit
        </Button>
      </header>

      {editing && (
        <ColumnTypeEditorModal
          projectId={projectId}
          source={source}
          onClose={() => setEditing(false)}
        />
      )}

      <Card className="overflow-hidden p-0">
        {error ? (
          <div className="px-4 py-12 text-center text-small text-danger">
            {(error as Error).message || "Failed to load rows."}
          </div>
        ) : (
          <DataGrid
            columns={data?.columns ?? []}
            rows={data?.rows ?? []}
            loading={isLoading}
            height={520}
          />
        )}
      </Card>
    </div>
  );
}

// ── Column-type editor modal ─────────────────────────────────────────

const FALLBACK_COLUMN_TYPES = [
  "string",
  "integer",
  "long",
  "short",
  "double",
  "float",
  "bigdecimal",
  "boolean",
  "date",
  "time",
  "timestamp",
  "varbinary",
];

function ColumnTypeEditorModal({
  projectId,
  source,
  onClose,
}: {
  projectId: string;
  source: DataSource;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const initial = (source.columnTypes ?? []).map((c) => columnLabel(c));
  const [types, setTypes] = useState<Record<string, string>>(() =>
    Object.fromEntries(initial.map((c) => [c.name, c.type || "string"])),
  );
  const [error, setError] = useState<string | null>(null);

  const { data: typeOptions } = useQuery({
    queryKey: ["column-types", projectId],
    queryFn: () =>
      apiClient.get<string[]>(
        `/api/projects/${projectId}/datasources/column-types`,
      ),
  });
  const options = typeOptions ?? FALLBACK_COLUMN_TYPES;

  const save = useMutation({
    mutationFn: () =>
      apiClient.put(`/api/projects/${projectId}/datasources/columns`, {
        kind: source.id != null ? "db" : "file",
        id: source.id,
        viewName: source.viewName || source.fileName,
        columns: initial.map((c) => ({
          name: c.name,
          type: types[c.name] || c.type || "string",
        })),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["project", projectId, "datasources"],
      });
      onClose();
    },
    onError: (e) =>
      setError(e instanceof Error ? e.message : "Failed to save column types"),
  });

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-lg bg-bg-primary shadow-xl">
        <div className="flex items-center justify-between border-b border-line-tertiary px-5 py-3.5">
          <h2 className="text-h2 text-ink-primary">Edit column types</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-ink-tertiary hover:bg-bg-secondary"
            aria-label="Close"
          >
            <IconX size={18} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <p className="mb-3 text-small text-ink-tertiary">
            Choose a type for each column. Saving rebuilds and redeploys the VDB.
          </p>
          {initial.length === 0 ? (
            <div className="py-8 text-center text-small text-ink-tertiary">
              No columns available to edit for this source.
            </div>
          ) : (
            <div className="space-y-2">
              {initial.map((c) => (
                <div
                  key={c.name}
                  className="flex items-center justify-between gap-3"
                >
                  <span className="min-w-0 flex-1 truncate text-[13px] text-ink-primary">
                    {c.name}
                  </span>
                  <select
                    value={types[c.name] ?? "string"}
                    onChange={(e) =>
                      setTypes((prev) => ({ ...prev, [c.name]: e.target.value }))
                    }
                    className="h-8 rounded-md border border-line-secondary bg-bg-primary px-2 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
                  >
                    {options.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          )}
          {error && (
            <div className="mt-3 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-small text-danger">
              {error}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-line-tertiary px-5 py-3">
          <Button variant="secondary" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              setError(null);
              save.mutate();
            }}
            disabled={save.isPending || initial.length === 0}
          >
            {save.isPending ? "Saving…" : "Save columns"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Dashboard content ────────────────────────────────────────────────

export function DashboardDetailView({
  projectId,
  dashboard,
  savedQueries,
  datasources,
  onBack,
  onPersisted,
  onPinWidget,
}: {
  projectId: string;
  dashboard: Dashboard;
  savedQueries: SavedQuery[];
  datasources: DataSource[];
  onBack: () => void;
  onPersisted?: () => void;
  onPinWidget?: (widget: WidgetConfig, data: unknown[], dashboardId: number) => void;
}) {
  return (
    <DashboardViewer
      dashboard={dashboard as unknown as ViewerDashboard}
      projectId={Number(projectId)}
      savedQueries={savedQueries.map((q) => ({
        id: q.id,
        name: q.name,
        sql_text: q.sql_text,
      }))}
      datasources={datasources.map((d) => ({
        viewName: d.viewName || d.fileName,
        fileName: d.fileName,
      }))}
      onBack={onBack}
      onPersisted={onPersisted}
      onPinWidget={onPinWidget}
    />
  );
}

// ── Document detail (full metadata) ──────────────────────────────────

type AITag = { tag_key?: string; display_name?: string; confidence?: number };
type AIEntity = {
  entity_type?: string;
  name?: string;
  evidence?: string;
};
type AIKpi = { kpi_key?: string; display_name?: string; reason?: string };
type DocFamily = {
  family_name?: string;
  family_type?: string;
  role?: string;
  reason?: string;
  confidence?: number;
  auto_link?: boolean;
};

function humanSize(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function MetaSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h3 className="text-caption uppercase tracking-wide text-ink-tertiary">
        {title}
      </h3>
      <div className="mt-1.5">{children}</div>
    </div>
  );
}

export function DocumentDetailView({
  asset,
  backLabel,
  onBack,
}: {
  asset: ProjectAsset;
  backLabel: string;
  onBack: () => void;
}) {
  const meta = (asset.ai_metadata ?? {}) as Record<string, unknown>;
  const tags = (meta.tags ?? []) as AITag[];
  const entities = (meta.entities ?? []) as AIEntity[];
  const kpis = (meta.recommended_kpis ?? []) as AIKpi[];
  const questions = (meta.suggested_questions ?? []) as string[];
  const domain = typeof meta.business_domain === "string" ? meta.business_domain : null;
  const docType = typeof meta.document_type === "string" ? meta.document_type : null;
  const family = (meta.document_family ?? null) as DocFamily | null;
  const type =
    asset.file_extension?.replace(".", "").toUpperCase() ||
    asset.asset_type.toUpperCase();

  return (
    <div className="space-y-4">
      <DetailBackBar label={backLabel} onBack={onBack} />

      <header className="flex items-start gap-2.5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-bg-secondary text-ink-tertiary">
          <IconFileText size={18} />
        </span>
        <div className="min-w-0">
          <h1 className="text-h1 text-ink-primary">{asset.title}</h1>
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-small text-ink-tertiary">
            <Badge tone="neutral">{type}</Badge>
            <span>{humanSize(asset.file_size_bytes)}</span>
            <span>· Uploaded {timeAgo(asset.created_at)}</span>
          </p>
        </div>
      </header>

      {asset.ai_summary && (
        <Card className="space-y-1.5 p-4">
          <MetaSection title="AI Summary">
            <p className="text-[13px] leading-relaxed text-ink-primary">
              {asset.ai_summary}
            </p>
          </MetaSection>
        </Card>
      )}

      {family && (
        <Card className="space-y-1 p-4">
          <MetaSection title="Document Family">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[13px] font-medium text-ink-primary">
                {family.family_name}
              </span>
              {family.auto_link != null && (
                <Badge tone={family.auto_link ? "success" : "warning"}>
                  {family.auto_link ? "Linked" : "Suggested"}
                </Badge>
              )}
              {family.confidence != null && (
                <span className="text-small text-ink-tertiary">
                  {Math.round(family.confidence * 100)}%
                </span>
              )}
            </div>
            {(family.family_type || family.role) && (
              <p className="mt-1 text-small text-ink-tertiary">
                {[family.family_type, family.role]
                  .filter((v) => v && v !== "unknown")
                  .map((v) => v!.replace(/_/g, " "))
                  .join(" · ")}
              </p>
            )}
            {family.reason && (
              <p className="mt-1 text-small text-ink-tertiary">{family.reason}</p>
            )}
          </MetaSection>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {(docType || domain) && (
          <Card className="space-y-2 p-4">
            {docType && (
              <MetaSection title="Document Type">
                <p className="text-[13px] text-ink-primary">{docType}</p>
              </MetaSection>
            )}
            {domain && (
              <MetaSection title="Business Domain">
                <p className="text-[13px] text-ink-primary">{domain}</p>
              </MetaSection>
            )}
          </Card>
        )}

        {tags.length > 0 && (
          <Card className="p-4">
            <MetaSection title="Tags">
              <div className="flex flex-wrap gap-1.5">
                {tags.map((t, i) => (
                  <Badge key={i} tone="outline">
                    {t.display_name ?? t.tag_key}
                  </Badge>
                ))}
              </div>
            </MetaSection>
          </Card>
        )}

        {kpis.length > 0 && (
          <Card className="p-4">
            <MetaSection title="Recommended KPIs">
              <ul className="space-y-1 text-[13px] text-ink-secondary">
                {kpis.map((k, i) => (
                  <li key={i}>
                    <span className="text-ink-primary">
                      {k.display_name ?? k.kpi_key}
                    </span>
                    {k.reason && (
                      <span className="text-ink-tertiary"> — {k.reason}</span>
                    )}
                  </li>
                ))}
              </ul>
            </MetaSection>
          </Card>
        )}

        {entities.length > 0 && (
          <Card className="p-4">
            <MetaSection title="Entities">
              <ul className="space-y-1 text-[13px] text-ink-secondary">
                {entities.map((e, i) => (
                  <li key={i} className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-bg-secondary px-1.5 py-0.5 text-small font-medium text-ink-tertiary">
                      {e.entity_type}
                    </span>
                    <span className="text-ink-primary">{e.name}</span>
                  </li>
                ))}
              </ul>
            </MetaSection>
          </Card>
        )}
      </div>

      {questions.length > 0 && (
        <Card className="p-4">
          <MetaSection title="Suggested Questions">
            <ul className="space-y-1 text-[13px] text-ink-secondary">
              {questions.map((q, i) => (
                <li key={i} className="flex items-start gap-1.5">
                  <span className="text-ink-tertiary">•</span>
                  {q}
                </li>
              ))}
            </ul>
          </MetaSection>
        </Card>
      )}
    </div>
  );
}

// ── Editable query preview (right rail) ──────────────────────────────

export function QueryEditor({
  projectId,
  query,
  onClose,
}: {
  projectId: string;
  query: SavedQuery;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(query.name);
  const [sql, setSql] = useState(query.sql_text ?? "");
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () =>
      apiClient.put(`/api/projects/${projectId}/queries/${query.id}`, {
        name,
        sql_text: sql,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "queries"],
      });
      setError(null);
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div className="space-y-2">
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="h-8 w-full rounded-md border border-line-secondary bg-bg-primary px-2.5 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
      />
      <textarea
        value={sql}
        onChange={(e) => setSql(e.target.value)}
        rows={8}
        spellCheck={false}
        className="w-full resize-y rounded-lg border border-line-secondary bg-[#1e1b2e] p-3 font-code text-[12px] leading-relaxed text-[#d6d3e8] focus:border-brand-500 focus:outline-none"
      />
      {error && <p className="text-small text-danger">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button variant="secondary" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={() => save.mutate()}
          disabled={save.isPending || !name.trim()}
        >
          {save.isPending ? "Saving…" : "Save"}
        </Button>
      </div>
    </div>
  );
}
