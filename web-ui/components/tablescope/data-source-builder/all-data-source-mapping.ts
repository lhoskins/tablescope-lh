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
]);

function toSourceType(value: string | null | undefined): SourceType {
  return value && SOURCE_TYPES.has(value as SourceType)
    ? (value as SourceType)
    : "postgresql";
}

export function allDataSourceToSessionSource(item: AllDataSource): SessionSource {
  const isFile = item.kind === "file";
  const isSaaS = item.sourceType === "saas_object";
  const sourceType: SourceType = isFile
    ? item.connectorType === "excel" || item.connectorType === "xlsx"
      ? "excel"
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
        }
      : undefined,
  };
}
