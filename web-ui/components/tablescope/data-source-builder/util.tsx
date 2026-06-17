import {
  IconDatabase,
  IconApi,
  IconFileSpreadsheet,
  IconServer,
  type Icon,
} from "@tabler/icons-react";
import type {
  SourceStatus,
  SourceType,
} from "@/lib/stores/data-source-builder-store";

export type SourceCategory = "database" | "api" | "file" | "warehouse";

export const CONNECTOR_LABELS: Record<SourceType, string> = {
  postgresql: "PostgreSQL",
  mysql: "MySQL/MariaDB",
  rest_api: "REST API",
  csv: "CSV file",
  excel: "Excel file",
  snowflake: "Snowflake",
  bigquery: "BigQuery",
};

export function connectorIcon(sourceType: SourceType): Icon {
  switch (sourceType) {
    case "rest_api":
      return IconApi;
    case "csv":
    case "excel":
      return IconFileSpreadsheet;
    case "snowflake":
    case "bigquery":
      return IconServer;
    default:
      return IconDatabase;
  }
}

export function categoryFor(sourceType: SourceType): SourceCategory {
  switch (sourceType) {
    case "rest_api":
      return "api";
    case "csv":
    case "excel":
      return "file";
    case "snowflake":
    case "bigquery":
      return "warehouse";
    default:
      return "database";
  }
}

export const STATUS_TONE: Record<
  SourceStatus,
  { label: string; tone: "brand" | "success" | "warning" | "danger" | "neutral" }
> = {
  configuring: { label: "Configuring", tone: "neutral" },
  connected: { label: "Active", tone: "brand" },
  ready: { label: "Ready", tone: "success" },
  auth_required: { label: "Auth", tone: "warning" },
  error: { label: "Error", tone: "danger" },
};

export function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}K`;
  return String(n);
}
