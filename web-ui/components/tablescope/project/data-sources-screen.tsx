"use client";

import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  IconRefresh,
  IconDatabase,
  IconFileSpreadsheet,
  IconApi,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { ConnectorsMenu } from "@/components/datasource/ConnectorsMenu";
import { AIFileUploadWizard } from "@/components/upload/AIFileUploadWizard";
import {
  ContextPanel,
  ContextSection,
} from "@/components/tablescope/context-panel";
import { StatTile } from "@/components/ui/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
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

        <Card className="p-4">
          <div className="mb-3">
            <h3 className="text-h3 text-ink-primary">AI-assisted upload</h3>
            <p className="text-small text-ink-tertiary">
              Drop a CSV or Excel file to profile it with AI and add it as a
              data source.
            </p>
          </div>
          <AIFileUploadWizard
            projectId={Number(projectId)}
            onComplete={() =>
              queryClient.invalidateQueries({
                queryKey: ["project", projectId, "datasources"],
              })
            }
          />
        </Card>

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
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {rows.map((s) => {
              const key = keyFor(s);
              const active = selected && keyFor(selected) === key;
              const cols = s.columnTypes ?? [];
              return (
                <Card
                  key={key}
                  onClick={() => {
                    setSelectedKey(key);
                    setDetailKey(key);
                  }}
                  className={cn(
                    "cursor-pointer",
                    active && "ring-1 ring-brand-500",
                  )}
                >
                  <div className="flex items-start gap-3 p-4">
                    <SourceIcon source={s} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-h3 text-ink-primary">
                          {s.fileName}
                        </span>
                        <Badge tone={isDatabase(s) ? "success" : "neutral"}>
                          {isDatabase(s) ? "Connected" : "File"}
                        </Badge>
                      </div>
                      <div className="text-small text-ink-tertiary">
                        {sourceTypeLabel(s)}
                        {humanSize(s.size) ? ` · ${humanSize(s.size)}` : ""}
                        {cols.length ? ` · ${cols.length} columns` : ""}
                      </div>
                    </div>
                  </div>
                  {cols.length > 0 && (
                    <div className="border-t border-line-tertiary px-4 py-2.5">
                      <table className="w-full text-[12px]">
                        <thead>
                          <tr className="text-left text-caption uppercase tracking-wide text-ink-tertiary">
                            <th className="py-1 font-medium">Column</th>
                            <th className="py-1 font-medium">Type</th>
                          </tr>
                        </thead>
                        <tbody>
                          {cols.slice(0, 4).map((c, i) => {
                            const { name, type } = columnLabel(c);
                            return (
                              <tr key={`${name}-${i}`}>
                                <td className="py-1 text-ink-primary">{name}</td>
                                <td className="py-1 text-ink-tertiary">
                                  {type || "—"}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                      {cols.length > 4 && (
                        <div className="pt-1 text-small text-ink-tertiary">
                          {cols.length - 4} more columns
                        </div>
                      )}
                    </div>
                  )}
                  <div className="flex items-center justify-between border-t border-line-tertiary px-4 py-2.5">
                    <span className="truncate text-small text-ink-tertiary">
                      {s.viewName}
                    </span>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setDetailKey(key);
                      }}
                      className="text-[12px] font-medium text-brand-700 hover:underline"
                    >
                      View data
                    </button>
                  </div>
                </Card>
              );
            })}
          </div>
        )}
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
    </ContextPanel>
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
