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

type Phase = "upload" | "analyzing" | "review" | "done";

export function AIFileUploadWizard({
  onComplete,
  projectId,
}: {
  onComplete?: () => void;
  projectId?: number;
}) {
  const [phase, setPhase] = useState<Phase>("upload");
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  // User edits
  const [tags, setTags] = useState<TagChip[]>([]);
  const [kpis, setKpis] = useState<KPIChip[]>([]);
  const [userNotes, setUserNotes] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [finalizing, setFinalizing] = useState(false);
  const [finalResult, setFinalResult] = useState<Record<string, unknown> | null>(null);

  // ── Upload & Analyze ────────────────────────────────────────────────

  const handleFileSelect = useCallback(
    async (files: FileList | File[]) => {
      const file = Array.from(files)[0];
      if (!file) return;

      setUploading(true);
      setError(null);
      setPhase("analyzing");

      try {
        const result = await apiClient.upload<AnalysisResult>(
          "/api/data-sources/upload/analyze",
          file,
          projectId != null ? { project_id: projectId } : undefined,
        );
        setAnalysis(result);
        setTags(result.tags || []);
        setKpis(
          (result.kpis || []).map((k) => ({ ...k, accepted: true }))
        );
        setDisplayName(result.file.file_name);
        setPhase("review");
      } catch (e) {
        setError((e as Error).message);
        setPhase("upload");
      } finally {
        setUploading(false);
      }
    },
    [projectId]
  );

  // ── Create Datasource ───────────────────────────────────────────────

  const handleCreate = useCallback(async () => {
    if (!analysis) return;
    setFinalizing(true);
    setError(null);

    try {
      const acceptedTagKeys = tags.filter((t) => t.accepted !== false).map((t) => t.tag_key || t.tag || t.display_name);
      const rejectedTagKeys = tags.filter((t) => t.accepted === false).map((t) => t.tag_key || t.tag || t.display_name);
      const acceptedKpiKeys = kpis.filter((k) => k.accepted !== false).map((k) => k.kpi_key);
      const rejectedKpiKeys = kpis.filter((k) => k.accepted === false).map((k) => k.kpi_key);

      const result = await apiClient.post<Record<string, unknown>>(
        "/api/data-sources/upload/finalize",
        {
          upload_session_id: analysis.upload_session_id,
          project_id: projectId,
          display_name: displayName,
          accepted_tags: tags.filter((t) => t.accepted !== false),
          accepted_tag_keys: acceptedTagKeys,
          rejected_tag_keys: rejectedTagKeys,
          accepted_kpi_keys: acceptedKpiKeys,
          rejected_kpi_keys: rejectedKpiKeys,
          user_notes: userNotes || null,
        }
      );
      setFinalResult(result);
      setPhase("done");
      onComplete?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setFinalizing(false);
    }
  }, [analysis, projectId, displayName, tags, kpis, userNotes, onComplete]);

  // ── Tag management ──────────────────────────────────────────────────

  const [newTag, setNewTag] = useState("");

  function addTag() {
    const trimmed = newTag.trim();
    if (!trimmed || tags.some((t) => (t.tag_key || t.tag) === trimmed)) return;
    setTags([...tags, { tag_key: trimmed, display_name: trimmed, tag: trimmed, source: "user", accepted: true }]);
    setNewTag("");
  }

  function removeTag(idx: number) {
    setTags(tags.filter((_, i) => i !== idx));
  }

  function toggleTag(idx: number) {
    const updated = [...tags];
    updated[idx] = { ...updated[idx], accepted: !updated[idx].accepted };
    setTags(updated);
  }

  function toggleKpi(idx: number) {
    const updated = [...kpis];
    updated[idx] = { ...updated[idx], accepted: !updated[idx].accepted };
    setKpis(updated);
  }

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
        <UploadDropzone onFileSelect={handleFileSelect} uploading={uploading} />
      )}

      {/* Phase: Analyzing */}
      {phase === "analyzing" && (
        <div className="flex flex-col items-center justify-center rounded-lg border border-slate-200 bg-white p-12">
          <div className="mb-4 h-10 w-10 animate-spin rounded-full border-4 border-blue-200 border-t-blue-600" />
          <p className="text-base font-medium text-slate-700">Analyzing file with AI...</p>
          <p className="mt-2 text-sm text-slate-400">Classifying against governed catalog</p>
        </div>
      )}

      {/* Phase: Review — single screen */}
      {phase === "review" && analysis && (
        <div className="space-y-5">
          {/* Header row */}
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-900">Review &amp; Create Datasource</h2>
            <button
              onClick={() => { setPhase("upload"); setAnalysis(null); }}
              className="text-sm text-slate-500 hover:text-slate-700 underline"
            >
              Upload different file
            </button>
          </div>

          {/* Grid: File info + AI Summary */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* File Info */}
            <div className="rounded-lg border border-slate-200 bg-white p-4">
              <h3 className="mb-2 text-xs font-medium uppercase text-slate-400">File Info</h3>
              <div className="space-y-1 text-sm">
                <p>
                  <span className="text-slate-500">Name:</span>{" "}
                  <input
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    className="ml-1 rounded border border-slate-200 px-2 py-0.5 text-sm"
                  />
                </p>
                <p><span className="text-slate-500">Type:</span> {analysis.file.file_type.toUpperCase()}</p>
                <p><span className="text-slate-500">Size:</span> {(analysis.file.file_size_bytes / 1024).toFixed(1)} KB</p>
                <p><span className="text-slate-500">Rows:</span> {analysis.file.row_count.toLocaleString()}</p>
                <p><span className="text-slate-500">Columns:</span> {analysis.file.column_count}</p>
              </div>
            </div>

            {/* AI Summary */}
            <div className="space-y-3">
              <div className="rounded-lg border border-blue-100 bg-blue-50 p-4">
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

          {/* Tags section */}
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <h3 className="mb-2 text-sm font-semibold text-slate-900">Tags</h3>
            <p className="mb-3 text-xs text-slate-400">
              Governed catalog tags. Click to toggle, &times; to remove, or add custom tags.
            </p>
            <div className="flex flex-wrap gap-2 mb-3">
              {tags.map((t, i) => (
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
                  <button onClick={() => toggleTag(i)} className="hover:opacity-70">
                    {t.display_name || t.tag}
                  </button>
                  {t.confidence != null && (
                    <span className="text-[10px] opacity-60">{(t.confidence * 100).toFixed(0)}%</span>
                  )}
                  <button onClick={() => removeTag(i)} className="ml-0.5 text-current opacity-50 hover:opacity-100">&times;</button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                value={newTag}
                onChange={(e) => setNewTag(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addTag()}
                placeholder="Add tag..."
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
              />
              <button
                onClick={addTag}
                disabled={!newTag.trim()}
                className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
              >
                + Add
              </button>
            </div>
          </div>

          {/* KPIs section */}
          {kpis.length > 0 && (
            <div className="rounded-lg border border-slate-200 bg-white p-4">
              <h3 className="mb-2 text-sm font-semibold text-slate-900">Recommended KPIs</h3>
              <p className="mb-3 text-xs text-slate-400">
                KPIs matched from the governed catalog based on this file&apos;s columns. Click to toggle.
              </p>
              <div className="flex flex-wrap gap-2">
                {kpis.map((k, i) => (
                  <span
                    key={i}
                    onClick={() => toggleKpi(i)}
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
                <div className="rounded-lg border border-amber-100 bg-amber-50 p-4">
                  <h3 className="mb-2 text-xs font-medium uppercase text-amber-600">Data Quality Notes</h3>
                  <ul className="space-y-1 text-sm text-slate-700 list-disc list-inside">
                    {analysis.data_quality_notes.map((n, i) => (
                      <li key={i}>{n}</li>
                    ))}
                  </ul>
                </div>
              )}
              {analysis.relationship_hints && analysis.relationship_hints.length > 0 && (
                <div className="rounded-lg border border-purple-100 bg-purple-50 p-4">
                  <h3 className="mb-2 text-xs font-medium uppercase text-purple-600">Relationship Hints</h3>
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
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <h3 className="mb-2 text-sm font-semibold text-slate-900">Notes (optional)</h3>
            <textarea
              value={userNotes}
              onChange={(e) => setUserNotes(e.target.value)}
              placeholder="Business context, data source origin, refresh schedule, known caveats..."
              rows={2}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>

          {/* Create Datasource button */}
          <div className="flex justify-end">
            <button
              onClick={handleCreate}
              disabled={finalizing}
              className="rounded-md bg-green-600 px-8 py-3 text-base font-medium text-white shadow-sm hover:bg-green-700 disabled:opacity-50"
            >
              {finalizing ? "Creating Datasource..." : "Create Datasource"}
            </button>
          </div>
        </div>
      )}

      {/* Phase: Done */}
      {phase === "done" && finalResult && (
        <div className="flex flex-col items-center justify-center rounded-lg border border-green-200 bg-green-50 p-12">
          <svg className="h-12 w-12 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <h3 className="mt-3 text-lg font-semibold text-green-800">Datasource Created</h3>
          <p className="mt-1 text-sm text-green-600">
            {String(finalResult.message || "Data source saved with AI metadata.")}
          </p>
          <button
            onClick={() => { setPhase("upload"); setAnalysis(null); setFinalResult(null); setTags([]); setKpis([]); setUserNotes(""); }}
            className="mt-4 rounded-md border border-green-300 px-4 py-2 text-sm font-medium text-green-700 hover:bg-green-100"
          >
            Upload Another File
          </button>
        </div>
      )}
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
        {uploading ? "Uploading & analyzing..." : "Upload a file for AI analysis"}
      </p>
      <p className="mt-1 text-sm text-slate-400">CSV, Excel (.xlsx), or TXT files</p>
      <label className="mt-4 cursor-pointer rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700">
        Choose File
        <input
          type="file"
          className="hidden"
          accept=".csv,.txt,.xlsx,.xls"
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
