"use client";

import { useMemo, useState } from "react";
import {
  IconSearch,
  IconDatabase,
  IconFileText,
  IconSparkles,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { StatTile } from "@/components/ui/stat-tile";
import { cn } from "@/lib/cn";
import {
  useProjectMetadataCatalog,
  type CatalogTable,
  type CatalogField,
  type CatalogDocument,
} from "@/lib/ui/use-project-data";

type Selection =
  | { kind: "table"; id: number }
  | { kind: "document"; id: number }
  | null;

export function MetadataCatalogPanel({ projectId }: { projectId: string }) {
  const { data, isLoading } = useProjectMetadataCatalog(projectId);
  const tables = useMemo(() => data?.tables ?? [], [data]);
  const documents = useMemo(() => data?.documents ?? [], [data]);
  const [search, setSearch] = useState("");
  const [selection, setSelection] = useState<Selection>(null);

  const q = search.trim().toLowerCase();
  const filteredTables = tables.filter((t) =>
    !q ? true : t.name.toLowerCase().includes(q),
  );
  const filteredDocs = documents.filter((d) =>
    !q ? true : d.title.toLowerCase().includes(q),
  );

  const current: Selection =
    selection ??
    (tables.length
      ? { kind: "table", id: tables[0].data_source_id }
      : documents.length
        ? { kind: "document", id: documents[0].id }
        : null);

  const selectedTable =
    current?.kind === "table"
      ? tables.find((t) => t.data_source_id === current.id) ?? null
      : null;
  const selectedDoc =
    current?.kind === "document"
      ? documents.find((d) => d.id === current.id) ?? null
      : null;

  const fieldsProfiled = tables.reduce((n, t) => n + t.fields.length, 0);
  const aiDescribed = tables.reduce(
    (n, t) => n + t.fields.filter((f) => f.ai_description).length,
    0,
  );

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button variant="primary">
          <IconSparkles size={14} />
          Re-profile with AI
        </Button>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Tables profiled" value={String(tables.length)} />
          <StatTile label="Fields catalogued" value={String(fieldsProfiled)} />
          <StatTile label="AI-described fields" value={String(aiDescribed)} />
          <StatTile label="Documents" value={String(documents.length)} />
        </div>

        <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
          <Card className="flex max-h-[640px] flex-col overflow-hidden">
            <div className="border-b border-line-tertiary p-2.5">
              <div className="flex items-center gap-2 rounded-md border border-line-secondary bg-bg-primary px-2.5 py-1.5">
                <IconSearch size={14} className="text-ink-tertiary" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search catalog…"
                  className="w-full bg-transparent text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:outline-none"
                />
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-2">
              {isLoading ? (
                <div className="px-2 py-6 text-center text-small text-ink-tertiary">
                  Loading…
                </div>
              ) : (
                <>
                  <GroupLabel
                    icon={IconDatabase}
                    label={`Tables (${filteredTables.length})`}
                  />
                  {filteredTables.map((t) => (
                    <SidebarItem
                      key={`t-${t.data_source_id}`}
                      title={t.name}
                      subtitle={`${t.field_count ?? t.fields.length} fields`}
                      active={
                        current?.kind === "table" &&
                        current.id === t.data_source_id
                      }
                      onClick={() =>
                        setSelection({ kind: "table", id: t.data_source_id })
                      }
                    />
                  ))}
                  <GroupLabel
                    icon={IconFileText}
                    label={`Documents (${filteredDocs.length})`}
                  />
                  {filteredDocs.map((d) => (
                    <SidebarItem
                      key={`d-${d.id}`}
                      title={d.title}
                      subtitle={d.type}
                      active={
                        current?.kind === "document" && current.id === d.id
                      }
                      onClick={() =>
                        setSelection({ kind: "document", id: d.id })
                      }
                    />
                  ))}
                  {filteredTables.length === 0 &&
                    filteredDocs.length === 0 && (
                      <div className="px-2 py-6 text-center text-small text-ink-tertiary">
                        Nothing matches your search.
                      </div>
                    )}
                </>
              )}
            </div>
          </Card>

          {selectedTable ? (
            <TableProfile table={selectedTable} />
          ) : selectedDoc ? (
            <DocumentProfile document={selectedDoc} />
          ) : (
            <Card className="flex items-center justify-center px-4 py-20 text-center text-small text-ink-tertiary">
              No catalogued data sources yet. Profile a data source with AI to
              populate the catalog.
            </Card>
          )}
        </div>
      </div>
  );
}

export const MetadataCatalogScreen = MetadataCatalogPanel;

function GroupLabel({
  icon: Icon,
  label,
}: {
  icon: typeof IconDatabase;
  label: string;
}) {
  return (
    <div className="mt-2 flex items-center gap-1.5 px-2 py-1 text-caption uppercase tracking-wide text-ink-tertiary">
      <Icon size={12} /> {label}
    </div>
  );
}

