"use client";

import { useRef, useState } from "react";
import { IconCloudUpload, IconLoader2 } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import {
  useBuilderStore,
  type SessionSource,
} from "@/lib/stores/data-source-builder-store";
import { analyzeFile } from "@/lib/api/data-source-builder";

const MAX_BYTES = 100 * 1024 * 1024;
const ALLOWED = ["csv", "xlsx", "xls"];

interface AiUploadDropzoneProps {
  /** Called after all selected files have been processed and at least one was ingested without error. */
  onUploadsDone?: () => void;
}

export function AiUploadDropzone({ onUploadsDone }: AiUploadDropzoneProps = {}) {
  const addSource = useBuilderStore((s) => s.addSource);
  const hasSource = useBuilderStore((s) => s.hasSource);
  const markCreated = useBuilderStore((s) => s.markCreated);
  const inputRef = useRef<HTMLInputElement>(null);

  const [dragActive, setDragActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ingest = async (file: File) => {
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (file.size > MAX_BYTES) {
      setError(`${file.name} exceeds 100MB. Try a database connection instead.`);
      return;
    }
    if (!ext || !ALLOWED.includes(ext)) {
      setError(`${file.name}: unsupported type. Upload .csv, .xlsx or .xls.`);
      return;
    }
    if (hasSource((s) => s.isFileUpload && s.displayName === file.name)) {
      setError(`${file.name} is already in this session.`);
      return;
    }
    const preview = await analyzeFile(file);
    const baseName = preview.file.file_name.replace(/\.[^.]+$/, "");
    const viewName = `${baseName.replace(/\s+/g, "_")}_${preview.file.file_type.toUpperCase()}`;
    const isExcel = ["xlsx", "xls"].includes(
      preview.file.file_type.toLowerCase(),
    );
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
    markCreated([source.id]);
  };

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setError(null);
    setBusy(true);
    let added = false;
    let hadError = false;
    try {
      for (const file of Array.from(files)) {
        try {
          await ingest(file);
          added = true;
        } catch (err) {
          hadError = true;
          setError(
            err instanceof Error
              ? err.message
              : `Could not read ${file.name}. Check it's a valid CSV or Excel file.`,
          );
        }
      }
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
    if (added && !hadError) onUploadsDone?.();
  };

  return (
    <div>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragActive(false);
          void handleFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
          dragActive
            ? "border-brand-500 bg-brand-50/50"
            : "border-brand-300 bg-brand-50/30 hover:border-brand-500 hover:bg-brand-50/50",
        )}
      >
        <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-brand-100 text-brand-600">
          {busy ? (
            <IconLoader2 size={24} className="animate-spin" />
          ) : (
            <IconCloudUpload size={24} />
          )}
        </span>
        <span className="flex items-center gap-2 text-[15px] font-semibold text-ink-primary">
          AI-Assisted File Upload
          <span className="rounded bg-brand-100 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-brand-700">
            AI
          </span>
        </span>
        <span className="max-w-md text-small text-ink-secondary">
          {busy
            ? "Analysing file with AI-powered column detection…"
            : "Click anywhere or drag files here to upload with AI-powered column detection and profiling."}
        </span>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.xlsx,.xls"
          multiple
          className="hidden"
          onChange={(e) => void handleFiles(e.target.files)}
        />
      </button>
      {error && <p className="mt-2 text-caption text-danger">{error}</p>}
    </div>
  );
}
