"use client";

import { useCallback, useState } from "react";
import { apiClient } from "@/lib/api-client";

type UploadResult = { path: string; size: number; datasource?: string; fileName?: string };

export function FileDropzone({
  onUploaded,
  projectId,
}: {
  onUploaded?: (result: UploadResult) => void;
  /** When set, uploaded files are auto-associated with this project. */
  projectId?: number;
}) {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState<UploadResult[]>([]);

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      setUploading(true);
      setError(null);
      for (const file of Array.from(files)) {
        try {
          const result = await apiClient.upload<UploadResult>(
            "/api/upload",
            file,
            projectId != null ? { project_id: projectId } : undefined,
          );
          setUploaded((prev) => [...prev, result]);
          onUploaded?.(result);
        } catch (e) {
          setError((e as Error).message);
        }
      }
      setUploading(false);
    },
    [onUploaded, projectId]
  );

  function onDragOver(e: React.DragEvent) {
    e.preventDefault();
    setIsDragging(true);
  }

  function onDragLeave(e: React.DragEvent) {
    e.preventDefault();
    setIsDragging(false);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  }

  function onFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(e.target.files);
      e.target.value = "";
    }
  }

  return (
    <div className="space-y-3">
      <div
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors ${
          isDragging
            ? "border-brand bg-brand/5"
            : "border-slate-300 hover:border-slate-400"
        }`}
      >
        <svg
          className="mb-3 h-10 w-10 text-slate-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"
          />
        </svg>
        <p className="text-sm text-slate-600">
          {uploading
            ? "Uploading..."
            : isDragging
            ? "Drop files here"
            : "Drag & drop files here, or click to browse"}
        </p>
        <p className="mt-1 text-xs text-slate-400">
          Supports CSV, Excel (.xlsx), and other data files
        </p>
        <label className="mt-3 cursor-pointer rounded-md bg-white px-3 py-1.5 text-sm font-medium text-brand shadow-sm ring-1 ring-inset ring-slate-300 hover:bg-slate-50">
          Browse files
          <input
            type="file"
            className="hidden"
            multiple
            disabled={uploading}
            onChange={onFileSelect}
          />
        </label>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {uploaded.length > 0 && (
        <div className="rounded-md border border-slate-200 bg-white">
          <div className="px-3 py-2 text-xs font-medium text-slate-500">
            Uploaded files
          </div>
          <ul className="divide-y divide-slate-100">
            {uploaded.map((u, i) => (
              <li key={i} className="flex items-center justify-between px-3 py-2">
                <span className="text-sm text-slate-700">
                  {u.path.split("/").pop()}
                </span>
                <span className="text-xs text-slate-400">
                  {(u.size / 1024).toFixed(1)} KB
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
