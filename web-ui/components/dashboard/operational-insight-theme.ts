/** Shared visual contract for every Apache ECharts renderer. */
export const OPERATIONAL_INSIGHT_THEME = {
  palette: ["#2563eb", "#0891b2", "#10b981", "#f59e0b", "#e11d48", "#4f46e5", "#0d9488", "#9333ea", "#65a30d", "#ea580c"],
  positive: "#059669", negative: "#dc2626", warning: "#d97706",
  light: { text: "#475569", muted: "#94a3b8", axis: "#dbe3ec", grid: "#edf2f7", surface: "#ffffff" },
  dark: { text: "#cbd5e1", muted: "#94a3b8", axis: "#334155", grid: "#1e293b", surface: "#0f172a" },
} as const;

export function operationalThemeColors(isDark: boolean) { return isDark ? OPERATIONAL_INSIGHT_THEME.dark : OPERATIONAL_INSIGHT_THEME.light; }
