/**
 * Date-range presets for the dashboard date filter.
 *
 * `resolveDatePreset` returns an inclusive {start, end} pair of ISO dates
 * (yyyy-mm-dd) for a named preset, or `null` for "all" (no constraint).
 * All math is pure and timezone-stable (uses local calendar dates) so it can
 * be unit tested with a fixed `today`.
 */

export type DatePresetId =
  | "all"
  | "today"
  | "yesterday"
  | "last_7_days"
  | "last_30_days"
  | "this_month"
  | "last_month"
  | "this_quarter"
  | "this_year"
  | "custom";

export const DATE_PRESETS: { id: DatePresetId; label: string }[] = [
  { id: "all", label: "All time" },
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "last_7_days", label: "Last 7 days" },
  { id: "last_30_days", label: "Last 30 days" },
  { id: "this_month", label: "This month" },
  { id: "last_month", label: "Last month" },
  { id: "this_quarter", label: "This quarter" },
  { id: "this_year", label: "This year" },
  { id: "custom", label: "Custom" },
];

function iso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function addDays(d: Date, n: number): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
}

/**
 * Resolve a preset to an inclusive {start, end} date pair, or null for "all"
 * / "custom" (custom ranges are supplied by the user, not derived here).
 */
export function resolveDatePreset(
  preset: DatePresetId | string,
  today: Date = new Date(),
): { start: string; end: string } | null {
  const t = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  switch (preset) {
    case "today":
      return { start: iso(t), end: iso(t) };
    case "yesterday": {
      const y = addDays(t, -1);
      return { start: iso(y), end: iso(y) };
    }
    case "last_7_days":
      return { start: iso(addDays(t, -6)), end: iso(t) };
    case "last_30_days":
      return { start: iso(addDays(t, -29)), end: iso(t) };
    case "this_month": {
      const start = new Date(t.getFullYear(), t.getMonth(), 1);
      const end = new Date(t.getFullYear(), t.getMonth() + 1, 0);
      return { start: iso(start), end: iso(end) };
    }
    case "last_month": {
      const start = new Date(t.getFullYear(), t.getMonth() - 1, 1);
      const end = new Date(t.getFullYear(), t.getMonth(), 0);
      return { start: iso(start), end: iso(end) };
    }
    case "this_quarter": {
      const q = Math.floor(t.getMonth() / 3);
      const start = new Date(t.getFullYear(), q * 3, 1);
      const end = new Date(t.getFullYear(), q * 3 + 3, 0);
      return { start: iso(start), end: iso(end) };
    }
    case "this_year":
      return {
        start: iso(new Date(t.getFullYear(), 0, 1)),
        end: iso(new Date(t.getFullYear(), 11, 31)),
      };
    case "all":
    case "custom":
    default:
      return null;
  }
}
