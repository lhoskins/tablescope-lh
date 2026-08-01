"use client";

import { useMemo, useRef, useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconRefresh,
  IconDatabase,
  IconFileSpreadsheet,
  IconApi,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { ConnectorsMenu } from "@/components/datasource/ConnectorsMenu";

import {
  ContextPanel,
  ContextSection,
} from "@/components/tablescope/context-panel";
import { StatTile } from "@/components/ui/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { DataSourceUpdateDialog } from "@/components/tablescope/project/data-source-update-dialog";
import {
  activateSourceVersion,
  listSourceVersions,
  preflightSourceUpdate,
  rollbackSourceVersion,
  type PreflightResponse,
  type SourceVersion,
} from "@/lib/api/data-source-versions";
import {
  useProjectDataSources,
  columnLabel,
  type DataSource,
} from "@/lib/ui/use-project-data";
import { metaList } from "@/lib/ui/ai-meta";
import { DataSourceResultView } from "@/components/tablescope/project/detail-views";

function isDatabase(s: DataSource): boolean {
  return s.sourceType === "database_table";
}
function isSaas(s: DataSource): boolean {
  return s.sourceType === "saas_object";
}

function sourceTypeLabel(s: DataSource): string {
  if (isDatabase(s)) return s.dbType ? `${s.dbType} table` : "Database table";
  if (isSaas(s)) return s.connectorType ? `${s.connectorType} object` : "SaaS object";
  return s.sourceType || "File";
}

function SourceIcon({ source }: { source: DataSource }) {
  const Icon = isDatabase(source)
    ? IconDatabase
    : isSaas(source)
      ? IconApi
      : IconFileSpreadsheet;
  return (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-bg-secondary text-ink-secondary">
      <Icon size={18} />
    </span>
  );
}

function humanSize(bytes: number | null): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DataSourcesScreen({ projectId }: { projectId: string }) {
  const { data, isLoading } = useProjectDataSources(projectId);
  const queryClient = useQueryClient();
  const rows = useMemo(
    () => (data ?? []).filter((s) => !s.archived),
    [data],
  );
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detailKey, setDetailKey] = useState<string | null>(null);

  // ── Update a source (drag-to-drop or the accessible Update action) ──
  // Both entry points stage the file and open the same preflight; neither one
  // touches the live version before the user confirms.
  const [dragOverKey, setDragOverKey] = useState<string | null>(null);
  const [updateTarget, setUpdateTarget] = useState<DataSource | null>(null);
  const [preflight, setPreflight] = useState<PreflightResponse | null>(null);
  const [updateError, setUpdateError] = useState<string | null>(null);
  const [activating, setActivating] = useState(false);
  const [replaceMsg, setReplaceMsg] = useState<string | null>(null);
  const pickerRef = useRef<HTMLInputElement>(null);
  const pickerSource = useRef<DataSource | null>(null);

  const startUpdate = useCallback(
    async (source: DataSource, files: FileList | null) => {
      setDragOverKey(null);
      if (!files || files.length === 0) return;
      setUpdateTarget(source);
      setPreflight(null);
      setUpdateError(null);
      setReplaceMsg(null);
      try {
        setPreflight(await preflightSourceUpdate(source.viewName, files[0]));
      } catch (err) {
        setUpdateError((err as Error).message);
      }
    },
    [],
  );

  const confirmUpdate = useCallback(async () => {
    if (!updateTarget || !preflight) return;
    setActivating(true);
    setUpdateError(null);
    try {
      await activateSourceVersion(updateTarget.viewName, preflight.version.id);
      const added = preflight.compatibility.addedColumns;
      setReplaceMsg(
        `Updated "${updateTarget.fileName}" to v${preflight.version.versionNumber}` +
          `${added.length ? ` (added column(s): ${added.join(", ")})` : ""}.`,
      );
      setUpdateTarget(null);
      setPreflight(null);
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "datasources"],
      });
      queryClient.invalidateQueries({ queryKey: ["source-versions"] });
    } catch (err) {
      setUpdateError((err as Error).message);
    } finally {
      setActivating(false);
    }
  }, [preflight, projectId, queryClient, updateTarget]);

  const openPicker = useCallback((source: DataSource) => {
    pickerSource.current = source;
    pickerRef.current?.click();
  }, []);

  const keyFor = (s: DataSource) => s.viewName || s.fileName;
  const selected =
    rows.find((s) => keyFor(s) === selectedKey) ?? rows[0] ?? null;
  const detail = rows.find((s) => keyFor(s) === detailKey) ?? null;

  const dbCount = rows.filter(isDatabase).length;
  const fileCount = rows.filter((s) => !isDatabase(s) && !isSaas(s)).length;
  const totalColumns = rows.reduce(
    (a, s) => a + (s.columnTypes?.length ?? 0),
    0,
  );

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-data-sources"
      breadcrumbLabel="Data Sources"
      actions={
        <>
          <Button variant="secondary">
            <IconRefresh size={14} />
            Sync all
          </Button>
          <ConnectorsMenu
            projectId={Number(projectId)}
            label="+ Connect Database"
            onCreated={() =>
              queryClient.invalidateQueries({
                queryKey: ["project", projectId, "datasources"],
              })
            }
          />
        </>
      }
      contextPanel={<SourceDetailPanel source={detail ?? selected} />}
    >
      {detail ? (
        <DataSourceResultView
          projectId={projectId}
          source={detail}
          backLabel="Data Sources"
          onBack={() => setDetailKey(null)}
        />
      ) : (
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Total sources" value={rows.length} />
          <StatTile label="Database sources" value={dbCount} />
          <StatTile label="File sources" value={fileCount} />
          <StatTile
            label="Columns mapped"
            value={totalColumns}
            hint="across all sources"
          />
        </div>

        {isLoading ? (
          <div className="py-16 text-center text-small text-ink-tertiary">
            Loading data sources…
          </div>
        ) : rows.length === 0 ? (
          <Card className="px-4 py-16 text-center text-small text-ink-tertiary">
            No data sources yet. Connect a database or upload a file to get
            started.
          </Card>
        ) : (
          <Card>
            <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
              <span className="text-h3 text-ink-primary">Data Sources</span>
              <span className="text-small text-ink-tertiary">
                {rows.length} total
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="border-b border-line-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
                    <th className="px-4 py-2 font-medium">Name</th>
                    <th className="px-4 py-2 font-medium">Source</th>
                    <th className="px-4 py-2 font-medium">Type</th>
                    <th className="px-4 py-2 font-medium">Visibility</th>
                    <th className="px-4 py-2 font-medium">Columns</th>
                    <th className="px-4 py-2 font-medium">Size</th>
                    <th className="px-4 py-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((s) => {
                    const key = keyFor(s);
                    const active = selected && keyFor(selected) === key;
                    const cols = s.columnTypes ?? [];
                    const isFile = !isDatabase(s) && !isSaas(s);
                    return (
                      <tr
                        key={key}
                        onClick={() => {
                          setSelectedKey(key);
                          setDetailKey(key);
                        }}
                        onDragOver={
                          isFile
                            ? (e) => {
                                e.preventDefault();
                                setDragOverKey(key);
                              }
                            : undefined
                        }
                        onDragLeave={
                          isFile ? () => setDragOverKey(null) : undefined
                        }
                        onDrop={
                          isFile
                            ? (e) => {
                                e.preventDefault();
                                void startUpdate(s, e.dataTransfer.files);
                              }
                            : undefined
                        }
                        className={cn(
                          "cursor-pointer border-b border-line-tertiary last:border-0",
                          dragOverKey === key
                            ? "border-brand border-dashed bg-brand-50/30 ring-2 ring-brand/30"
                            : active
                              ? "bg-brand-50/60"
                              : "hover:bg-bg-secondary",
                        )}
                      >
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-2.5">
                            <SourceIcon source={s} />
                            <span
                              className={cn(
                                "font-medium",
                                active ? "text-brand-700" : "text-ink-primary",
                              )}
                            >
                              {s.fileName}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-2.5 text-ink-secondary">
                          {s.viewName || "—"}
                        </td>
                        <td className="px-4 py-2.5 text-ink-secondary">
                          {sourceTypeLabel(s)}
                        </td>
                        <td className="px-4 py-2.5">
                          <Badge tone={isDatabase(s) ? "success" : "neutral"}>
                            {isDatabase(s) ? "Connected" : "File"}
                          </Badge>
                        </td>
                        <td className="px-4 py-2.5 text-ink-secondary">
                          {cols.length || "—"}
                        </td>
                        <td className="px-4 py-2.5 text-ink-tertiary">
                          {humanSize(s.size) || "—"}
                        </td>
                        <td className="px-4 py-2.5">
                          {isFile && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                openPicker(s);
                              }}
                              className="rounded-md border border-line-primary px-2 py-1 text-caption font-medium text-ink-primary hover:bg-bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
                            >
                              Update data source
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {replaceMsg && (
          <p className="text-[12px] text-ink-secondary">{replaceMsg}</p>
        )}

        <input
          ref={pickerRef}
          type="file"
          className="hidden"
          onChange={(e) => {
            const source = pickerSource.current;
            const files = e.target.files;
            if (source) void startUpdate(source, files);
            e.target.value = "";
          }}
        />

        <DataSourceUpdateDialog
          open={updateTarget !== null}
          sourceName={updateTarget?.fileName ?? ""}
          preflight={preflight}
          busy={activating}
          error={updateError}
          onConfirm={() => void confirmUpdate()}
          onCancel={() => {
            setUpdateTarget(null);
            setPreflight(null);
            setUpdateError(null);
          }}
        />
      </div>
      )}
    </ProjectShell>
  );
}

