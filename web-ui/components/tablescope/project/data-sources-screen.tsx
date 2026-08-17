"use client";

import { useMemo, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import {
  IconRefresh,
  IconSearch,
  IconDatabase,
  IconDatabasePlus,
  IconServer,
  IconFileText,
  IconApi,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { DataSourceUpdateDialog } from "@/components/tablescope/project/data-source-update-dialog";
import {
  activateSourceVersion,
  preflightSourceUpdate,
  type PreflightResponse,
} from "@/lib/api/data-source-versions";
import {
  type PreflightDeleteResponse,
} from "@/lib/api/data-sources";
import {
  useProjectDataSources,
  type DataSource,
} from "@/lib/ui/use-project-data";
import { DataSourceResultView } from "@/components/tablescope/project/detail-views";
import { StatBar, type StatItem } from "./overview-screen/stat-bar";
import { isDatabase } from "./data-sources-screen/is-database";
import { isSaas } from "./data-sources-screen/is-saas";
import { SourceIcon } from "./data-sources-screen/source-icon";
import { sourceTypeLabel } from "./data-sources-screen/source-type-label";
import { humanSize } from "./data-sources-screen/human-size";
import { archiveSource } from "./data-sources-screen/archive-source";
import { preflightDelete } from "./data-sources-screen/preflight-delete";
import { deleteSource } from "./data-sources-screen/delete-source";
import { FILTERS } from "./data-sources-screen/filters";
import { ArchiveCard } from "./data-sources-screen/archive-card";
import { DeleteSourceDialog } from "./data-sources-screen/delete-source-dialog";

export function DataSourcesScreen({ projectId }: { projectId: string }) {
  const router = useRouter();
  const { data: allData, isLoading } = useProjectDataSources(projectId, true);
  const queryClient = useQueryClient();
  const rows = useMemo(
    () => (allData ?? []).filter((s) => !s.archived),
    [allData],
  );
  const archivedRows = useMemo(
    () => (allData ?? []).filter((s) => s.archived),
    [allData],
  );
  const [filter, setFilter] = useState<"all" | "archive">("all");
  const [search, setSearch] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detailKey, setDetailKey] = useState<string | null>(null);

  // ── Update a source (drag-to-drop or the accessible Update action) ──
  const [dragOverKey, setDragOverKey] = useState<string | null>(null);
  const [updateTarget, setUpdateTarget] = useState<DataSource | null>(null);
  const [preflight, setPreflight] = useState<PreflightResponse | null>(null);
  const [updateError, setUpdateError] = useState<string | null>(null);
  const [activating, setActivating] = useState(false);
  const [replaceMsg, setReplaceMsg] = useState<string | null>(null);
  const pickerRef = useRef<HTMLInputElement>(null);
  const pickerSource = useRef<DataSource | null>(null);

  // ── Archive / delete ──
  const [archiveBusyId, setArchiveBusyId] = useState<string | null>(null);
  const [archiveError, setArchiveError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DataSource | null>(null);
  const [deletePreflight, setDeletePreflight] = useState<PreflightDeleteResponse | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: ["project", projectId, "datasources"],
    });
    queryClient.invalidateQueries({ queryKey: ["source-versions"] });
  }, [projectId, queryClient]);

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
      refresh();
    } catch (err) {
      setUpdateError((err as Error).message);
    } finally {
      setActivating(false);
    }
  }, [preflight, refresh, updateTarget]);

  const openPicker = useCallback((source: DataSource) => {
    pickerSource.current = source;
    pickerRef.current?.click();
  }, []);

  const handleArchive = useCallback(
    async (source: DataSource, archived: boolean) => {
      setArchiveBusyId(source.lifecycleId);
      setArchiveError(null);
      try {
        await archiveSource(source, archived);
        if (archived) {
          setDetailKey(null);
          setSelectedKey(null);
        }
        refresh();
      } catch (err) {
        setArchiveError((err as Error).message);
      } finally {
        setArchiveBusyId(null);
      }
    },
    [refresh],
  );

  const handleDelete = useCallback(async (source: DataSource) => {
    setDeleteTarget(source);
    setDeletePreflight(null);
    setDeleteError(null);
    setDeleteBusy(true);
    try {
      setDeletePreflight(await preflightDelete(source));
    } catch (err) {
      setDeleteError((err as Error).message);
    } finally {
      setDeleteBusy(false);
    }
  }, []);

  const confirmDelete = useCallback(async () => {
    if (!deleteTarget || !deletePreflight?.safe) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await deleteSource(deleteTarget);
      setDeleteTarget(null);
      setDeletePreflight(null);
      refresh();
    } catch (err) {
      setDeleteError((err as Error).message);
    } finally {
      setDeleteBusy(false);
    }
  }, [deletePreflight, deleteTarget, refresh]);

  const keyFor = (s: DataSource) => s.lifecycleId;
  const selected =
    rows.find((s) => keyFor(s) === selectedKey) ?? rows[0] ?? null;
  const detail = rows.find((s) => keyFor(s) === detailKey) ?? null;

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    const pool = filter === "archive" ? archivedRows : rows;
    if (!term) return pool;
    return pool.filter((s) => {
      const hay = [
        s.fileName,
        s.viewName,
        s.sourceType,
        s.dbType,
        s.connectorType,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(term);
    });
  }, [rows, archivedRows, filter, search]);

  const dbCount = rows.filter(isDatabase).length;
  const fileCount = rows.filter((s) => !isDatabase(s) && !isSaas(s)).length;
  const saasCount = rows.filter(isSaas).length;

  const statItems: StatItem[] = [
    {
      key: "total",
      icon: IconDatabase,
      iconClass: "bg-brand-50 text-brand-700",
      value: rows.length,
      label: "Total sources",
    },
    {
      key: "database",
      icon: IconServer,
      iconClass: "bg-ai-bg text-ai",
      value: dbCount,
      label: "Database sources",
    },
    {
      key: "file",
      icon: IconFileText,
      iconClass: "bg-success-bg text-success",
      value: fileCount,
      label: "File sources",
    },
    {
      key: "saas",
      icon: IconApi,
      iconClass: "bg-warning-bg text-warning",
      value: saasCount,
      label: "SaaS sources",
    },
  ];

  const inDetail = Boolean(detail);

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-data-sources"
      breadcrumbLabel="Data Sources"
      showProjectHeader={!inDetail}
      headerActions={
        !inDetail ? (
          <>
            <Button variant="secondary">
              <IconRefresh size={14} />
              Sync all
            </Button>
            <Button
              variant="secondary"
              onClick={() => router.push(`/projects/${projectId}/data-source-builder`)}
            >
              <IconDatabasePlus size={14} />
              Data Source Builder
            </Button>
          </>
        ) : undefined
      }
    >
      {detail ? (
        <DataSourceResultView
          projectId={projectId}
          source={detail}
          backLabel="Data Sources"
          onBack={() => setDetailKey(null)}
          onArchive={() => void handleArchive(detail, true)}
          archiveBusy={archiveBusyId === detail.lifecycleId}
          archiveError={archiveError}
        />
      ) : (
        <div className="space-y-4">
          {filter !== "archive" && <StatBar items={statItems} />}

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[220px] flex-1">
              <IconSearch
                size={15}
                className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-tertiary"
              />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search data sources…"
                className="h-8 w-full rounded-md border border-line-secondary bg-bg-primary pl-8 pr-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
              />
            </div>
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={cn(
                  "h-8 rounded-md border px-3 text-[12px] font-medium",
                  filter === f.key
                    ? "border-brand-500 bg-brand-50 text-brand-700"
                    : "border-line-secondary bg-bg-primary text-ink-secondary hover:bg-bg-secondary",
                )}
              >
                {f.label}
              </button>
            ))}
          </div>

          {isLoading ? (
            <div className="py-16 text-center text-small text-ink-tertiary">
              Loading data sources…
            </div>
          ) : filtered.length === 0 ? (
            <Card className="px-4 py-16 text-center text-small text-ink-tertiary">
              {filter === "archive"
                ? "No archived data sources. Archive a data source to see it here."
                : "No data sources yet. Connect a database or upload a file to get started."}
            </Card>
          ) : filter === "archive" ? (
            <ArchiveCard
              rows={filtered}
              busyId={archiveBusyId}
              error={archiveError}
              onRestore={(s) => void handleArchive(s, false)}
              onDelete={handleDelete}
            />
          ) : (
            <Card>
              <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
                <span className="text-h3 text-ink-primary">All Data Sources</span>
                <span className="text-small text-ink-tertiary">
                  {filtered.length} total {filtered.length === 1 ? "data source" : "data sources"}
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
                    {filtered.map((s) => {
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
                            {isFile ? (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  openPicker(s);
                                }}
                                className="rounded-md border border-line-primary px-2 py-1 text-caption font-medium text-ink-primary hover:bg-bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
                              >
                                Update
                              </button>
                            ) : (
                              <span className="text-ink-tertiary">—</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {filtered.length === 0 && !isLoading && (
                  <div className="px-4 py-12 text-center text-small text-ink-tertiary">
                    No data sources match your search.
                  </div>
                )}
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

          <DeleteSourceDialog
            open={deleteTarget !== null}
            source={deleteTarget}
            preflight={deletePreflight}
            busy={deleteBusy}
            error={deleteError}
            onConfirm={() => void confirmDelete()}
            onCancel={() => {
              setDeleteTarget(null);
              setDeletePreflight(null);
              setDeleteError(null);
            }}
          />
        </div>
      )}
    </ProjectShell>
  );
}
