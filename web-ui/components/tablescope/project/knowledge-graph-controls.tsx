"use client";

import { paletteFor, humanize, LEGEND } from "./knowledge-graph-style";

const LENSES: { value: string; label: string }[] = [
  { value: "insight-first", label: "Insight-First" },
  { value: "document-centric", label: "Document-Centric" },
  { value: "process-centric", label: "Process-Centric" },
  { value: "kpi-centric", label: "KPI-Centric" },
  { value: "lineage", label: "Lineage" },
  { value: "evidence", label: "Evidence" },
  { value: "audit", label: "Audit" },
  { value: "anomaly", label: "Anomaly" },
  { value: "process-improvement", label: "Process Improvement" },
  { value: "compliance", label: "Compliance" },
];

interface ControlsProps {
  lens: string;
  onLensChange: (lens: string) => void;
  minConfidence: number;
  onMinConfidenceChange: (value: number) => void;
  includeInferred: boolean;
  onIncludeInferredChange: (value: boolean) => void;
  typeCounts: { type: string; count: number }[];
  hiddenTypes: Set<string>;
  onToggleType: (type: string) => void;
  highestFirst: boolean;
  onHighestFirstChange: (value: boolean) => void;
  onReset: () => void;
}

export function KnowledgeGraphControls({
  lens,
  onLensChange,
  minConfidence,
  onMinConfidenceChange,
  includeInferred,
  onIncludeInferredChange,
  typeCounts,
  hiddenTypes,
  onToggleType,
  highestFirst,
  onHighestFirstChange,
  onReset,
}: ControlsProps) {
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-4">
      <h2 className="text-small font-semibold uppercase tracking-wide text-ink-tertiary">
        Graph Controls
      </h2>

      {/* Graph lens */}
      <div>
        <label className="mb-1 block text-small font-medium text-ink-secondary">
          Graph Lens
        </label>
        <select
          value={lens}
          onChange={(e) => onLensChange(e.target.value)}
          className="w-full rounded-md border border-line-tertiary bg-bg-primary px-2.5 py-1.5 text-body text-ink-primary"
        >
          {LENSES.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}
            </option>
          ))}
        </select>
      </div>

      {/* Confidence slider */}
      <div>
        <label className="mb-1 flex items-center justify-between text-small font-medium text-ink-secondary">
          <span>Confidence (min)</span>
          <span className="font-semibold text-ink-primary">
            {minConfidence.toFixed(2)}
          </span>
        </label>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={minConfidence}
          onChange={(e) => onMinConfidenceChange(Number(e.target.value))}
          className="w-full accent-brand"
        />
        <div className="mt-0.5 flex justify-between text-[10px] text-ink-tertiary">
          <span>0.00</span>
          <span>0.50</span>
          <span>1.00</span>
        </div>
        <label className="mt-2 flex items-center gap-2 text-small text-ink-secondary">
          <input
            type="checkbox"
            checked={includeInferred}
            onChange={(e) => onIncludeInferredChange(e.target.checked)}
            className="accent-brand"
          />
          Include inferred relationships
        </label>
      </div>

      {/* Node types */}
      <div>
        <div className="mb-1.5 text-small font-medium text-ink-secondary">
          Node Types
        </div>
        <div className="space-y-1">
          {typeCounts.map(({ type, count }) => {
            const palette = paletteFor(type);
            return (
              <label
                key={type}
                className="flex cursor-pointer items-center gap-2 text-small text-ink-secondary"
              >
                <input
                  type="checkbox"
                  checked={!hiddenTypes.has(type)}
                  onChange={() => onToggleType(type)}
                  className="accent-brand"
                />
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: palette.dot }}
                />
                <span className="flex-1 truncate">{humanize(type)}</span>
                <span className="text-ink-tertiary">{count}</span>
              </label>
            );
          })}
        </div>
      </div>

      <label className="flex items-center gap-2 text-small text-ink-secondary">
        <input
          type="checkbox"
          checked={highestFirst}
          onChange={(e) => onHighestFirstChange(e.target.checked)}
          className="accent-brand"
        />
        Highest confidence first
      </label>

      {/* Legend */}
      <div>
        <div className="mb-1.5 text-small font-medium text-ink-secondary">
          Legend
        </div>
        <div className="space-y-1">
          {LEGEND.map((entry) => {
            const palette = paletteFor(entry.type, entry.type === "project");
            return (
              <div
                key={entry.label}
                className="flex items-center gap-2 text-small text-ink-tertiary"
              >
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: palette.dot }}
                />
                {entry.label}
              </div>
            );
          })}
        </div>
      </div>

      <button
        type="button"
        onClick={onReset}
        className="mt-auto rounded-md border border-line-tertiary px-3 py-1.5 text-small font-medium text-ink-secondary hover:bg-bg-tertiary"
      >
        Reset Filters
      </button>
    </div>
  );
}
