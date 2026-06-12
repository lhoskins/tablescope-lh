"use client";

import { useState, useCallback } from "react";
import { apiClient } from "@/lib/api-client";

// ── Types ────────────────────────────────────────────────────────────────

type TagChip = {
  tag_key: string;
  display_name: string;
  tag?: string;
  tag_type?: string;
  source?: "ai" | "catalog" | "user" | "system";
  confidence?: number;
  accepted?: boolean;
  reason?: string;
};

type KPIChip = {
  kpi_key: string;
  display_name: string;
  source?: "catalog" | "user";
  confidence?: number;
  accepted?: boolean;
  field_mapping?: Record<string, string>;
  reason?: string;
};

type AnalysisResult = {
  upload_session_id: string;
  file: {
    file_name: string;
    file_type: string;
    file_size_bytes: number;
    row_count: number;
    column_count: number;
    sheet_name?: string;
  };
  summary: {
    ai_summary: string;
    ai_usage_summary: string;
    ai_quality_summary: string;
    business_domain?: string;
    process_area?: string;
  };
  fields: Array<{
    field_name: string;
    detected_type: string;
    null_count: number;
    null_percent: number;
    distinct_count: number;
    sample_values: string[];
    ai_description?: string;
  }>;
  tags: TagChip[];
  kpis?: KPIChip[];
  relationship_hints?: Array<{
    source_field: string;
    possible_target: string;
    confidence: number;
  }>;
  data_quality_notes?: string[];
  recommendations: Array<Record<string, unknown>>;
  status: string;
};

type FileEntry = {
  id: string;
  fileName: string;
  status: "analyzing" | "ready" | "creating" | "done" | "error";
  analysis: AnalysisResult | null;
  tags: TagChip[];
  kpis: KPIChip[];
  displayName: string;
  userNotes: string;
  error?: string;
  result?: Record<string, unknown>;
  newTag: string;
};

type Phase = "upload" | "processing" | "done";

