import type {
  SessionSource,
  SourceType,
} from "@/lib/stores/data-source-builder-store";
import { CONNECTOR_LABELS } from "./util";

/** One row in the Active / Available Data Sources list. */
export interface FlatItem {
  /** `sourceId` for a file, `sourceId::tableName` for a connected table. */
  key: string;
  sourceId: string;
  sourceType: SourceType;
  /** Display name shown in the Name column. */
  name: string;
  /** Origin shown in the Source column. */
  sourceLabel: string;
  /** e.g. "csv" or "sqlserver table". */
  typeLabel: string;
  visibility: "File" | "Connected";
  columns: number;
  /** Formatted size for files; "—" for connected tables. */
  sizeOrStatus: string;
  /** Whether the item is currently selected for assignment (table "adding"). */
  selected: boolean;
  isFile: boolean;
  /** Immutable creation timestamp (ISO 8601); used for the "New" badge. */
  createdAt?: string | null;
}

function formatBytes(bytes?: number): string {
  if (!bytes || bytes <= 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Build the flat list of created data-source items from the session sources,
 * limited to keys the user has explicitly created in Step 1.
 */
export function flattenCreated(
  sources: SessionSource[],
  createdKeys: string[],
): FlatItem[] {
  const created = new Set(createdKeys);
  const items: FlatItem[] = [];

  for (const source of sources) {
    if (source.isFileUpload) {
      if (!created.has(source.id)) continue;
      const table = source.tables[0];
      items.push({
        key: source.id,
        sourceId: source.id,
        sourceType: source.sourceType,
        name: source.displayName,
        sourceLabel: source.viewName ?? source.displayName,
        typeLabel: source.sourceType === "excel" ? "excel" : "csv",
        visibility: "File",
        columns: source.fileMetadata?.columns.length ?? table?.cols ?? 0,
        sizeOrStatus: formatBytes(source.fileMetadata?.sizeBytes),
        selected: (table?.state ?? "unselected") === "adding",
        isFile: true,
        createdAt: source.createdAt,
      });
      continue;
    }
    for (const table of source.tables) {
      const key = `${source.id}::${table.tableName}`;
      if (!created.has(key)) continue;
      items.push({
        key,
        sourceId: source.id,
        sourceType: source.sourceType,
        name: table.tableName,
        sourceLabel: source.displayName,
        typeLabel: `${source.isSaaS ? "SaaS" : "table"} · ${CONNECTOR_LABELS[source.sourceType] ?? source.sourceType}`,
        visibility: "Connected",
        columns: table.cols || 0,
        sizeOrStatus: "—",
        selected: table.state === "adding",
        isFile: false,
        createdAt: source.createdAt,
      });
    }
  }

  return items;
}
