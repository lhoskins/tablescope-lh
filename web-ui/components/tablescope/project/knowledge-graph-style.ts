import type { KnowledgeGraphSeverity } from "@/lib/ui/use-project-data";

/** Visual palette per node category, aligned with the mockup color language. */
export interface NodePalette {
  bg: string;
  border: string;
  text: string;
  dot: string;
}

const PURPLE: NodePalette = {
  bg: "#F5F3FF",
  border: "#7C3AED",
  text: "#5B21B6",
  dot: "#7C3AED",
};
const ORANGE: NodePalette = {
  bg: "#FFF7ED",
  border: "#F97316",
  text: "#9A3412",
  dot: "#F97316",
};
const GREEN: NodePalette = {
  bg: "#F0FDF4",
  border: "#16A34A",
  text: "#166534",
  dot: "#16A34A",
};
const AMBER: NodePalette = {
  bg: "#FFFBEB",
  border: "#D97706",
  text: "#92400E",
  dot: "#D97706",
};
const BLUE: NodePalette = {
  bg: "#EFF6FF",
  border: "#2563EB",
  text: "#1E40AF",
  dot: "#2563EB",
};
const TEAL: NodePalette = {
  bg: "#ECFEFF",
  border: "#0D9488",
  text: "#115E59",
  dot: "#0D9488",
};
const ENTITY: NodePalette = {
  bg: "#FFF7ED",
  border: "#EA580C",
  text: "#9A3412",
  dot: "#EA580C",
};
const RED: NodePalette = {
  bg: "#FEF2F2",
  border: "#E11D48",
  text: "#9F1239",
  dot: "#E11D48",
};
const NAVY: NodePalette = {
  bg: "#0F172A",
  border: "#0F172A",
  text: "#FFFFFF",
  dot: "#0F172A",
};
const SLATE: NodePalette = {
  bg: "#F8FAFC",
  border: "#94A3B8",
  text: "#334155",
  dot: "#94A3B8",
};

const PALETTE_BY_TYPE: Record<string, NodePalette> = {
  process: ORANGE,
  document: PURPLE,
  reference_document: PURPLE,
  document_family: PURPLE,
  policy: PURPLE,
  procedure: PURPLE,
  standard: PURPLE,
  control: PURPLE,
  kpi: GREEN,
  metric: GREEN,
  threshold: GREEN,
  benchmark: GREEN,
  query: AMBER,
  saved_query: AMBER,
  dashboard: BLUE,
  data_source: TEAL,
  datasource: TEAL,
  table: TEAL,
  column: TEAL,
  entity: ENTITY,
  business_entity: ENTITY,
  supplier: ENTITY,
  customer: ENTITY,
  product: ENTITY,
  facility: ENTITY,
  contract: ENTITY,
  tag: ENTITY,
  risk: RED,
  audit_finding: RED,
  warning: AMBER,
  anomaly: AMBER,
  opportunity: GREEN,
  gap: PURPLE,
  process_gap: PURPLE,
  data_gap: PURPLE,
  compliance_gap: PURPLE,
  insight: RED,
  relationship_insight: RED,
  recommendation: ORANGE,
  action: ORANGE,
  project: NAVY,
};

export function paletteFor(type: string, isCenter = false): NodePalette {
  if (isCenter) return NAVY;
  return PALETTE_BY_TYPE[type] ?? SLATE;
}

/** Emoji-free alert sign per finding node type (rendered in the canvas flow). */
export function alertSignFor(type: string): "risk" | "warning" | "opportunity" | "gap" | "action" | null {
  if (type === "risk" || type === "audit_finding" || type === "insight" || type === "relationship_insight")
    return "risk";
  if (type === "warning" || type === "anomaly") return "warning";
  if (type === "opportunity") return "opportunity";
  if (type === "gap" || type === "process_gap" || type === "data_gap" || type === "compliance_gap")
    return "gap";
  if (type === "recommendation" || type === "action") return "action";
  return null;
}

export const SEVERITY_META: Record<
  KnowledgeGraphSeverity,
  { label: string; chip: string; accent: string }
> = {
  critical: { label: "Critical", chip: "bg-danger/10 text-danger", accent: "border-l-danger" },
  urgent: { label: "Urgent", chip: "bg-warning/10 text-warning", accent: "border-l-warning" },
  warning: { label: "Warning", chip: "bg-warning/10 text-warning", accent: "border-l-warning" },
  watch: { label: "Watch", chip: "bg-bg-tertiary text-ink-secondary", accent: "border-l-line-secondary" },
  opportunity: { label: "Opportunity", chip: "bg-success/10 text-success", accent: "border-l-success" },
  info: { label: "Info", chip: "bg-bg-tertiary text-ink-secondary", accent: "border-l-line-secondary" },
};

/** Humanize a snake_case relationship/type token for display. */
export function humanize(text: string): string {
  return text.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Legend entries, ordered to mirror the mockup. */
export const LEGEND: { label: string; type: string }[] = [
  { label: "Process (Selected)", type: "project" },
  { label: "Process", type: "process" },
  { label: "Document / Governing Doc", type: "document" },
  { label: "KPI / Metric", type: "kpi" },
  { label: "Query (Tablescope)", type: "query" },
  { label: "Dashboard (Tablescope)", type: "dashboard" },
  { label: "Data Source", type: "data_source" },
  { label: "Entity", type: "entity" },
  { label: "Insight / Finding", type: "insight" },
];
