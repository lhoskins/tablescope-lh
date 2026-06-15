/**
 * Helpers for reading AI metadata (tags / KPIs) attached to documents and data
 * sources. The shapes vary across sources, so these readers are defensive and
 * accept either strings or objects with a display label under common keys.
 */

export function metaLabel(item: unknown): string {
  if (typeof item === "string") return item;
  if (item && typeof item === "object") {
    const rec = item as Record<string, unknown>;
    for (const key of ["display_name", "name", "tag_key", "kpi_key", "label"]) {
      const v = rec[key];
      if (typeof v === "string" && v.trim()) return v;
    }
  }
  return "";
}

/** Read the first present array from `meta` among the candidate keys. */
export function metaList(
  meta: Record<string, unknown> | null | undefined,
  keys: string[],
): string[] {
  if (!meta) return [];
  for (const key of keys) {
    const v = meta[key];
    if (Array.isArray(v)) {
      return v.map(metaLabel).filter((s): s is string => Boolean(s));
    }
  }
  return [];
}
