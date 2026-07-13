/** Semantic insight palette — single source of truth for Business Insight
 * and Project Insight. Tailwind token classes only; no hex values. */

export const SUMMARY_TONES = {
  danger: {
    box: "border-danger/40 bg-danger/5",
    label: "text-danger",
  },
  warning: {
    box: "border-warning/40 bg-warning/5",
    label: "text-warning",
  },
  success: {
    box: "border-success/40 bg-success/5",
    label: "text-success",
  },
  brand: {
    box: "border-brand-500/40 bg-brand-50",
    label: "text-brand-700",
  },
} as const;

export const CARD_SEVERITY = {
  critical: {
    accent: "border-l-danger",
    chip: "bg-danger/10 text-danger",
    label: "Critical",
  },
  urgent: {
    accent: "border-l-danger",
    chip: "bg-danger/10 text-danger",
    label: "Urgent",
  },
  warning: {
    accent: "border-l-warning",
    chip: "bg-warning/10 text-warning",
    label: "Warning",
  },
  watch: {
    accent: "border-l-line-secondary",
    chip: "bg-bg-tertiary text-ink-secondary",
    label: "Watch",
  },
  trend: {
    accent: "border-l-brand-500",
    chip: "bg-brand-50 text-brand-700",
    label: "Trend",
  },
  opportunity: {
    accent: "border-l-success",
    chip: "bg-success/10 text-success",
    label: "Opportunity",
  },
  recommendation: {
    accent: "border-l-brand-500",
    chip: "bg-brand-50 text-brand-700",
    label: "Recommendation",
  },
  informational: {
    accent: "border-l-line-secondary",
    chip: "bg-bg-tertiary text-ink-secondary",
    label: "Informational",
  },
  // Home Intelligence uses the shorter ``info`` key; kept as an alias of
  // ``informational`` so both pages share one map without a data-type change.
  info: {
    accent: "border-l-line-secondary",
    chip: "bg-bg-tertiary text-ink-secondary",
    label: "Info",
  },
} as const;

export type SummaryTone = keyof typeof SUMMARY_TONES;
export type CardSeverityKey = keyof typeof CARD_SEVERITY;
