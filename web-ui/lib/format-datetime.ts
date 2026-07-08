/**
 * Shared human-readable date/time formatting.
 *
 * Renders in the browser's local timezone (the app has no per-tenant timezone),
 * using a short month, day, year and 12-hour clock with AM/PM — e.g.
 * "Jun 21, 2026 3:45 PM". Built explicitly (rather than via Intl) so the exact
 * separators are stable across locales and never a raw ISO timestamp.
 */
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

export function formatDateTime(value: Date | string | number | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return null;

  const month = MONTHS[date.getMonth()];
  const day = date.getDate();
  const year = date.getFullYear();

  const rawHours = date.getHours();
  const ampm = rawHours >= 12 ? "PM" : "AM";
  const hours = rawHours % 12 === 0 ? 12 : rawHours % 12;
  const minutes = String(date.getMinutes()).padStart(2, "0");

  return `${month} ${day}, ${year} ${hours}:${minutes} ${ampm}`;
}

/** Same as {@link formatDateTime} but prefixed with "Last updated: ". */
export function formatLastUpdated(
  value: Date | string | number | null | undefined,
): string | null {
  const formatted = formatDateTime(value);
  return formatted === null ? null : `Last updated: ${formatted}`;
}
