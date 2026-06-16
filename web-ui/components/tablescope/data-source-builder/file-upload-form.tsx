"use client";

import { useRef, useState } from "react";
import { IconLoader2, IconUpload } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import {
  useBuilderStore,
  type SessionSource,
} from "@/lib/stores/data-source-builder-store";
import {
  analyzeFile,
  type FilePreviewResult,
} from "@/lib/api/data-source-builder";

const MAX_BYTES = 100 * 1024 * 1024;

export function FileUploadForm({
  onAdded,
  onCancel,
}: {
  onAdded: () => void;
  onCancel: () => void;
}) {
  const addSource = useBuilderStore((s) => s.addSource);
  const hasSource = useBuilderStore((s) => s.hasSource);
  const inputRef = useRef<HTMLInputElement>(null);

  const [dragActive, setDragActive] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<FilePreviewResult | null>(null);

  const handleFile = async (file: File) => {
    setError(null);
    if (file.size > MAX_BYTES) {
      setError(
        "File exceeds 100MB. Try splitting it or connect via database instead.",
      );
      return;
    }
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!ext || !["csv", "xlsx", "xls"].includes(ext)) {
      setError("Unsupported file type. Upload a .csv, .xlsx or .xls file.");
      return;
    }
    setAnalyzing(true);
    try {
      const result = await analyzeFile(file);
      setPreview(result);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not read this file. Check it's a valid CSV or Excel file and try again.",
      );
    } finally {
      setAnalyzing(false);
    }
  };

  const handleAdd = () => {
    if (!preview) return;
    const baseName = preview.file.file_name.replace(/\.[^.]+$/, "");
    const viewName = `${baseName.replace(/\s+/g, "_")}_${preview.file.file_type.toUpperCase()}`;
    if (hasSource((s) => s.isFileUpload && s.displayName === preview.file.file_name)) {
      setError("This source is already in your session.");
      return;
    }
    const isExcel = ["xlsx", "xls"].includes(preview.file.file_type.toLowerCase());
    const source: SessionSource = {
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
        uploadSessionId: preview.upload_session_id,
        sizeBytes: preview.file.file_size_bytes,
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
    addSource(source);
    onAdded();
  };

  return (
    <div className="space-y-3">
      {!preview ? (
        <>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragActive(false);
              const f = e.dataTransfer.files?.[0];
              if (f) void handleFile(f);
            }}
            onClick={() => inputRef.current?.click()}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors",
              dragActive
                ? "border-brand-500 bg-brand-50/40"
                : "border-line-secondary bg-bg-secondary/40 hover:border-brand-500",
            )}
          >
            {analyzing ? (
              <>
                <IconLoader2 size={22} className="animate-spin text-brand-500" />
                <p className="text-[13px] text-ink-secondary">Analysing file…</p>
              </>
            ) : (
              <>
                <IconUpload size={22} className="text-ink-tertiary" />
                <p className="text-[13px] font-medium text-ink-primary">
                  Drop file here or click to browse
                </p>
                <p className="text-caption text-ink-tertiary">
                  Accepts .csv, .xlsx, .xls — max 100MB
                </p>
              </>
            )}
            <input
              ref={inputRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void handleFile(f);
              }}
            />
          </div>
        </>
      ) : (
        <div className="space-y-2">
          <div className="rounded-md border border-line-tertiary px-3 py-2 text-[12px]">
            <p className="font-medium text-ink-primary">
              {preview.file.file_name}
            </p>
            <p className="text-ink-tertiary">
              {preview.file.row_count.toLocaleString()} rows ·{" "}
              {preview.file.column_count} columns
            </p>
          </div>
          <div className="max-h-48 overflow-y-auto rounded-md border border-line-tertiary">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-line-tertiary text-left text-caption uppercase text-ink-tertiary">
                  <th className="px-3 py-1.5 font-medium">Column</th>
                  <th className="px-3 py-1.5 font-medium">Type</th>
                  <th className="px-3 py-1.5 font-medium">Samples</th>
                </tr>
              </thead>
              <tbody>
                {preview.fields.map((f) => (
                  <tr
                    key={f.field_name}
                    className="border-b border-line-tertiary last:border-0"
                  >
                    <td className="px-3 py-1.5 font-mono text-ink-primary">
                      {f.field_name}
                    </td>
                    <td className="px-3 py-1.5 text-ink-secondary">
                      {f.detected_type ?? "string"}
                    </td>
                    <td className="px-3 py-1.5 text-ink-tertiary">
                      {(f.sample_values ?? [])
                        .slice(0, 3)
                        .map((v) => String(v))
                        .join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-md border border-danger/40 bg-danger-bg/40 px-3 py-2 text-[12px] text-danger">
          {error}
        </div>
      )}

      <div className="flex items-center justify-end gap-2 pt-1">
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        {preview && (
          <>
            <Button
              variant="secondary"
              onClick={() => {
                setPreview(null);
                setError(null);
              }}
            >
              Choose another
            </Button>
            <Button variant="primary" onClick={handleAdd}>
              Add to session
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
