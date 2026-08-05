"use client";


import { useState, useCallback } from "react";
import { apiClient } from "@/lib/api-client";


// ── Upload Dropzone ───────────────────────────────────────────────────────

export function UploadDropzone({
  onFileSelect,
  uploading,
}: {
  onFileSelect: (files: FileList | File[]) => void;
  uploading: boolean;
}) {
  const [isDragging, setIsDragging] = useState(false);

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
      onDragLeave={(e) => { e.preventDefault(); setIsDragging(false); }}
      onDrop={(e) => {
        e.preventDefault();
        setIsDragging(false);
        if (e.dataTransfer.files.length > 0) onFileSelect(e.dataTransfer.files);
      }}
      className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-12 transition-colors ${
        isDragging ? "border-blue-400 bg-blue-50" : "border-slate-300 hover:border-slate-400"
      }`}
    >
      <svg className="mb-3 h-12 w-12 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
      </svg>
      <p className="text-base font-medium text-slate-700">
        {uploading ? "Uploading & analyzing..." : "Upload files for AI analysis"}
      </p>
      <p className="mt-1 text-sm text-slate-400">CSV, Excel (.xlsx), or TXT files — select multiple</p>
      <label className="mt-4 cursor-pointer rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700">
        Choose Files
        <input
          type="file"
          className="hidden"
          accept=".csv,.txt,.xlsx,.xls"
          multiple
          disabled={uploading}
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) {
              onFileSelect(e.target.files);
              e.target.value = "";
            }
          }}
        />
      </label>
    </div>
  );
}