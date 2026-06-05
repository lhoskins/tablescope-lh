"use client";

import { useState } from "react";
import type { WidgetConfig, DashboardConfig } from "./types";
import { WidgetConfigPanel } from "./WidgetConfigPanel";

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
  projectId,
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
  const [showAddWidget, setShowAddWidget] = useState(false);

  const handleAddWidget = (widget: WidgetConfig) => {
    setWidgets([...widgets, { ...widget, position: widgets.length }]);
    setShowAddWidget(false);
  };

  const handleRemoveWidget = (idx: number) => {
    setWidgets(widgets.filter((_, i) => i !== idx));
  };

  const handleSubmit = () => {
    onSubmit({
      name,
      description,
      config: { widgets, globalFilters: [] },
    });
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
      {/* Header */}
      <div className="border-b border-slate-100 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-slate-800">Create Dashboard</h2>
            <p className="text-xs text-slate-500">Step {step} of 3</p>
          </div>
          <button
            onClick={onCancel}
            className="text-xs font-medium text-slate-500 hover:text-slate-700"
          >
            Cancel
          </button>
        </div>
        {/* Step indicators */}
        <div className="mt-3 flex gap-2">
          {[1, 2, 3].map((s) => (
            <div
              key={s}
              className={`h-1.5 flex-1 rounded-full ${s <= step ? "bg-blue-600" : "bg-slate-200"}`}
            />
          ))}
        </div>
      </div>

      {/* Step 1: Name & Description */}
      {step === 1 && (
        <div className="p-6">
          <div className="mb-4">
            <label className="mb-1 block text-xs font-semibold text-slate-700">Dashboard Name</label>
            <input
              className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-500"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Q1 Sales Performance"
            />
          </div>
          <div className="mb-4">
            <label className="mb-1 block text-xs font-semibold text-slate-700">Description (optional)</label>
            <textarea
              className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-500"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this dashboard show?"
              rows={2}
            />
          </div>
          <div className="flex justify-end">
            <button
              onClick={() => setStep(2)}
              disabled={!name.trim()}
              className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white disabled:opacity-50"
            >
              Next: Add Widgets
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Add Widgets (using enhanced WidgetConfigPanel) */}
      {step === 2 && (
        <div className="p-6">
          {/* Widget list */}
          {widgets.length > 0 && (
            <div className="mb-4 space-y-2">
              {widgets.map((w, idx) => (
                <div
                  key={w.id}
                  className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-4 py-2"
                >
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-medium text-slate-700">
                      {idx + 1}. {w.title}
                    </span>
                    <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-bold text-blue-700">
                      {w.type}
                    </span>
                    {w.aggregation && (
                      <span className="rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-bold text-sky-700">
                        {w.aggregation.toUpperCase()}({w.yColumn})
                      </span>
                    )}
                    {w.dateGranularity && (
                      <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-700">
                        {w.dateGranularity}
                      </span>
                    )}
                  </div>
                  <button
                    onClick={() => handleRemoveWidget(idx)}
                    className="text-xs text-red-500 hover:text-red-700"
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Add Widget panel */}
          {showAddWidget ? (
            <WidgetConfigPanel
              projectId={projectId}
              savedQueries={savedQueries}
              datasources={datasources}
              onSave={handleAddWidget}
              onCancel={() => setShowAddWidget(false)}
            />
          ) : (
            <button
              onClick={() => setShowAddWidget(true)}
              className="mb-4 w-full rounded-lg border-2 border-dashed border-slate-200 py-6 text-xs font-medium text-slate-500 hover:border-blue-400 hover:text-blue-600"
            >
              + Add Widget
            </button>
          )}

          <div className="flex justify-between">
            <button
              onClick={() => setStep(1)}
              className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium hover:bg-slate-50"
            >
              Back
            </button>
            <button
              onClick={() => setStep(3)}
              disabled={widgets.length === 0}
              className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white disabled:opacity-50"
            >
              Next: Review
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Review & Create */}
      {step === 3 && (
        <div className="p-6">
          <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
            <h3 className="text-sm font-bold text-slate-800">{name}</h3>
            {description && <p className="mt-1 text-xs text-slate-500">{description}</p>}
            <div className="mt-3 space-y-1">
              {widgets.map((w, idx) => (
                <div key={w.id} className="flex items-center gap-2 text-xs text-slate-600">
                  <span className="font-medium">{idx + 1}.</span>
                  <span>{w.title}</span>
                  <span className="rounded bg-blue-100 px-1 py-0.5 text-[9px] font-bold text-blue-700">
                    {w.type}
                  </span>
                  <span className="rounded bg-sky-100 px-1 py-0.5 text-[9px] font-bold text-sky-700">
                    {w.aggregation.toUpperCase()}({w.yColumn})
                  </span>
                  {w.dateGranularity && (
                    <span className="rounded bg-amber-100 px-1 py-0.5 text-[9px] font-bold text-amber-700">
                      by {w.dateGranularity}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="flex justify-between">
            <button
              onClick={() => setStep(2)}
              className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium hover:bg-slate-50"
            >
              Back
            </button>
            <button
              onClick={handleSubmit}
              disabled={isSubmitting}
              className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white disabled:opacity-50"
            >
              {isSubmitting ? "Creating..." : "Create Dashboard"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
