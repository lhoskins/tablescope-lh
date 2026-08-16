"use client";

import { useRef, useState } from "react";
import { IconArrowsMove, IconEdit, IconSparkles } from "@tabler/icons-react";
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
  const [arranging, setArranging] = useState(false);
  const dragged = useRef<string | undefined>(undefined);
  if (widgets.length === 0) return null;

  const persist = async (next: OperationalInsightWidgetConfig[]) => {
    const saved = await apiClient.put<Dashboard>(`/api/projects/${projectId}/dashboards/${dashboard.id}`, {
      config: { ...dashboard.config, operationalWidgets: next },
    });
    setWidgets(next);
    onUpdated?.(saved);
  };

  const refresh = async (widget: OperationalInsightWidgetConfig, instruction?: string) => {
    setRefreshingId(widget.id);
    setError(null);
    try {
      const result = await apiClient.post<SuggestionResponse>("/api/ai/actions/suggest-dashboards", {
        project_id: Number(projectId),
        prompt: instruction?.trim()
          ? `${widget.prompt} User refinement: ${instruction.trim()}`
          : widget.prompt,
        audience: "operational",
        desired_count: 3,
      });
      const suggestion = result.suggestions?.[0];
      if (!suggestion) throw new Error("AI could not refresh this widget from the available project data.");
      const context = suggestion.knowledgeGraphContext;
      const next = widgets.map((item) => {
        if (item.id !== widget.id) return item;
        if (item.type === "operational_brief") {
          return { ...item, prompt: instruction?.trim() ? `${item.prompt} User refinement: ${instruction.trim()}` : item.prompt, summary: suggestion.businessPurpose || suggestion.description || item.summary, items: context?.risks?.slice(0, 3) ?? item.items, updatedAt: new Date().toISOString() };
        }
        const opportunities = [...(context?.opportunities ?? []), ...(context?.gaps ?? []), ...(suggestion.widgets ?? []).map((entry) => entry.businessQuestion || entry.title || "")].filter(Boolean).slice(0, 5);
        return { ...item, prompt: instruction?.trim() ? `${item.prompt} User refinement: ${instruction.trim()}` : item.prompt, items: opportunities.length ? opportunities : item.items, updatedAt: new Date().toISOString() };
      });
      await persist(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "AI refresh failed");
    } finally {
      setRefreshingId(null);
    }
  };

  const reorder = async (targetId: string) => {
    const sourceId = dragged.current;
    if (!sourceId || sourceId === targetId) return;
    const ordered = [...widgets].sort((a, b) => (a.layout?.position ?? 0) - (b.layout?.position ?? 0));
    const sourceIndex = ordered.findIndex((item) => item.id === sourceId);
    const targetIndex = ordered.findIndex((item) => item.id === targetId);
    if (sourceIndex < 0 || targetIndex < 0) return;
    const [source] = ordered.splice(sourceIndex, 1);
    ordered.splice(targetIndex, 0, source);
    await persist(ordered.map((item, position) => ({ ...item, layout: { position, width: item.layout?.width ?? "standard" } })));
  };
  const resize = (id: string) => persist(widgets.map((item) => item.id === id ? { ...item, layout: { position: item.layout?.position ?? 0, width: item.layout?.width === "wide" ? "standard" : "wide" } } : item));

  return (
    <div className="mb-3">
      <div className="mb-2 flex justify-end"><Button variant="secondary" size="sm" onClick={() => setArranging((value) => !value)}><IconArrowsMove size={13} />{arranging ? "Done arranging" : "Arrange operational sections"}</Button></div>
      <div className="grid grid-cols-12 gap-3">
      {[...widgets].sort((a, b) => (a.layout?.position ?? 0) - (b.layout?.position ?? 0)).map((widget) => (
        <Card key={widget.id} draggable={arranging} onDragStart={() => { dragged.current = widget.id; }} onDragOver={(event) => arranging && event.preventDefault()} onDrop={(event) => { if (arranging) { event.preventDefault(); void reorder(widget.id); } }} className={`${widget.layout?.width === "wide" ? "col-span-12" : "col-span-12 lg:col-span-6"} p-4 ${arranging ? "cursor-grab border-dashed" : ""}`}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-small font-semibold text-ink-primary">{widget.title}</div>
              <div className="mt-0.5 text-[11px] text-ink-tertiary">AI-managed · editable · updated {widget.updatedAt ? new Date(widget.updatedAt).toLocaleString() : "when created"}</div>
            </div>
            <div className="flex gap-1">
              {arranging && <Button variant="secondary" size="sm" onClick={() => resize(widget.id)}>{widget.layout?.width === "wide" ? "Half width" : "Full width"}</Button>}
              <Button variant="secondary" size="sm" onClick={() => setEditingId(editingId === widget.id ? null : widget.id)}><IconEdit size={13} />Edit with AI</Button>
              <Button variant="secondary" size="sm" onClick={() => refresh(widget)} disabled={refreshingId !== null}><IconSparkles size={13} />{refreshingId === widget.id ? "Refreshing…" : "Refresh AI"}</Button>
            </div>
          </div>
          {editingId === widget.id ? (
            <OperationalWidgetEditor
              widget={widget}
              onCancel={() => setEditingId(null)}
              onApply={async (instruction) => {
                await refresh(widget, instruction);
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
      {error && <div className="col-span-12 rounded-md bg-red-50 px-3 py-2 text-small text-red-700">{error}</div>}
      </div>
    </div>
  );
}

function OperationalWidgetEditor({
  widget,
  onCancel,
  onApply,
}: {
  widget: OperationalInsightWidgetConfig;
  onCancel: () => void;
  onApply: (instruction: string) => Promise<void>;
}) {
  const [instruction, setInstruction] = useState("");
  const [saving, setSaving] = useState(false);
  return (
    <div className="mt-3 space-y-2">
      <label className="block text-small font-medium text-ink-secondary" htmlFor={`operational-ai-instruction-${widget.id}`}>Tell AI what should change</label>
      <textarea id={`operational-ai-instruction-${widget.id}`} aria-label="AI edit instruction" value={instruction} onChange={(event) => setInstruction(event.target.value)} rows={3} placeholder={widget.type === "operational_brief" ? "Example: Focus the brief on major-incident risk and the sites contributing most to breaches." : "Example: Prioritize opportunities by SLA impact and estimated backlog reduction."} className="w-full rounded-md border border-line-secondary bg-bg-primary p-2 text-small text-ink-primary focus:border-brand-500 focus:outline-none" />
      <p className="text-[11px] text-ink-tertiary">AI will regenerate this section from the governed project data. No query or metric configuration is required.</p>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" size="sm" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" size="sm" disabled={saving || instruction.trim().length < 3} onClick={async () => { setSaving(true); await onApply(instruction); setSaving(false); }}>{saving ? "Applying…" : "Apply with AI"}</Button>
      </div>
    </div>
  );
}
