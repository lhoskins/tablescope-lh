import type { MyDataSource } from "@/lib/api/data-source-builder";
import type {
  SessionSource,
  SourceType,
} from "@/lib/stores/data-source-builder-store";

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

/**
 * Convert the caller's already-created data sources (from the backend) into
 * session sources flagged `existing`, so they show in the Active / Available
 * lists, can be reviewed, and can be (re)assigned to projects.
 */
export function buildExistingSources(items: MyDataSource[]): SessionSource[] {
  return items.map((item): SessionSource => {
    if (item.kind === "file") {
      const fmt = item.sourceFormat?.toLowerCase();
      const sourceType: SourceType =
        fmt === "excel" || fmt === "xlsx" || fmt === "xls" ? "excel" : "csv";
      return {
        id: `existing-file-${item.id}`,
        sourceType,
        displayName: item.name,
        connectionConfig: {},
        status: "ready",
        isFileUpload: true,
        viewName: item.viewName,
        backendId: item.id,
        existing: true,
        projectId: item.projectId,
        createdAt: item.createdAt,
        loadedAt: item.createdAt,
        fileMetadata: {
          name: item.name,
          rows: 0,
          columns: Array.from({ length: item.columns }, (_, i) => `col_${i}`),
        },
        tables: [
          {
            tableName: item.viewName,
            rows: 0,
            cols: item.columns,
            aiEnabled: true,
            state: "unselected" as const,
          },
        ],
      };
    }
    const isSaaS = item.sourceType === "saas_object";
    const sourceType = isSaaS
      ? toSourceType(item.connectorType)
      : toSourceType(item.dbType);
    return {
      id: `existing-db-${item.id}`,
      sourceType,
      displayName: item.name,
      connectionConfig: {
        db_type: item.dbType ?? "",
        schema_name: item.schemaName ?? "",
      },
      status: "ready",
      isFileUpload: false,
      isSaaS,
      viewName: item.viewName,
      backendId: item.id,
      existing: true,
      projectId: item.projectId,
      createdAt: item.createdAt,
      loadedAt: item.createdAt,
      tables: [
        {
          // Show the data-source name (not the raw table name) in the lists.
          tableName: item.name,
          rows: 0,
          cols: item.columns,
          aiEnabled: true,
          state: "unselected" as const,
        },
      ],
    };
  });
}
