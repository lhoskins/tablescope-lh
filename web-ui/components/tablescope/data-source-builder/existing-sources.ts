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
]);

function toSourceType(dbType: string | null | undefined): SourceType {
  return dbType && SOURCE_TYPES.has(dbType as SourceType)
    ? (dbType as SourceType)
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
    return {
      id: `existing-db-${item.id}`,
      sourceType: toSourceType(item.dbType),
      displayName: item.name,
      connectionConfig: {
        db_type: item.dbType ?? "",
        schema_name: item.schemaName ?? "",
      },
      status: "ready",
      isFileUpload: false,
      viewName: item.viewName,
      backendId: item.id,
      existing: true,
      projectId: item.projectId,
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
