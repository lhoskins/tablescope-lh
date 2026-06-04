"use client";

import { useState, useCallback } from "react";
import type { WidgetConfig, WidgetType, DashboardConfig } from "./types";

const WIDGET_TYPES: { type: WidgetType; label: string; icon: string }[] = [
  { type: "bar", label: "Bar Chart", icon: "📊" },
  { type: "line", label: "Line Chart", icon: "📈" },
  { type: "pie", label: "Pie / Donut", icon: "🍩" },
  { type: "area", label: "Area Chart", icon: "📉" },
  { type: "kpi", label: "KPI / Number", icon: "🔢" },
  { type: "table", label: "Data Table", icon: "📋" },
];

type SavedQuery = {
  id: number;
  name: string;
};

type Datasource = {
  viewName: string;
  fileName: string;
};

type Props = {
  projectId: number;
  savedQueries: SavedQuery[];
  datasources: Datasource[];
  onCancel: () => void;
  onSubmit: (payload: { name: string; description: string; config: DashboardConfig }) => void;
  isSubmitting: boolean;
};

export function CreateDashboardWizard({
  savedQueries,
  datasources,
  onCancel,
  onSubmit,
  isSubmitting,
}: Props) {
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [widgets, setWidgets] = useState<WidgetConfig[]>([]);

  // Widget form state
  const [wTitle, setWTitle] = useState("");
  const [wType, setWType] = useState<WidgetType>("bar");
  const [wSourceKind, setWSourceKind] = useState<"query" | "datasource">("query");
  const [wSourceId, setWSourceId] = useState("");
  const [wXKey, setWXKey] = useState("");
  const [wYKey, setWYKey] = useState("");
  const [wColSpan, setWColSpan] = useState(6);

  const addWidget = useCallback(() => {
    if (!wTitle.trim()) return;
    const w: WidgetConfig = {
      id: `w-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      type: wType,
      title: wTitle,
      dataSource:
        wSourceKind === "query"
          ? { kind: "query", queryId: Number(wSourceId) || 0 }
          : { kind: "datasource", viewName: wSourceId },
      xKey: wXKey || "category",
      yKey: wYKey || "value",
      colSpan: wColSpan,
      position: widgets.length,
    };
    setWidgets((prev) => [...prev, w]);
    setWTitle("");
    setWXKey("");
    setWYKey("");
  }, [wTitle, wType, wSourceKind, wSourceId, wXKey, wYKey, wColSpan, widgets.length]);

  const removeWidget = useCallback((id: string) => {
    setWidgets((prev) => prev.filter((w) => w.id !== id));
  }, []);

  const handleSubmit = () => {
    onSubmit({ name, description, config: { widgets } });
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
      {/* Wizard steps header */}
      <div className="flex border-b border-slate-200">
        {[
          { num: 1, label: "Name & Info" },
          { num: 2, label: "Add Widgets" },
          { num: 3, label: "Review & Create" },
        ].map((s) => (
          <div
            key={s.num}
            className={`flex-1 border-b-2 px-4 py-3 text-center text-xs font-semibold transition-colors ${
              step === s.num
                ? "border-blue-600 text-blue-600"
                : step > s.num
                ? "border-green-500 text-green-600"
                : "border-transparent text-slate-400"
            }`}
          >
            <span
              className={`mr-1 inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px] ${
                step > s.num
                  ? "bg-green-500 text-white"
                  : step === s.num
                  ? "bg-blue-600 text-white"
                  : "bg-slate-200 text-slate-400"
              }`}
            >
              {step > s.num ? "✓" : s.num}
            </span>
            {s.label}
          </div>
        ))}
      </div>

      <div className="p-6">
        {/* Step 1: Name & Info */}
        {step === 1 && (
          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-semibold text-slate-700">Dashboard Name</label>
              <input
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/10"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Q1 Revenue Overview"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-semibold text-slate-700">Description</label>
              <textarea
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/10"
                rows={3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional description..."
              />
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={onCancel} className="rounded-lg px-4 py-2 text-sm text-slate-500 hover:text-slate-700">
                Cancel
              </button>
              <button
                onClick={() => setStep(2)}
                disabled={!name.trim()}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Add Widgets */}
        {step === 2 && (
          <div className="grid grid-cols-2 gap-6">
            {/* Left: widget form */}
            <div className="space-y-4">
              <h3 className="text-base font-bold text-slate-800">Add a Widget</h3>
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-600">Widget Title</label>
                <input
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-500"
                  value={wTitle}
                  onChange={(e) => setWTitle(e.target.value)}
                  placeholder="e.g. Monthly Revenue Trend"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-600">Chart Type</label>
                <div className="grid grid-cols-3 gap-2">
                  {WIDGET_TYPES.map((wt) => (
                    <button
                      key={wt.type}
                      onClick={() => setWType(wt.type)}
                      className={`rounded-lg border-2 px-3 py-3 text-center text-xs font-semibold transition-colors ${
                        wType === wt.type
                          ? "border-blue-600 bg-blue-50 text-blue-700"
                          : "border-slate-200 text-slate-600 hover:border-blue-300 hover:bg-blue-50"
                      }`}
                    >
                      <div className="mb-1 text-xl">{wt.icon}</div>
                      {wt.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-600">Data Source</label>
                <select
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none"
                  value={`${wSourceKind}:${wSourceId}`}
                  onChange={(e) => {
                    const [kind, id] = e.target.value.split(":") as ["query" | "datasource", string];
                    setWSourceKind(kind);
                    setWSourceId(id);
                  }}
                >
                  <option value="query:">Select a data source...</option>
                  {savedQueries.map((q) => (
                    <option key={`q-${q.id}`} value={`query:${q.id}`}>
                      Saved Query: {q.name}
                    </option>
                  ))}
                  {datasources.map((ds) => (
                    <option key={`ds-${ds.viewName}`} value={`datasource:${ds.viewName}`}>
                      Datasource: {ds.fileName}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-[10px] text-slate-400">Choose a saved query or project datasource.</p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs font-semibold text-slate-600">X Axis / Category</label>
                  <input
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none"
                    value={wXKey}
                    onChange={(e) => setWXKey(e.target.value)}
                    placeholder="e.g. month"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-semibold text-slate-600">Y Axis / Value</label>
                  <input
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none"
                    value={wYKey}
                    onChange={(e) => setWYKey(e.target.value)}
                    placeholder="e.g. revenue"
                  />
                </div>
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-600">Widget Size</label>
                <div className="flex gap-2">
                  {([
                    { v: 3, l: "Small (1/4)" },
                    { v: 6, l: "Medium (1/2)" },
                    { v: 12, l: "Large (Full)" },
                  ] as const).map((s) => (
                    <button
                      key={s.v}
                      onClick={() => setWColSpan(s.v)}
                      className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                        wColSpan === s.v
                          ? "bg-blue-600 text-white"
                          : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      {s.l}
                    </button>
                  ))}
                </div>
              </div>
              <button
                onClick={addWidget}
                disabled={!wTitle.trim()}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                Add Widget
              </button>
            </div>

            {/* Right: preview list */}
            <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4">
              <h3 className="mb-3 text-sm font-semibold text-slate-500">
                Dashboard Preview ({widgets.length} widget{widgets.length !== 1 ? "s" : ""} added)
              </h3>
              {widgets.length === 0 ? (
                <div className="py-8 text-center text-xs text-slate-400">
                  No widgets yet. Use the form on the left to add widgets.
                </div>
              ) : (
                <div className="space-y-2">
                  {widgets.map((w) => (
                    <div key={w.id} className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-3 py-2">
                      <div>
                        <div className="text-xs font-semibold text-slate-700">{w.title}</div>
                        <div className="text-[10px] text-slate-400">
                          {WIDGET_TYPES.find((t) => t.type === w.type)?.label ?? w.type} · {w.colSpan === 12 ? "Full" : w.colSpan === 6 ? "Half" : "Quarter"}
                        </div>
                      </div>
                      <button
                        onClick={() => removeWidget(w.id)}
                        className="rounded p-1 text-slate-400 hover:text-red-500"
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-4 flex justify-end gap-2">
                <button onClick={() => setStep(1)} className="rounded-lg px-3 py-2 text-xs text-slate-500 hover:text-slate-700">
                  Back
                </button>
                <button
                  onClick={() => setStep(3)}
                  className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white hover:bg-blue-700"
                >
                  Next
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Step 3: Review & Create */}
        {step === 3 && (
          <div className="space-y-4">
            <h3 className="text-base font-bold text-slate-800">Review Dashboard</h3>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
              <div className="mb-1 text-sm font-semibold text-slate-800">{name}</div>
              <div className="mb-3 text-xs text-slate-500">{description || "No description"}</div>
              <div className="text-xs text-slate-500">{widgets.length} widget{widgets.length !== 1 ? "s" : ""}</div>
              <div className="mt-2 space-y-1">
                {widgets.map((w) => (
                  <div key={w.id} className="text-xs text-slate-600">
                    • {w.title} ({WIDGET_TYPES.find((t) => t.type === w.type)?.label ?? w.type})
                  </div>
                ))}
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setStep(2)} className="rounded-lg px-4 py-2 text-sm text-slate-500 hover:text-slate-700">
                Back
              </button>
              <button
                onClick={handleSubmit}
                disabled={isSubmitting || !name.trim()}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {isSubmitting ? "Creating..." : "Create Dashboard"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
