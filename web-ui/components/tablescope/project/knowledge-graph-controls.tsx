"use client";

import { paletteFor, humanize, LEGEND } from "./knowledge-graph-style";
import type { RelationshipStrength } from "@/lib/ui/use-project-data";

// The relationship-evidence filter: each class maps to a connector style on the
// canvas. Explicit + inferred show by default; recommended/hidden are opt-in.
type ConnectorKind = "solid" | "dotted" | "dashed";

const STRENGTHS: {
  value: RelationshipStrength;
  label: string;
  hint: string;
  preview: ConnectorKind;
}[] = [
  { value: "explicit", label: "Explicit", hint: "Stated / validated in project evidence", preview: "solid" },
  { value: "inferred", label: "Inferred", hint: "High-confidence inference", preview: "dotted" },
  { value: "recommended", label: "Recommended", hint: "Best-practice suggestion (off by default)", preview: "dashed" },
  { value: "weak", label: "Weak / Hidden", hint: "Low-confidence links (off by default)", preview: "dotted" },
];

// Connector-style legend (line appearance ↔ evidence class).
const CONNECTOR_LEGEND: { label: string; preview: ConnectorKind | "hidden" }[] = [
  { label: "Solid — Explicit / validated", preview: "solid" },
  { label: "Dotted — Inferred / high confidence", preview: "dotted" },
  { label: "Dashed — Recommended / best practice", preview: "dashed" },
  { label: "Hidden — Weak / unsupported", preview: "hidden" },
];

function ConnectorPreview({ kind }: { kind: ConnectorKind | "hidden" }) {
  if (kind === "hidden") {
    return (
      <svg width="22" height="6" className="shrink-0">
        <line x1="0" y1="3" x2="22" y2="3" stroke="#e2e8f0" strokeWidth={1} strokeDasharray="1 4" />
      </svg>
    );
  }
  const stroke = kind === "dashed" ? "#fbbf24" : kind === "solid" ? "#94a3b8" : "#cbd5e1";
  const dash = kind === "solid" ? undefined : kind === "dashed" ? "8 6" : "4 4";
  return (
    <svg width="22" height="6" className="shrink-0">
      <line x1="0" y1="3" x2="22" y2="3" stroke={stroke} strokeWidth={1.5} strokeDasharray={dash} />
    </svg>
  );
}

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
  strengths: Set<RelationshipStrength>;
  onToggleStrength: (value: RelationshipStrength) => void;
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
  strengths,
  onToggleStrength,
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

      {/* Relationship evidence (connector-style policy) */}
      <div>
        <div className="mb-1.5 text-small font-medium text-ink-secondary">
          Relationship Evidence
        </div>
        <div className="space-y-1">
          {STRENGTHS.map((s) => (
            <label
              key={s.value}
              title={s.hint}
              className="flex cursor-pointer items-center gap-2 text-small text-ink-secondary"
            >
              <input
                type="checkbox"
                checked={strengths.has(s.value)}
                onChange={() => onToggleStrength(s.value)}
                className="accent-brand"
              />
              <ConnectorPreview kind={s.preview} />
              <span className="flex-1 truncate">{s.label}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Connector style legend (line appearance ↔ evidence class) */}
      <div>
        <div className="mb-1.5 text-small font-medium text-ink-secondary">
          Connector Styles
        </div>
        <div className="space-y-1">
          {CONNECTOR_LEGEND.map((entry) => (
            <div
              key={entry.label}
              className="flex items-center gap-2 text-small text-ink-tertiary"
            >
              <ConnectorPreview kind={entry.preview} />
              <span className="flex-1 truncate">{entry.label}</span>
            </div>
          ))}
        </div>
      </div>

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
