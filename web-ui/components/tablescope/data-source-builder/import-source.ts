import type { FilePreviewResult } from "@/lib/api/data-source-builder";
import type { SessionSource } from "@/lib/stores/data-source-builder-store";

/** Progress stages shared by all three acquisition methods. */
export type ImportStage =
  | "idle"
  | "validating"
  | "connecting"
  | "transferring"
  | "scanning"
  | "profiling"
  | "analyzing"
  | "ready"
  | "error";

export const STAGE_LABELS: Record<Exclude<ImportStage, "idle">, string> = {
  validating: "Validating source",
  connecting: "Connecting",
  transferring: "Downloading file",
  scanning: "Security scanning",
  profiling: "Profiling data",
  analyzing: "AI analysis",
  ready: "Ready to assign",
  error: "Import failed",
};

/**
 * Build the builder's session source from an import preview.
 *
 * Every acquisition method funnels through here so a URL or network import
 * produces exactly the same session shape a local upload does — the rest of
 * the builder cannot tell them apart beyond the origin badge.
 */
export function sessionSourceFromPreview(
  preview: FilePreviewResult,
): SessionSource {
  const baseName = preview.file.file_name.replace(/\.[^.]+$/, "");
  const viewName = `${baseName.replace(/\s+/g, "_")}_${preview.file.file_type.toUpperCase()}`;
  const isExcel = ["xlsx", "xls", "xlsm"].includes(
    preview.file.file_type.toLowerCase(),
  );
  return {
    id: crypto.randomUUID(),
    sourceType: isExcel ? "excel" : "csv",
    displayName: preview.file.file_name,
    connectionConfig: {},
    status: "ready",
    isFileUpload: true,
    viewName,
    fileMetadata: {
      name: preview.file.file_name,
      rows: preview.file.row_count,
      columns: preview.fields.map((f) => f.field_name),
      sheets: preview.file.sheet_name ? [preview.file.sheet_name] : undefined,
      importJobId: preview.import_job_id ?? preview.upload_session_id,
      sizeBytes: preview.file.file_size_bytes,
      acquisitionMethod: preview.acquisition_method ?? "local_upload",
      sourceHost: preview.source_host ?? undefined,
    },
    previewFields: preview.fields,
    tables: [
      {
        tableName: viewName,
        rows: preview.file.row_count,
        cols: preview.file.column_count,
        aiEnabled: true,
        state: "adding",
      },
    ],
  };
}