function SourceDetailPanel({ source }: { source: DataSource | null }) {
  if (!source) {
    return (
      <ContextPanel title="Source Detail" askPlaceholder="Ask about this source…">
        <div className="px-1 py-8 text-center text-small text-ink-tertiary">
          Select a source to see its schema and details.
        </div>
      </ContextPanel>
    );
  }
  const cols = source.columnTypes ?? [];
  const meta = source.aiMetadata ?? null;
  const tags = metaList(meta, ["suggested_tags", "tags"]);
  const kpis = metaList(meta, ["suggested_kpis", "recommended_kpis", "kpis"]);
  const summary =
    meta && typeof meta.summary === "string" ? meta.summary : null;
  return (
    <ContextPanel title="Source Detail" askPlaceholder="Ask about this source…">
      {summary && (
        <div className="rounded-lg border border-brand-100 bg-brand-50/60 p-3 text-[13px] leading-relaxed text-ink-primary">
          {summary}
        </div>
      )}

      {kpis.length > 0 && (
        <ContextSection title="Recommended KPIs">
          <ul className="space-y-1 text-[13px]">
            {kpis.slice(0, 8).map((k, i) => (
              <li key={`${k}-${i}`} className="flex items-start gap-1.5">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-brand-500" />
                <span className="text-ink-primary">{k}</span>
              </li>
            ))}
          </ul>
        </ContextSection>
      )}

      {tags.length > 0 && (
        <ContextSection title="Tags">
          <div className="flex flex-wrap gap-1.5">
            {tags.slice(0, 12).map((t, i) => (
              <Badge key={`${t}-${i}`} tone="brand">
                {t}
              </Badge>
            ))}
          </div>
        </ContextSection>
      )}

      <ContextSection title="Source">
        <dl className="space-y-1 text-[13px]">
          <Row label="Name" value={source.fileName} />
          <Row label="Type" value={sourceTypeLabel(source)} />
          <Row label="View" value={source.viewName} />
          {humanSize(source.size) && (
            <Row label="Size" value={humanSize(source.size)} />
          )}
          <Row label="Columns" value={String(cols.length)} />
        </dl>
      </ContextSection>

      {cols.length > 0 && (
        <ContextSection title="Schema">
          <ul className="space-y-1 text-[13px]">
            {cols.slice(0, 12).map((c, i) => {
              const { name, type } = columnLabel(c);
              return (
                <li key={`${name}-${i}`} className="flex justify-between gap-2">
                  <span className="truncate text-ink-primary">{name}</span>
                  <span className="text-ink-tertiary">{type || "—"}</span>
                </li>
              );
            })}
          </ul>
        </ContextSection>
      )}

      {!isDatabase(source) && !isSaas(source) && (
        <VersionHistorySection viewName={source.viewName} />
      )}
    </ContextPanel>
  );
}

