"use client";

import { useEffect, useMemo, useState } from "react";
import { IconCheck, IconSparkles, IconX } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { SavedQuery } from "@/lib/ui/use-project-data";
import { cn } from "@/lib/cn";
import { DASHBOARD_TEMPLATES } from "./registry";
import { DashboardTemplateIconView } from "./icons";
import { instantiateDashboardTemplate } from "./instantiate";
import type {
  DashboardTemplateCategory,
  DashboardTemplateDefinition,
  DashboardTemplateParameters,
} from "./types";

function _normal(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

const CATEGORIES: Array<{ value: "all" | DashboardTemplateCategory; label: string }> = [
  { value: "all", label: "All templates" },
  { value: "itsm", label: "ITSM" },
  { value: "finance", label: "Finance" },
  { value: "manufacturing", label: "Manufacturing" },
  { value: "sales", label: "Sales" },
  { value: "hr", label: "HR" },
];

interface DashboardTemplateDialogProps {
  open: boolean;
  projectId: string;
  savedQueries: SavedQuery[];
  existingTemplateIds: Set<string>;
  onClose: () => void;
  onCreated: (dashboardIds: number[]) => void;
  onOpenExisting: (templateId: string) => void;
  notify: (message: string, tone?: "success" | "error" | "info") => void;
}

export function DashboardTemplateDialog({
  open,
  projectId,
  savedQueries,
  existingTemplateIds,
  onClose,
  onCreated,
  onOpenExisting,
  notify,
}: DashboardTemplateDialogProps) {
  const [category, setCategory] = useState<"all" | DashboardTemplateCategory>("all");
  const [selectedId, setSelectedId] = useState(DASHBOARD_TEMPLATES[0].id);
  const selected = DASHBOARD_TEMPLATES.find((template) => template.id === selectedId) ?? DASHBOARD_TEMPLATES[0];
  const [groupName, setGroupName] = useState(selected.name);
  const [dimensionLabel, setDimensionLabel] = useState(selected.defaultDimensionLabel);
  const [valueSource, setValueSource] = useState<"query" | "manual">("query");
  const [queryId, setQueryId] = useState<number | undefined>();
  const [manualValues, setManualValues] = useState("");
  const [defaultPeriod, setDefaultPeriod] = useState(selected.defaultPeriod);
  const [creating, setCreating] = useState(false);
  const [progress, setProgress] = useState("");

  useEffect(() => {
    setGroupName(selected.name);
    setDimensionLabel(selected.defaultDimensionLabel);
    setDefaultPeriod(selected.defaultPeriod);
    setProgress("");
  }, [selected]);

  useEffect(() => {
    if (queryId || savedQueries.length === 0) return;
    setQueryId(savedQueries[0].id);
  }, [queryId, savedQueries]);

  const visibleTemplates = useMemo(
    () => DASHBOARD_TEMPLATES.filter((template) => category === "all" || template.category === category),
    [category],
  );
  const alreadyAdded = existingTemplateIds.has(selected.id);
  const builtIn = selected.dashboards.some((dashboard) => Boolean(dashboard.itsmPreset));

  if (!open) return null;

  const create = async () => {
    if (!groupName.trim()) {
      notify("Enter a dashboard group name", "error");
      return;
    }
    if (valueSource === "query" && !queryId) {
      notify("Select the query that supplies the parameter values", "error");
      return;
    }
    const values = manualValues.split(",").map((value) => value.trim()).filter(Boolean);
    if (valueSource === "manual" && values.length === 0) {
      notify("Enter one or more comma-separated values", "error");
      return;
    }
    const query = savedQueries.find((item) => item.id === queryId);
    const parameters: DashboardTemplateParameters = {
      dimensionLabel: dimensionLabel.trim() || selected.defaultDimensionLabel,
      dimensionField: _normal(dimensionLabel.trim() || selected.defaultDimensionLabel),
      valueSource,
      queryId: valueSource === "query" ? queryId : undefined,
      queryName: valueSource === "query" ? query?.name : undefined,
      manualValues: valueSource === "manual" ? values : undefined,
      defaultPeriod,
    };
    setCreating(true);
    setProgress("Preparing the dashboard collection…");
    try {
      const ids = await instantiateDashboardTemplate({
        projectId,
        template: selected,
        groupName: groupName.trim(),
        parameters,
        onProgress: (complete, total, name) => setProgress(`${complete} of ${total} created · ${name}`),
      });
      notify(`Created ${ids.length} dashboards in “${groupName.trim()}”`, "success");
      onCreated(ids);
    } catch (error) {
      notify(error instanceof Error ? error.message : "Template creation failed", "error");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/30 p-4">
      <div className="mx-auto my-6 w-full max-w-6xl rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-h2 text-ink-primary">Add dashboard template</h2>
            <p className="mt-1 text-small text-ink-tertiary">
              Create a complete, editable Operational Insight dashboard collection.
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close template gallery" className="rounded p-1 text-ink-tertiary hover:bg-bg-secondary">
            <IconX size={18} />
          </button>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {CATEGORIES.map((item) => (
            <Button key={item.value} size="sm" variant={category === item.value ? "primary" : "secondary"} onClick={() => setCategory(item.value)}>
              {item.label}
            </Button>
          ))}
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.05fr)_minmax(340px,.95fr)]">
          <div className="grid content-start gap-3 sm:grid-cols-2">
            {visibleTemplates.map((template) => (
              <TemplateChoice
                key={template.id}
                template={template}
                selected={template.id === selected.id}
                added={existingTemplateIds.has(template.id)}
                onSelect={() => setSelectedId(template.id)}
              />
            ))}
          </div>

          <Card className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wide text-brand-600">Template collection</div>
                <h3 className="mt-1 text-h3 text-ink-primary">{selected.name}</h3>
                <p className="mt-1 text-small text-ink-secondary">{selected.description}</p>
              </div>
              <IconSparkles size={19} className="text-ai" />
            </div>

            <div className="mt-4">
              <div className="text-small font-medium text-ink-primary">Dashboards included</div>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {selected.dashboards.map((dashboard) => (
                  <div key={dashboard.key} className="flex items-center gap-2 text-small text-ink-secondary">
                    <DashboardTemplateIconView name={dashboard.icon} size={15} />
                    <span>{dashboard.name}</span>
                  </div>
                ))}
              </div>
            </div>

            <label className="mt-4 block text-small font-medium text-ink-secondary" htmlFor="dashboard-template-group-name">Dashboard group name</label>
            <input id="dashboard-template-group-name" value={groupName} onChange={(event) => setGroupName(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none" />

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div>
                <label className="block text-small font-medium text-ink-secondary" htmlFor="template-dimension-label">Dimension label</label>
                <input id="template-dimension-label" value={dimensionLabel} onChange={(event) => setDimensionLabel(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none" />
                <div className="mt-1 text-[11px] text-ink-tertiary">Examples: Site, Region, Plant or Business Unit</div>
              </div>
              <div>
                <label className="block text-small font-medium text-ink-secondary" htmlFor="template-value-source">Values supplied by</label>
                <select id="template-value-source" value={valueSource} onChange={(event) => setValueSource(event.target.value as "query" | "manual")} className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none">
                  <option value="query">Query result</option>
                  <option value="manual">Manual entry</option>
                </select>
              </div>
            </div>

            {valueSource === "query" ? (
              <div className="mt-3">
                <label className="block text-small font-medium text-ink-secondary" htmlFor="template-query">Select query</label>
                <select id="template-query" value={queryId ?? ""} onChange={(event) => setQueryId(Number(event.target.value))} className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none">
                  <option value="" disabled>Select a saved query…</option>
                  {savedQueries.map((query) => <option key={query.id} value={query.id}>{query.name}</option>)}
                </select>
                <div className="mt-1 text-[11px] text-ink-tertiary">The first result column supplies the selectable values.</div>
              </div>
            ) : (
              <div className="mt-3">
                <label className="block text-small font-medium text-ink-secondary" htmlFor="template-manual-values">Enter values, separated by commas</label>
                <input id="template-manual-values" value={manualValues} onChange={(event) => setManualValues(event.target.value)} placeholder="Costa Mesa, Carson, Lamphun, CMX" className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none" />
                <div className="mt-1 text-[11px] text-ink-tertiary">Each value becomes a selectable dashboard parameter.</div>
              </div>
            )}

            <label className="mt-3 block text-small font-medium text-ink-secondary" htmlFor="template-default-period">Default period</label>
            <select id="template-default-period" value={defaultPeriod} onChange={(event) => setDefaultPeriod(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none">
              <option value="30_days">30 days</option><option value="60_days">60 days</option><option value="90_days">90 days</option><option value="6_months">6 months</option><option value="1_year">1 year</option><option value="2_years">2 years</option>
            </select>

            <div className="mt-4 rounded-md bg-bg-secondary/60 p-3 text-small text-ink-secondary">
              <div className="flex items-center gap-2 font-medium text-ink-primary"><IconSparkles size={15} />AI-managed insight widgets</div>
              <div className="mt-1">Operational Brief and Best Improvement Opportunities are created from governed project data and remain editable.</div>
            </div>

            {progress && <div className="mt-3 text-small text-ink-tertiary" aria-live="polite">{progress}</div>}
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <Button variant="secondary" onClick={onClose}>Cancel</Button>
              {builtIn && alreadyAdded ? (
                <Button variant="primary" onClick={() => onOpenExisting(selected.id)}>Open dashboard group</Button>
              ) : (
                <Button variant="primary" onClick={create} disabled={creating}>
                  <IconSparkles size={14} />
                  {creating ? "Creating with AI…" : `Create ${selected.dashboards.length} dashboards`}
                </Button>
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function TemplateChoice({
  template,
  selected,
  added,
  onSelect,
}: {
  template: DashboardTemplateDefinition;
  selected: boolean;
  added: boolean;
  onSelect: () => void;
}) {
  return (
    <button type="button" onClick={onSelect} aria-pressed={selected} className={cn("grid min-h-[112px] grid-cols-[44px_1fr] items-center gap-3 rounded-lg border bg-bg-primary p-4 text-left transition-colors", selected ? "border-brand-500 ring-1 ring-brand-200" : "border-line-secondary hover:border-line-primary")}>
      <span className="grid h-11 w-11 place-items-center rounded-full bg-brand-50 text-brand-700"><DashboardTemplateIconView name={template.icon} /></span>
      <span className="min-w-0 self-center">
        <span className="block text-small font-semibold text-ink-primary">{template.name}</span>
        <span className="mt-1 block text-[11px] leading-4 text-ink-tertiary">{template.description}</span>
        {added && <span className="mt-2 inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-600"><IconCheck size={12} />Added</span>}
      </span>
    </button>
  );
}
