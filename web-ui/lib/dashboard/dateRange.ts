/** Named date ranges shared by editable dashboards. */
export type DatePresetId =
  | "all"
  | "today"
  | "yesterday"
  | "last_7_days"
  | "last_30_days"
  | "last_60_days"
  | "last_90_days"
  | "last_6_months"
  | "last_1_year"
  | "last_2_years"
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
  { id: "last_60_days", label: "Last 60 days" },
  { id: "last_90_days", label: "Last 90 days" },
  { id: "last_6_months", label: "Last 6 months" },
  { id: "last_1_year", label: "Last 1 year" },
  { id: "last_2_years", label: "Last 2 years" },
  { id: "this_month", label: "This month" },
  { id: "last_month", label: "Last month" },
  { id: "this_quarter", label: "This quarter" },
  { id: "this_year", label: "This year" },
  { id: "custom", label: "Custom" },
];

function iso(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function addDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

function rollingDays(today: Date, days: number) {
  return { start: iso(addDays(today, -(days - 1))), end: iso(today) };
}

export function resolveDatePreset(
  preset: DatePresetId | string,
  today: Date = new Date(),
): { start: string; end: string } | null {
  const current = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  switch (preset) {
    case "today":
      return { start: iso(current), end: iso(current) };
    case "yesterday": {
      const yesterday = addDays(current, -1);
      return { start: iso(yesterday), end: iso(yesterday) };
    }
    case "last_7_days":
      return rollingDays(current, 7);
    case "last_30_days":
      return rollingDays(current, 30);
    case "last_60_days":
      return rollingDays(current, 60);
    case "last_90_days":
      return rollingDays(current, 90);
    case "last_6_months":
      return rollingDays(current, 183);
    case "last_1_year":
      return rollingDays(current, 365);
    case "last_2_years":
      return rollingDays(current, 730);
    case "this_month":
      return {
        start: iso(new Date(current.getFullYear(), current.getMonth(), 1)),
        end: iso(new Date(current.getFullYear(), current.getMonth() + 1, 0)),
      };
    case "last_month":
      return {
        start: iso(new Date(current.getFullYear(), current.getMonth() - 1, 1)),
        end: iso(new Date(current.getFullYear(), current.getMonth(), 0)),
      };
    case "this_quarter": {
      const quarter = Math.floor(current.getMonth() / 3);
      return {
        start: iso(new Date(current.getFullYear(), quarter * 3, 1)),
        end: iso(new Date(current.getFullYear(), quarter * 3 + 3, 0)),
      };
    }
    case "this_year":
      return {
        start: iso(new Date(current.getFullYear(), 0, 1)),
        end: iso(new Date(current.getFullYear(), 11, 31)),
      };
    default:
      return null;
  }
}