/** Version history with rollback for file-backed sources. */
function VersionHistorySection({ viewName }: { viewName: string }) {
  const queryClient = useQueryClient();
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { data } = useQuery<SourceVersion[]>({
    queryKey: ["source-versions", viewName],
    queryFn: () => listSourceVersions(viewName),
    enabled: Boolean(viewName),
  });
  const versions = data ?? [];
  if (versions.length === 0) return null;

  const rollback = async (version: SourceVersion) => {
    setBusyId(version.id);
    setError(null);
    try {
      await rollbackSourceVersion(viewName, version.id);
      queryClient.invalidateQueries({ queryKey: ["source-versions", viewName] });
      queryClient.invalidateQueries({ queryKey: ["project"] });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <ContextSection title="Version history">
      <ul className="space-y-2 text-[13px]">
        {versions.map((v) => (
          <li key={v.id} className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate text-ink-primary">
                v{v.versionNumber} · {v.originalFilename}
              </p>
              <p className="text-caption text-ink-tertiary">
                {v.status}
                {v.rowCount != null ? ` · ${v.rowCount} rows` : ""}
              </p>
            </div>
            {v.status === "archived" && (
              <button
                type="button"
                onClick={() => void rollback(v)}
                disabled={busyId !== null}
                className="shrink-0 rounded-md border border-line-primary px-2 py-1 text-caption font-medium text-ink-primary hover:bg-bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 disabled:opacity-50"
              >
                {busyId === v.id ? "Restoring…" : "Restore"}
              </button>
            )}
          </li>
        ))}
      </ul>
      {error && <p className="mt-2 text-caption text-danger">{error}</p>}
    </ContextSection>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-ink-tertiary">{label}</dt>
      <dd className="truncate text-ink-primary">{value}</dd>
    </div>
  );
}
