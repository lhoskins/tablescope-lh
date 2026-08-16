"use client";

import { useEffect, useMemo, useState } from "react";
import { IconCheck, IconDatabase, IconLoader2 } from "@tabler/icons-react";
import { apiClient } from "@/lib/api-client";
import type { DataSource } from "@/lib/ui/use-project-data";
import type { DashboardTemplateDefinition, TemplateBindingDraft } from "./types";

function columnsOf(source?: DataSource): string[] {
  return (source?.columnTypes ?? []).flatMap((column) => typeof column === "object" && column && typeof (column as { name?: unknown }).name === "string" ? [(column as { name: string }).name] : []);
}

function validateDraft(draft: TemplateBindingDraft): TemplateBindingDraft {
  const errors: string[] = [];
  for (const metric of draft.metricManifest) {
    const entity = String(metric.entity ?? "");
    if (!draft.sourceMapping[entity]) { errors.push(`Select a datasource for ${entity}.`); continue; }
    const filters = [metric.filter, metric.numeratorFilter].filter(Boolean) as Array<Record<string, unknown>>;
    const fields = [metric.valueField, metric.dateField, metric.denominatorField, ...filters.map((item) => item.field)].filter(Boolean).map(String);
    fields.forEach((field) => { if (!draft.fieldMapping[entity]?.[field]) errors.push(`Map ${entity}.${field}.`); });
  }
  return { ...draft, validation: { ...draft.validation, valid: errors.length === 0, errors: [...new Set(errors)] } };
}

export function TemplateBindingEditor({ projectId, template, datasources, dimensionLabel, valueSource, value, onChange }: { projectId: string; template: DashboardTemplateDefinition; datasources: DataSource[]; dimensionLabel: string; valueSource: "query" | "manual"; value?: TemplateBindingDraft; onChange: (value: TemplateBindingDraft) => void }) {
  const [loading, setLoading] = useState(false);
  const profiles = useMemo(() => datasources.map((source) => ({ viewName: source.viewName, columns: columnsOf(source) })), [datasources]);
  useEffect(() => {
    let active = true; setLoading(true);
    apiClient.post<TemplateBindingDraft>(`/api/projects/${projectId}/dashboard-template-bindings/preview`, { template_id: template.id, sources: profiles, dimension_label: dimensionLabel })
      .then((preview) => { if (active) onChange({ ...preview, dimensionConfig: { ...preview.dimensionConfig, label: dimensionLabel, valueSource } }); })
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [dimensionLabel, onChange, profiles, projectId, template.id, valueSource]);
  if (loading && !value) return <div className="mt-4 flex items-center gap-2 p-3 text-small"><IconLoader2 size={15} className="animate-spin" />Profiling datasource fields…</div>;
  if (!value) return null;
  const updateSource = (entity: string, viewName: string) => {
    const source = datasources.find((item) => item.viewName === viewName);
    const available = columnsOf(source);
    const fields = Object.keys(value.fieldMapping[entity] ?? {});
    const mapping = Object.fromEntries(fields.flatMap((field) => { const match = available.find((column) => column.toLowerCase() === field.toLowerCase()); return match ? [[field, match]] : []; }));
    onChange(validateDraft({ ...value, sourceMapping: { ...value.sourceMapping, [entity]: viewName }, fieldMapping: { ...value.fieldMapping, [entity]: mapping } }));
  };
  const updateField = (entity: string, field: string, column: string) => onChange(validateDraft({ ...value, fieldMapping: { ...value.fieldMapping, [entity]: { ...(value.fieldMapping[entity] ?? {}), [field]: column } } }));
  const entities = [...new Set(value.metricManifest.map((metric) => String(metric.entity)))];
  return <div className="mt-4 rounded-lg border border-line-secondary bg-bg-secondary/30 p-3">
    <div className="flex items-start justify-between gap-3"><div><div className="flex items-center gap-2 text-small font-semibold"><IconDatabase size={15} />Datasource mapping</div><p className="text-[11px] text-ink-tertiary">Approval compiles, validates, saves and versions the batch queries.</p></div><span className={`rounded-full px-2 py-1 text-[10px] ${value.validation.valid ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>{value.validation.valid ? "Ready to approve" : `${value.validation.errors.length} mappings needed`}</span></div>
    <div className="mt-3 space-y-3">{entities.map((entity) => {
      const viewName = value.sourceMapping[entity] ?? "";
      const columns = columnsOf(datasources.find((item) => item.viewName === viewName));
      const fields = [...new Set(value.metricManifest.filter((metric) => metric.entity === entity).flatMap((metric) => { const filter = metric.filter as Record<string, unknown> | undefined; const numerator = metric.numeratorFilter as Record<string, unknown> | undefined; return [metric.valueField, metric.dateField, metric.denominatorField, filter?.field, numerator?.field]; }).filter(Boolean).map(String))];
      return <div key={entity} className="rounded-md border bg-bg-primary p-2.5"><div className="grid gap-2 sm:grid-cols-[110px_1fr]"><span className="text-[11px] font-semibold capitalize">{entity}</span><select value={viewName} onChange={(event) => updateSource(entity, event.target.value)} className="h-8 rounded border px-2 text-[11px]"><option value="">Select datasource…</option>{datasources.map((source) => <option key={source.viewName} value={source.viewName}>{source.fileName}</option>)}</select></div><div className="mt-2 grid gap-2 sm:grid-cols-2">{fields.map((field) => <label key={field} className="text-[10px]">{field}<select value={value.fieldMapping[entity]?.[field] ?? ""} onChange={(event) => updateField(entity, field, event.target.value)} className="mt-0.5 h-8 w-full rounded border px-2"><option value="">Map field…</option>{columns.map((column) => <option key={column}>{column}</option>)}</select></label>)}</div></div>;
    })}</div>
    {value.validation.valid && <div className="mt-2 flex items-center gap-1 text-[11px] text-emerald-700"><IconCheck size={13} />No SQL authoring is required.</div>}
  </div>;
}
