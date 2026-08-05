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
import { DataSourceResultView } from "@/components/tablescope/project/detail-views";import { sourceTypeLabel } from "./source-type-label";
import { SourceIcon } from "./source-icon";



export function ArchiveCard({
  rows,
  busy,
  onRestore,
  onDelete,
}: {
  rows: DataSource[];
  busy: boolean;
  onRestore: (source: DataSource) => void;
  onDelete: (source: DataSource) => void;
}) {
  return (
    <Card>
      <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
        <span className="flex items-center gap-1.5 text-h3 text-ink-primary">
          <IconArchive size={16} className="text-ink-tertiary" />
          Archive
        </span>
        <span className="text-small text-ink-tertiary">
          {rows.length} archived {rows.length === 1 ? "source" : "sources"}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-line-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Source</th>
              <th className="px-4 py-2 font-medium">Type</th>
              <th className="px-4 py-2 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr
                key={s.viewName || s.fileName}
                className="border-b border-line-tertiary last:border-0"
              >
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-2.5">
                    <SourceIcon source={s} />
                    <span className="font-medium text-ink-primary">{s.fileName}</span>
                  </div>
                </td>
                <td className="px-4 py-2.5 text-ink-secondary">
                  {s.viewName || "—"}
                </td>
                <td className="px-4 py-2.5 text-ink-secondary">
                  {sourceTypeLabel(s)}
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center justify-end gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      onClick={() => onRestore(s)}
                    >
                      <IconArrowBackUp size={14} />
                      Restore
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => onDelete(s)}
                    >
                      <IconTrash size={14} />
                      Delete
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}