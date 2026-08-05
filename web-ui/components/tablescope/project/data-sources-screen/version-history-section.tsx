"use client";


import { useMemo, useRef, useState, useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconRefresh,
  IconDatabase,
  IconFileSpreadsheet,
  IconApi,
  IconArchive,
  IconArrowBackUp,
  IconTrash,
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
  archiveFileSource,
  archiveDatabaseSource,
  archiveSaasSource,
  preflightDeleteFileSource,
  preflightDeleteDatabaseSource,
  preflightDeleteSaasSource,
  deleteFileSource,
  deleteDatabaseSource,
  deleteSaasSource,
  type PreflightDeleteResponse,
} from "@/lib/api/data-sources";
import {
  useProjectDataSources,
  columnLabel,
  type DataSource,
} from "@/lib/ui/use-project-data";
import { metaList } from "@/lib/ui/ai-meta";
import { DataSourceResultView } from "@/components/tablescope/project/detail-views";


/** Version history with rollback for file-backed sources. */
export function VersionHistorySection({ viewName }: { viewName: string }) {
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