function SidebarItem({
  title,
  subtitle,
  active,
  onClick,
}: {
  title: string;
  subtitle: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full rounded-md px-2 py-1.5 text-left",
        active ? "bg-brand-50" : "hover:bg-bg-secondary",
      )}
    >
      <div
        className={cn(
          "truncate text-[13px] font-medium",
          active ? "text-brand-700" : "text-ink-primary",
        )}
      >
        {title}
      </div>
      <div className="truncate text-small text-ink-tertiary">{subtitle}</div>
    </button>
  );
}

function TableProfile({ table }: { table: CatalogTable }) {
  return (
    <Card className="overflow-hidden">
      <div className="border-b border-line-tertiary px-4 py-3.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <IconDatabase size={16} className="text-ink-tertiary" />
            <span className="text-h2 text-ink-primary">{table.name}</span>
          </div>
          <Badge tone={table.status === "ready" ? "success" : "neutral"}>
            {table.status}
          </Badge>
        </div>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-small text-ink-tertiary">
          {table.source && <span>{table.source}</span>}
          {table.row_count != null && (
            <span>{table.row_count.toLocaleString()} rows</span>
          )}
          <span>{table.fields.length} fields</span>
        </div>
      </div>

      {table.ai_summary && (
        <div className="border-b border-line-tertiary bg-ai-bg/40 px-4 py-3">
          <div className="mb-1 flex items-center gap-1.5 text-caption uppercase tracking-wide text-ai">
            <IconSparkles size={12} /> AI Profile
          </div>
          <p className="text-[13px] leading-relaxed text-ink-secondary">
            {table.ai_summary}
          </p>
          {table.ai_quality_summary && (
            <p className="mt-1.5 text-small text-ink-tertiary">
              {table.ai_quality_summary}
            </p>
          )}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-left text-[13px]">
          <thead>
            <tr className="border-b border-line-tertiary text-caption uppercase tracking-wide text-ink-tertiary">
              <Th>Field</Th>
              <Th>Type</Th>
              <Th>AI Description</Th>
              <Th className="text-right">Null %</Th>
              <Th className="text-right">Distinct</Th>
              <Th>Samples</Th>
            </tr>
          </thead>
          <tbody>
            {table.fields.map((f) => (
              <FieldRow key={f.name} field={f} />
            ))}
            {table.fields.length === 0 && (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-8 text-center text-small text-ink-tertiary"
                >
                  No field-level profile available.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function FieldRow({ field }: { field: CatalogField }) {
  const samples = field.sample_values
    .slice(0, 3)
    .map((v) => String(v))
    .join(", ");
  return (
    <tr className="border-b border-line-tertiary last:border-0">
      <td className="px-4 py-2.5">
        <span className="font-medium text-ink-primary">{field.name}</span>
        {!field.include_in_ai && (
          <Badge tone="outline" className="ml-1.5">
            excluded
          </Badge>
        )}
      </td>
      <td className="px-4 py-2.5">
        <Badge tone="neutral">{field.type ?? "unknown"}</Badge>
      </td>
      <td className="px-4 py-2.5 text-ink-secondary">
        {field.ai_description ?? "—"}
      </td>
      <td className="px-4 py-2.5 text-right text-ink-secondary">
        {field.null_percent != null ? `${field.null_percent.toFixed(2)}%` : "—"}
      </td>
      <td className="px-4 py-2.5 text-right text-ink-secondary">
        {field.distinct_count != null
          ? field.distinct_count.toLocaleString()
          : "—"}
      </td>
      <td className="max-w-[200px] truncate px-4 py-2.5 text-ink-tertiary">
        {samples || "—"}
      </td>
    </tr>
  );
}

function DocumentProfile({ document }: { document: CatalogDocument }) {
  return (
    <Card className="overflow-hidden">
      <div className="border-b border-line-tertiary px-4 py-3.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <IconFileText size={16} className="text-ink-tertiary" />
            <span className="text-h2 text-ink-primary">{document.title}</span>
          </div>
          <Badge tone="neutral">{document.type}</Badge>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-4 px-4 py-4 sm:grid-cols-3">
        <Stat label="Status" value={document.status} />
        <Stat label="Extractions" value={String(document.clauses)} />
        <Stat label="Relationships" value={String(document.relationships)} />
      </div>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-caption uppercase tracking-wide text-ink-tertiary">
        {label}
      </div>
      <div className="mt-0.5 text-h3 text-ink-primary">{value}</div>
    </div>
  );
}

function Th({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <th className={cn("px-4 py-2 font-medium", className)}>{children}</th>
  );
}
