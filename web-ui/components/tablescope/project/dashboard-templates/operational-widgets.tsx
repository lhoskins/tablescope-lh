"use client";

import { useState } from "react";
import { IconEdit, IconSparkles } from "@tabler/icons-react";
import { apiClient } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { Dashboard } from "@/lib/ui/use-project-data";
import type { OperationalInsightWidgetConfig } from "./types";
import { operationalWidgetsOf } from "./types";

interface SuggestionResponse {
  suggestions?: Array<{
    description?: string;
    businessPurpose?: string;
    widgets?: Array<{ title?: string; businessQuestion?: string }>;
    knowledgeGraphContext?: { opportunities?: string[]; gaps?: string[]; risks?: string[] };
  }>;
}

export function OperationalInsightWidgets({
  projectId,
  dashboard,
  onUpdated,
}: {
  projectId: string;
  dashboard: Dashboard;
  onUpdated?: (dashboard: Dashboard) => void;
}) {
  const [widgets, setWidgets] = useState(() => operationalWidgetsOf(dashboard));
  const [editingId, setEditingId] = useState<string | null>(null);
  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (widgets.length === 0) return null;

  const persist = async (next: OperationalInsightWidgetConfig[]) => {
    const saved = await apiClient.put<Dashboard>(`/api/projects/${projectId}/dashboards/${dashboard.id}`, {
      config: { ...dashboard.config, operationalWidgets: next },
    });
    setWidgets(next);
    onUpdated?.(saved);
  };

  const refresh = async (widget: OperationalInsightWidgetConfig) => {
    setRefreshingId(widget.id);
    setError(null);
    try {
      const result = await apiClient.post<SuggestionResponse>("/api/ai/actions/suggest-dashboards", {
        project_id: Number(projectId),
        prompt: widget.prompt,
        audience: "operational",
        desired_count: 3,
      });
      const suggestion = result.suggestions?.[0];
      if (!suggestion) throw new Error("AI could not refresh this widget from the available project data.");
      const context = suggestion.knowledgeGraphContext;
      const next = widgets.map((item) => {
        if (item.id !== widget.id) return item;
        if (item.type === "operational_brief") {
          return { ...item, summary: suggestion.businessPurpose || suggestion.description || item.summary, items: context?.risks?.slice(0, 3) ?? item.items, updatedAt: new Date().toISOString() };
        }
        const opportunities = [...(context?.opportunities ?? []), ...(context?.gaps ?? []), ...(suggestion.widgets ?? []).map((entry) => entry.businessQuestion || entry.title || "")].filter(Boolean).slice(0, 5);
        return { ...item, items: opportunities.length ? opportunities : item.items, updatedAt: new Date().toISOString() };
      });
      await persist(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "AI refresh failed");
    } finally {
      setRefreshingId(null);
    }
  };

  return (
    <div className="mb-3 grid gap-3 lg:grid-cols-[1.35fr_.65fr]">
      {widgets.map((widget) => (
        <Card key={widget.id} className="p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-small font-semibold text-ink-primary">{widget.title}</div>
              <div className="mt-0.5 text-[11px] text-ink-tertiary">AI-managed · editable · updated {widget.updatedAt ? new Date(widget.updatedAt).toLocaleString() : "when created"}</div>
            </div>
            <div className="flex gap-1">
              <Button variant="secondary" size="sm" onClick={() => setEditingId(editingId === widget.id ? null : widget.id)}><IconEdit size={13} />Edit</Button>
              <Button variant="secondary" size="sm" onClick={() => refresh(widget)} disabled={refreshingId !== null}><IconSparkles size={13} />{refreshingId === widget.id ? "Refreshing…" : "Refresh AI"}</Button>
            </div>
          </div>
          {editingId === widget.id ? (
            <OperationalWidgetEditor
              widget={widget}
              onCancel={() => setEditingId(null)}
              onSave={async (updated) => {
                await persist(widgets.map((item) => item.id === updated.id ? updated : item));
                setEditingId(null);
              }}
            />
          ) : (
            <div className="mt-3">
              {widget.summary && <p className="text-small leading-5 text-ink-secondary">{widget.summary}</p>}
              {(widget.items ?? []).length > 0 && (
                <ol className="mt-3 space-y-2">
                  {(widget.items ?? []).map((item, index) => <li key={`${widget.id}-${index}`} className="flex gap-2 text-small text-ink-secondary"><span className="font-semibold text-brand-600">{index + 1}.</span><span>{item}</span></li>)}
                </ol>
              )}
            </div>
          )}
        </Card>
      ))}
      {error && <div className="lg:col-span-2 rounded-md bg-red-50 px-3 py-2 text-small text-red-700">{error}</div>}
    </div>
  );
}

function OperationalWidgetEditor({
  widget,
  onCancel,
  onSave,
}: {
  widget: OperationalInsightWidgetConfig;
  onCancel: () => void;
  onSave: (widget: OperationalInsightWidgetConfig) => Promise<void>;
}) {
  const [summary, setSummary] = useState(widget.summary ?? "");
  const [items, setItems] = useState((widget.items ?? []).join("\n"));
  const [saving, setSaving] = useState(false);
  return (
    <div className="mt-3 space-y-2">
      {widget.type === "operational_brief" && <textarea aria-label="Operational brief" value={summary} onChange={(event) => setSummary(event.target.value)} rows={3} className="w-full rounded-md border border-line-secondary bg-bg-primary p-2 text-small text-ink-primary focus:border-brand-500 focus:outline-none" />}
      <textarea aria-label="Insight items" value={items} onChange={(event) => setItems(event.target.value)} rows={4} className="w-full rounded-md border border-line-secondary bg-bg-primary p-2 text-small text-ink-primary focus:border-brand-500 focus:outline-none" />
      <div className="flex justify-end gap-2">
        <Button variant="secondary" size="sm" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" size="sm" disabled={saving} onClick={async () => { setSaving(true); await onSave({ ...widget, summary: summary.trim(), items: items.split("\n").map((item) => item.trim()).filter(Boolean), updatedAt: new Date().toISOString() }); setSaving(false); }}>{saving ? "Saving…" : "Save"}</Button>
      </div>
    </div>
  );
}
