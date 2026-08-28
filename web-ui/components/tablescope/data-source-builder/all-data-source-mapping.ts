import type { AllDataSource } from "@/lib/api/data-source-catalog";
import type { SessionSource, SourceType, TableSelection } from "@/lib/stores/data-source-builder-store";

const SOURCE_TYPES = new Set<SourceType>([
  "postgresql",
  "mysql",
  "snowflake",
  "bigquery",
  "servicenow",
  "salesforce",
  "hubspot",
  "quickbooks",
  "google_drive",
]);

function toSourceType(value: string | null | undefined): SourceType {
  if (!value) return "postgresql";
  if (value === "google_sheet") return "google_drive";
  if (SOURCE_TYPES.has(value as SourceType)) return value as SourceType;
  return "postgresql";
}

export function allDataSourceToSessionSource(item: AllDataSource): SessionSource {
  const isFile = item.kind === "file";
  const isSaaS = item.sourceType === "saas_object";
  const sourceType: SourceType = isFile
    ? item.connectorType === "excel" || item.connectorType === "xlsx"
      ? "excel"
      : item.connectorType === "google_sheet"
        ? "google_drive"
        : "csv"
    : isSaaS
      ? toSourceType(item.connectorType)
      : toSourceType(item.dbType);

  const table: TableSelection = {
    tableName: isFile ? item.viewName : item.name,
    rows: 0,
    cols: item.columns,
    aiEnabled: true,
    state: "adding",
  };

  return {
    id: item.id,
    sourceType,
    displayName: item.name,
    connectionConfig: isFile
      ? {}
      : {
          db_type: item.dbType ?? "",
          schema_name: item.schemaName ?? "",
          table_name: item.tableName ?? "",
        },
    status: "ready",
    isFileUpload: isFile,
    isSaaS,
    viewName: item.viewName,
    backendId: isFile ? undefined : item.backendId,
    existing: true,
    projectId: item.projectId,
    createdAt: item.createdAt,
    loadedAt: item.createdAt,
    tables: [table],
    fileMetadata: isFile
      ? {
          name: item.name,
          rows: 0,
          columns: Array.from({ length: item.columns }, (_, i) => `col_${i}`),
          acquisitionMethod:
            sourceType === "google_drive" ? "google_drive" : "local_upload",
          sourceHost: sourceType === "google_drive" ? "Google Drive" : undefined,
        }
      : undefined,
  };
}
