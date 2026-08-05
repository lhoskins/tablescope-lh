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
import { DataSourceResultView } from "@/components/tablescope/project/detail-views";import { isDatabase } from "./is-database";
import { isSaas } from "./is-saas";
import { sourceTypeLabel } from "./source-type-label";
import { humanSize } from "./human-size";
import { VersionHistorySection } from "./version-history-section";
import { Row } from "./row";



export function SourceDetailPanel({ source }: { source: DataSource | null }) {
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