export function AIFileUploadWizard({
  onComplete,
  projectId,
}: {
  onComplete?: () => void;
  projectId?: number;
}) {
  const [phase, setPhase] = useState<Phase>("upload");
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  // ── helpers to update a single file entry ──────────────────────────

  const updateFile = useCallback((id: string, patch: Partial<FileEntry>) => {
    setFiles((prev) => prev.map((f) => (f.id === id ? { ...f, ...patch } : f)));
  }, []);

  // ── Upload & Analyze ────────────────────────────────────────────────

  const handleFileSelect = useCallback(
    async (fileList: FileList | File[]) => {
      const selected = Array.from(fileList);
      if (selected.length === 0) return;

      setError(null);
      setPhase("processing");

      const entries: FileEntry[] = selected.map((f, i) => ({
        id: `${Date.now()}-${i}`,
        fileName: f.name,
        status: "analyzing" as const,
        analysis: null,
        tags: [],
        kpis: [],
        displayName: f.name,
        userNotes: "",
        newTag: "",
      }));

      setFiles((prev) => [...prev, ...entries]);

      await Promise.allSettled(
        selected.map(async (file, i) => {
          const entry = entries[i];
          try {
            const result = await apiClient.upload<AnalysisResult>(
              "/api/data-sources/upload/analyze",
              file,
              projectId != null ? { project_id: projectId } : undefined,
            );
            setFiles((prev) =>
              prev.map((f) =>
                f.id === entry.id
                  ? {
                      ...f,
                      status: "ready",
                      analysis: result,
                      tags: result.tags || [],
                      kpis: (result.kpis || []).map((k) => ({ ...k, accepted: true })),
                      displayName: result.file.file_name,
                    }
                  : f,
              ),
            );
          } catch (e) {
            setFiles((prev) =>
              prev.map((f) =>
                f.id === entry.id
                  ? { ...f, status: "error", error: (e as Error).message }
                  : f,
              ),
            );
          }
        }),
      );
    },
    [projectId],
  );

  // ── Create single datasource ──────────────────────────────────────

  const handleCreateOne = useCallback(
    async (id: string) => {
      const entry = files.find((f) => f.id === id);
      if (!entry || !entry.analysis) return;

      updateFile(id, { status: "creating", error: undefined });

      try {
        const acceptedTagKeys = entry.tags
          .filter((t) => t.accepted !== false)
          .map((t) => t.tag_key || t.tag || t.display_name);
        const rejectedTagKeys = entry.tags
          .filter((t) => t.accepted === false)
          .map((t) => t.tag_key || t.tag || t.display_name);
        const acceptedKpiKeys = entry.kpis
          .filter((k) => k.accepted !== false)
          .map((k) => k.kpi_key);
        const rejectedKpiKeys = entry.kpis
          .filter((k) => k.accepted === false)
          .map((k) => k.kpi_key);

        const result = await apiClient.post<Record<string, unknown>>(
          "/api/data-sources/upload/finalize",
          {
            upload_session_id: entry.analysis.upload_session_id,
            project_id: projectId,
            display_name: entry.displayName,
            accepted_tags: entry.tags.filter((t) => t.accepted !== false),
            accepted_tag_keys: acceptedTagKeys,
            rejected_tag_keys: rejectedTagKeys,
            accepted_kpi_keys: acceptedKpiKeys,
            rejected_kpi_keys: rejectedKpiKeys,
            user_notes: entry.userNotes || null,
          },
        );
        updateFile(id, { status: "done", result });
      } catch (e) {
        updateFile(id, { status: "ready", error: (e as Error).message });
      }
    },
    [files, projectId, updateFile],
  );

  // ── Create ALL datasources ────────────────────────────────────────

  const handleCreateAll = useCallback(async () => {
    const ready = files.filter((f) => f.status === "ready");
    await Promise.allSettled(ready.map((f) => handleCreateOne(f.id)));
    onComplete?.();
  }, [files, handleCreateOne, onComplete]);

  // ── Tag / KPI management (scoped to one file entry) ───────────────

  function addTag(id: string) {
    setFiles((prev) =>
      prev.map((f) => {
        if (f.id !== id) return f;
        const trimmed = f.newTag.trim();
        if (!trimmed || f.tags.some((t) => (t.tag_key || t.tag) === trimmed)) return { ...f, newTag: "" };
        return {
          ...f,
          tags: [...f.tags, { tag_key: trimmed, display_name: trimmed, tag: trimmed, source: "user" as const, accepted: true }],
          newTag: "",
        };
      }),
    );
  }

  function removeTag(id: string, idx: number) {
    setFiles((prev) =>
      prev.map((f) => (f.id === id ? { ...f, tags: f.tags.filter((_, i) => i !== idx) } : f)),
    );
  }

  function toggleTag(id: string, idx: number) {
    setFiles((prev) =>
      prev.map((f) => {
        if (f.id !== id) return f;
        const updated = [...f.tags];
        updated[idx] = { ...updated[idx], accepted: !updated[idx].accepted };
        return { ...f, tags: updated };
      }),
    );
  }

  function toggleKpi(id: string, idx: number) {
    setFiles((prev) =>
      prev.map((f) => {
        if (f.id !== id) return f;
        const updated = [...f.kpis];
        updated[idx] = { ...updated[idx], accepted: !updated[idx].accepted };
        return { ...f, kpis: updated };
      }),
    );
  }

  function removeFileEntry(id: string) {
    setFiles((prev) => {
      const next = prev.filter((f) => f.id !== id);
      if (next.length === 0) setPhase("upload");
      return next;
    });
  }

  // ── derived state ─────────────────────────────────────────────────

  const readyCount = files.filter((f) => f.status === "ready").length;
  const analyzingCount = files.filter((f) => f.status === "analyzing").length;
  const doneCount = files.filter((f) => f.status === "done").length;
  const allDone = files.length > 0 && doneCount === files.length;

  // ── Render ──────────────────────────────────────────────────────────

  return (
    <div className="mx-auto max-w-5xl">
      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
          <button onClick={() => setError(null)} className="ml-2 font-medium underline">
            Dismiss
          </button>
        </div>
      )}

      {/* Phase: Upload */}
      {phase === "upload" && (
        <UploadDropzone onFileSelect={handleFileSelect} uploading={false} />
      )}

      {/* Phase: Processing / Review */}
      {phase === "processing" && (
        <div className="space-y-4">
          {/* Header */}
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-900">
              Review &amp; Create Datasources
              {files.length > 1 && (
                <span className="ml-2 text-sm font-normal text-slate-400">
                  ({doneCount} of {files.length} created)
                </span>
              )}
            </h2>
            <div className="flex gap-2">
              <button
                onClick={() => {
                  const input = document.createElement("input");
                  input.type = "file";
                  input.multiple = true;
                  input.accept = ".csv,.txt,.xlsx,.xls";
                  input.onchange = () => {
                    if (input.files && input.files.length > 0) handleFileSelect(input.files);
                  };
                  input.click();
                }}
                className="text-sm text-blue-600 hover:text-blue-800 underline"
              >
                + Add more files
              </button>
            </div>
          </div>

          {/* Analyzing progress */}
          {analyzingCount > 0 && (
            <div className="flex items-center gap-3 rounded-lg border border-blue-100 bg-blue-50 px-4 py-3">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-blue-200 border-t-blue-600" />
              <p className="text-sm text-blue-700">
                Analyzing {analyzingCount} file{analyzingCount > 1 ? "s" : ""} with AI...
              </p>
            </div>
          )}

          {/* File cards */}
          {files.map((entry) => (
            <FileReviewCard
              key={entry.id}
              entry={entry}
              onToggleTag={(idx) => toggleTag(entry.id, idx)}
              onRemoveTag={(idx) => removeTag(entry.id, idx)}
              onAddTag={() => addTag(entry.id)}
              onNewTagChange={(v) => updateFile(entry.id, { newTag: v })}
              onToggleKpi={(idx) => toggleKpi(entry.id, idx)}
              onNotesChange={(v) => updateFile(entry.id, { userNotes: v })}
              onDisplayNameChange={(v) => updateFile(entry.id, { displayName: v })}
              onCreate={() => handleCreateOne(entry.id)}
              onRemove={() => removeFileEntry(entry.id)}
            />
          ))}

          {/* Create All button */}
          {readyCount > 1 && (
            <div className="flex justify-end">
              <button
                onClick={handleCreateAll}
                className="rounded-md bg-green-600 px-8 py-3 text-base font-medium text-white shadow-sm hover:bg-green-700"
              >
                Create All Datasources ({readyCount})
              </button>
            </div>
          )}

          {/* All done */}
          {allDone && (
            <div className="flex flex-col items-center justify-center rounded-lg border border-green-200 bg-green-50 p-8">
              <svg className="h-10 w-10 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <h3 className="mt-2 text-lg font-semibold text-green-800">
                {files.length === 1 ? "Datasource Created" : `All ${files.length} Datasources Created`}
              </h3>
              <button
                onClick={() => { setPhase("upload"); setFiles([]); }}
                className="mt-3 rounded-md border border-green-300 px-4 py-2 text-sm font-medium text-green-700 hover:bg-green-100"
              >
                Upload More Files
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── File Review Card ──────────────────────────────────────────────────────

function FileReviewCard({
  entry,
  onToggleTag,
  onRemoveTag,
  onAddTag,
  onNewTagChange,
  onToggleKpi,
  onNotesChange,
  onDisplayNameChange,
  onCreate,
  onRemove,
}: {
  entry: FileEntry;
  onToggleTag: (idx: number) => void;
  onRemoveTag: (idx: number) => void;
  onAddTag: () => void;
  onNewTagChange: (v: string) => void;
  onToggleKpi: (idx: number) => void;
  onNotesChange: (v: string) => void;
  onDisplayNameChange: (v: string) => void;
  onCreate: () => void;
  onRemove: () => void;
}) {
  const { analysis } = entry;

  // Analyzing
  if (entry.status === "analyzing") {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-4">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-blue-200 border-t-blue-600" />
        <span className="text-sm text-slate-600">{entry.fileName}</span>
        <span className="text-xs text-slate-400">Analyzing...</span>
        <button onClick={onRemove} className="ml-auto text-slate-400 hover:text-red-500 text-sm">&times;</button>
      </div>
    );
  }

  // Error
  if (entry.status === "error") {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-4">
        <span className="text-sm font-medium text-red-700">{entry.fileName}</span>
        <span className="text-xs text-red-500">{entry.error}</span>
        <button onClick={onRemove} className="ml-auto text-red-400 hover:text-red-600 text-sm">&times;</button>
      </div>
    );
  }

  // Done
  if (entry.status === "done") {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-green-200 bg-green-50 px-4 py-4">
        <svg className="h-5 w-5 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span className="text-sm font-medium text-green-800">{entry.displayName}</span>
        <span className="text-xs text-green-600">Datasource created</span>
      </div>
    );
  }

  // Creating
  if (entry.status === "creating") {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-4">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-green-200 border-t-green-600" />
        <span className="text-sm text-slate-600">{entry.displayName}</span>
        <span className="text-xs text-slate-400">Creating datasource...</span>
      </div>
    );
  }

  // Ready for review
  if (!analysis) return null;

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      {/* File header */}
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <span className="text-sm font-semibold text-slate-900">{entry.fileName}</span>
        <button onClick={onRemove} className="text-slate-400 hover:text-red-500 text-sm">&times;</button>
      </div>

      <div className="space-y-4 p-4">
        {/* Error within this card */}
        {entry.error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{entry.error}</div>
        )}

        {/* Grid: File info + AI Summary */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <h3 className="mb-2 text-xs font-medium uppercase text-slate-400">File Info</h3>
            <div className="space-y-1 text-sm">
              <p>
                <span className="text-slate-500">Name:</span>{" "}
                <input
                  value={entry.displayName}
                  onChange={(e) => onDisplayNameChange(e.target.value)}
                  className="ml-1 rounded border border-slate-200 px-2 py-0.5 text-sm"
                />
              </p>
              <p><span className="text-slate-500">Type:</span> {analysis.file.file_type.toUpperCase()}</p>
              <p><span className="text-slate-500">Size:</span> {(analysis.file.file_size_bytes / 1024).toFixed(1)} KB</p>
              <p><span className="text-slate-500">Rows:</span> {analysis.file.row_count.toLocaleString()}</p>
              <p><span className="text-slate-500">Columns:</span> {analysis.file.column_count}</p>
            </div>
          </div>

          <div className="space-y-3">
            <div className="rounded-lg border border-blue-100 bg-blue-50 p-3">
              <h3 className="mb-1 text-xs font-medium uppercase text-blue-600">AI Summary</h3>
              <p className="text-sm text-slate-700">{analysis.summary.ai_summary}</p>
            </div>
            {analysis.summary.business_domain && (
              <div className="flex gap-3 text-sm">
                <span className="rounded-full bg-purple-100 px-3 py-1 text-purple-700">
                  {analysis.summary.business_domain.replace(/_/g, " ")}
                </span>
                {analysis.summary.process_area && (
                  <span className="rounded-full bg-indigo-100 px-3 py-1 text-indigo-700">
                    {analysis.summary.process_area.replace(/_/g, " ")}
                  </span>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Tags */}
        <div>
          <h3 className="mb-2 text-sm font-semibold text-slate-900">Tags</h3>
          <p className="mb-2 text-xs text-slate-400">
            Governed catalog tags. Click to toggle, &times; to remove, or add custom tags.
          </p>
          <div className="flex flex-wrap gap-2 mb-2">
            {entry.tags.map((t, i) => (
              <span
                key={i}
                className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-sm cursor-pointer transition-colors ${
                  t.accepted !== false
                    ? t.source === "user"
                      ? "bg-green-100 text-green-700"
                      : "bg-blue-100 text-blue-700"
                    : "bg-slate-100 text-slate-400 line-through"
                }`}
              >
                <button onClick={() => onToggleTag(i)} className="hover:opacity-70">
                  {t.display_name || t.tag}
                </button>
                {t.confidence != null && (
                  <span className="text-[10px] opacity-60">{(t.confidence * 100).toFixed(0)}%</span>
                )}
                <button onClick={() => onRemoveTag(i)} className="ml-0.5 text-current opacity-50 hover:opacity-100">&times;</button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={entry.newTag}
              onChange={(e) => onNewTagChange(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && onAddTag()}
              placeholder="Add tag..."
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
            <button
              onClick={onAddTag}
              disabled={!entry.newTag.trim()}
              className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
            >
              + Add
            </button>
          </div>
        </div>

        {/* KPIs */}
        {entry.kpis.length > 0 && (
          <div>
            <h3 className="mb-2 text-sm font-semibold text-slate-900">Recommended KPIs</h3>
            <p className="mb-2 text-xs text-slate-400">
              KPIs matched from the governed catalog based on this file&apos;s columns. Click to toggle.
            </p>
            <div className="flex flex-wrap gap-2">
              {entry.kpis.map((k, i) => (
                <span
                  key={i}
                  onClick={() => onToggleKpi(i)}
                  className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-sm cursor-pointer transition-colors ${
                    k.accepted !== false
                      ? "bg-amber-100 text-amber-800"
                      : "bg-slate-100 text-slate-400 line-through"
                  }`}
                  title={k.reason || k.kpi_key}
                >
                  {k.display_name}
                  {k.confidence != null && (
                    <span className="text-[10px] opacity-60">{(k.confidence * 100).toFixed(0)}%</span>
                  )}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Quality & Relationships */}
        {(analysis.data_quality_notes?.length || analysis.relationship_hints?.length) ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {analysis.data_quality_notes && analysis.data_quality_notes.length > 0 && (
              <div className="rounded-lg border border-amber-100 bg-amber-50 p-3">
                <h3 className="mb-1 text-xs font-medium uppercase text-amber-600">Data Quality Notes</h3>
                <ul className="space-y-1 text-sm text-slate-700 list-disc list-inside">
                  {analysis.data_quality_notes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              </div>
            )}
            {analysis.relationship_hints && analysis.relationship_hints.length > 0 && (
              <div className="rounded-lg border border-purple-100 bg-purple-50 p-3">
                <h3 className="mb-1 text-xs font-medium uppercase text-purple-600">Relationship Hints</h3>
                <ul className="space-y-1 text-sm text-slate-700">
                  {analysis.relationship_hints.map((r, i) => (
                    <li key={i}>
                      <span className="font-medium">{r.source_field}</span>
                      <span className="mx-1 text-slate-400">&rarr;</span>
                      <span>{r.possible_target}</span>
                      <span className="ml-1 text-xs text-slate-400">({(r.confidence * 100).toFixed(0)}%)</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : null}

        {/* Notes */}
        <div>
          <h3 className="mb-1 text-sm font-semibold text-slate-900">Notes (optional)</h3>
          <textarea
            value={entry.userNotes}
            onChange={(e) => onNotesChange(e.target.value)}
            placeholder="Business context, data source origin, refresh schedule, known caveats..."
            rows={2}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        {/* Create button */}
        <div className="flex justify-end">
          <button
            onClick={onCreate}
            className="rounded-md bg-green-600 px-6 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-green-700"
          >
            Create Datasource
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Upload Dropzone ───────────────────────────────────────────────────────

function UploadDropzone({
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
