"use client";

import { useState, useCallback } from "react";
import { apiClient } from "@/lib/api-client";

// ── Types ────────────────────────────────────────────────────────────────

type FieldProfile = {
  field_name: string;
  detected_type: string;
  recommended_type: string;
  max_length: number;
  min_length: number;
  nullable: boolean;
  null_count: number;
  null_percent: number;
  distinct_count: number;
  sample_values: string[];
  min_value: string | null;
  max_value: string | null;
  ai_description?: string;
  ai_quality_notes?: string;
  include_in_ai?: boolean;
};

type TagChip = {
  tag: string;
  tag_type?: string;
  source?: "ai" | "user" | "system";
  confidence?: number;
  accepted?: boolean;
};

type Recommendation = {
  client_id?: string;
  recommendation_type: string;
  title: string;
  description: string;
  severity: string;
  suggested_action?: Record<string, string>;
  status: string;
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
  };
  fields: FieldProfile[];
  tags: TagChip[];
  recommendations: Recommendation[];
  status: string;
};

type WizardStep = "upload" | "analyzing" | "summary" | "fields" | "tags" | "recommendations" | "notes" | "finalize";

const STEP_ORDER: WizardStep[] = ["upload", "analyzing", "summary", "fields", "tags", "recommendations", "notes", "finalize"];
const STEP_LABELS: Record<WizardStep, string> = {
  upload: "Upload",
  analyzing: "Analyzing",
  summary: "Summary",
  fields: "Fields",
  tags: "Tags",
  recommendations: "Recommendations",
  notes: "Notes",
  finalize: "Finalize",
};

export function AIFileUploadWizard({
  onComplete,
  projectId,
}: {
  onComplete?: () => void;
  projectId?: number;
}) {
  const [step, setStep] = useState<WizardStep>("upload");
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  // User edits
  const [tags, setTags] = useState<TagChip[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [fields, setFields] = useState<FieldProfile[]>([]);
  const [userNotes, setUserNotes] = useState("");
  const [userNuances, setUserNuances] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [finalizing, setFinalizing] = useState(false);
  const [finalResult, setFinalResult] = useState<Record<string, unknown> | null>(null);

  const stepIdx = STEP_ORDER.indexOf(step);

  // ── Upload & Analyze ────────────────────────────────────────────────

  const handleFileSelect = useCallback(
    async (files: FileList | File[]) => {
      const file = Array.from(files)[0];
      if (!file) return;

      setUploading(true);
      setError(null);
      setStep("analyzing");

      try {
        const result = await apiClient.upload<AnalysisResult>(
          "/api/data-sources/upload/analyze",
          file,
          projectId != null ? { project_id: projectId } : undefined,
        );
        setAnalysis(result);
        setTags(result.tags);
        setRecommendations(result.recommendations);
        setFields(result.fields.map((f) => ({ ...f, include_in_ai: f.include_in_ai ?? true })));
        setDisplayName(result.file.file_name);
        setStep("summary");
      } catch (e) {
        setError((e as Error).message);
        setStep("upload");
      } finally {
        setUploading(false);
      }
    },
    [projectId]
  );

  // ── Finalize ────────────────────────────────────────────────────────

  const handleFinalize = useCallback(async () => {
    if (!analysis) return;
    setFinalizing(true);
    setError(null);

    try {
      const result = await apiClient.post<Record<string, unknown>>(
        "/api/data-sources/upload/finalize",
        {
          upload_session_id: analysis.upload_session_id,
          project_id: projectId,
          display_name: displayName,
          accepted_tags: tags.filter((t) => t.accepted !== false),
          recommendation_decisions: recommendations.map((r, i) => ({
            id: i,
            status: r.status,
          })),
          user_notes: userNotes || null,
          user_nuances: userNuances || null,
        }
      );
      setFinalResult(result);
      onComplete?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setFinalizing(false);
    }
  }, [analysis, projectId, displayName, tags, recommendations, userNotes, userNuances, onComplete]);

  // ── Navigation ──────────────────────────────────────────────────────

  const canGoNext = step !== "upload" && step !== "analyzing" && step !== "finalize";
  const canGoBack = stepIdx > 2; // can't go back past summary

  function goNext() {
    const idx = STEP_ORDER.indexOf(step);
    if (idx < STEP_ORDER.length - 1) setStep(STEP_ORDER[idx + 1]);
  }
  function goBack() {
    const idx = STEP_ORDER.indexOf(step);
    if (idx > 0) setStep(STEP_ORDER[idx - 1]);
  }

  // ── Render Steps ────────────────────────────────────────────────────

  return (
    <div className="mx-auto max-w-4xl">
      {/* Progress bar */}
      <div className="mb-6 flex items-center gap-1">
        {STEP_ORDER.filter((s) => s !== "analyzing").map((s, i) => {
          const sIdx = STEP_ORDER.indexOf(s);
          const active = sIdx === stepIdx;
          const done = sIdx < stepIdx;
          return (
            <div key={s} className="flex items-center">
              <div
                className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-medium ${
                  active
                    ? "bg-blue-600 text-white"
                    : done
                    ? "bg-blue-100 text-blue-600"
                    : "bg-slate-100 text-slate-400"
                }`}
              >
                {done ? "\u2713" : i + 1}
              </div>
              <span className={`ml-1 text-xs ${active ? "font-medium text-blue-600" : "text-slate-400"}`}>
                {STEP_LABELS[s]}
              </span>
              {i < STEP_ORDER.filter((s2) => s2 !== "analyzing").length - 1 && (
                <div className="mx-2 h-px w-6 bg-slate-200" />
              )}
            </div>
          );
        })}
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
          <button onClick={() => setError(null)} className="ml-2 font-medium underline">
            Dismiss
          </button>
        </div>
      )}

      {/* STEP: Upload */}
      {step === "upload" && (
        <UploadStep onFileSelect={handleFileSelect} uploading={uploading} />
      )}

      {/* STEP: Analyzing */}
      {step === "analyzing" && <AnalyzingStep />}

      {/* STEP: Summary */}
      {step === "summary" && analysis && (
        <SummaryStep analysis={analysis} displayName={displayName} onDisplayNameChange={setDisplayName} />
      )}

      {/* STEP: Fields */}
      {step === "fields" && (
        <FieldsStep fields={fields} onFieldsChange={setFields} />
      )}

      {/* STEP: Tags */}
      {step === "tags" && (
        <TagsStep tags={tags} onTagsChange={setTags} />
      )}

      {/* STEP: Recommendations */}
      {step === "recommendations" && (
        <RecommendationsStep recommendations={recommendations} onRecommendationsChange={setRecommendations} />
      )}

      {/* STEP: Notes */}
      {step === "notes" && (
        <NotesStep
          userNotes={userNotes}
          userNuances={userNuances}
          onNotesChange={setUserNotes}
          onNuancesChange={setUserNuances}
        />
      )}

      {/* STEP: Finalize */}
      {step === "finalize" && (
        <FinalizeStep
          analysis={analysis}
          tags={tags}
          recommendations={recommendations}
          userNotes={userNotes}
          finalizing={finalizing}
          finalResult={finalResult}
          onFinalize={handleFinalize}
        />
      )}

      {/* Navigation buttons */}
      {step !== "upload" && step !== "analyzing" && !finalResult && (
        <div className="mt-6 flex justify-between">
          <button
            onClick={goBack}
            disabled={!canGoBack}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"
          >
            Back
          </button>
          {step !== "finalize" ? (
            <button
              onClick={goNext}
              disabled={!canGoNext}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
            >
              Next
            </button>
          ) : (
            <button
              onClick={handleFinalize}
              disabled={finalizing}
              className="rounded-md bg-green-600 px-6 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-40"
            >
              {finalizing ? "Saving..." : "Save Data Source"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────

function UploadStep({
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

function AnalyzingStep() {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-slate-200 bg-white p-12">
      <div className="mb-4 h-10 w-10 animate-spin rounded-full border-4 border-blue-200 border-t-blue-600" />
      <p className="text-base font-medium text-slate-700">Analyzing file...</p>
      <div className="mt-4 space-y-2 text-sm text-slate-500">
        <p>Profiling columns and data types...</p>
        <p>Running AI analysis...</p>
        <p>Generating recommendations...</p>
      </div>
    </div>
  );
}

function SummaryStep({
  analysis,
  displayName,
  onDisplayNameChange,
}: {
  analysis: AnalysisResult;
  displayName: string;
  onDisplayNameChange: (name: string) => void;
}) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold text-slate-900">File Summary</h2>

      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h3 className="mb-2 text-xs font-medium uppercase text-slate-400">File Info</h3>
          <div className="space-y-1 text-sm">
            <p><span className="text-slate-500">Name:</span> <input value={displayName} onChange={(e) => onDisplayNameChange(e.target.value)} className="ml-1 rounded border border-slate-200 px-2 py-0.5 text-sm" /></p>
            <p><span className="text-slate-500">Type:</span> {analysis.file.file_type.toUpperCase()}</p>
            <p><span className="text-slate-500">Size:</span> {(analysis.file.file_size_bytes / 1024).toFixed(1)} KB</p>
            <p><span className="text-slate-500">Rows:</span> {analysis.file.row_count.toLocaleString()}</p>
            <p><span className="text-slate-500">Columns:</span> {analysis.file.column_count}</p>
            {analysis.file.sheet_name && <p><span className="text-slate-500">Sheet:</span> {analysis.file.sheet_name}</p>}
          </div>
        </div>

        <div className="space-y-3">
          <div className="rounded-lg border border-blue-100 bg-blue-50 p-4">
            <h3 className="mb-1 text-xs font-medium uppercase text-blue-600">AI Summary</h3>
            <p className="text-sm text-slate-700">{analysis.summary.ai_summary}</p>
          </div>
          <div className="rounded-lg border border-green-100 bg-green-50 p-4">
            <h3 className="mb-1 text-xs font-medium uppercase text-green-600">Likely Use</h3>
            <p className="text-sm text-slate-700">{analysis.summary.ai_usage_summary}</p>
          </div>
          {analysis.summary.ai_quality_summary && (
            <div className="rounded-lg border border-amber-100 bg-amber-50 p-4">
              <h3 className="mb-1 text-xs font-medium uppercase text-amber-600">Quality</h3>
              <p className="text-sm text-slate-700">{analysis.summary.ai_quality_summary}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function FieldsStep({
  fields,
  onFieldsChange,
}: {
  fields: FieldProfile[];
  onFieldsChange: (fields: FieldProfile[]) => void;
}) {
  function toggleInclude(idx: number) {
    const updated = [...fields];
    updated[idx] = { ...updated[idx], include_in_ai: !updated[idx].include_in_ai };
    onFieldsChange(updated);
  }

  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold text-slate-900">Field Profiles</h2>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500">Field</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500">Type</th>
              <th className="px-3 py-2 text-right text-xs font-medium text-slate-500">Nulls</th>
              <th className="px-3 py-2 text-right text-xs font-medium text-slate-500">Distinct</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500">Sample</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500">AI Notes</th>
              <th className="px-3 py-2 text-center text-xs font-medium text-slate-500">Include</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {fields.map((f, i) => (
              <tr key={f.field_name} className="hover:bg-slate-50">
                <td className="px-3 py-2 font-medium text-slate-900">{f.field_name}</td>
                <td className="px-3 py-2">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                    {f.recommended_type || f.detected_type}
                  </span>
                </td>
                <td className="px-3 py-2 text-right text-slate-600">
                  {f.null_percent > 0 ? `${f.null_percent.toFixed(1)}%` : "\u2014"}
                </td>
                <td className="px-3 py-2 text-right text-slate-600">{f.distinct_count}</td>
                <td className="px-3 py-2 text-slate-500 truncate max-w-[200px]">
                  {f.sample_values?.slice(0, 3).join(", ")}
                </td>
                <td className="px-3 py-2 text-xs text-slate-500 max-w-[200px]">
                  {f.ai_description || f.ai_quality_notes || "\u2014"}
                </td>
                <td className="px-3 py-2 text-center">
                  <input
                    type="checkbox"
                    checked={f.include_in_ai !== false}
                    onChange={() => toggleInclude(i)}
                    className="h-4 w-4 rounded border-slate-300 text-blue-600"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TagsStep({
  tags,
  onTagsChange,
}: {
  tags: TagChip[];
  onTagsChange: (tags: TagChip[]) => void;
}) {
  const [newTag, setNewTag] = useState("");

  function addTag() {
    const trimmed = newTag.trim();
    if (!trimmed || tags.some((t) => t.tag === trimmed)) return;
    onTagsChange([...tags, { tag: trimmed, tag_type: "user", source: "user", accepted: true }]);
    setNewTag("");
  }

  function removeTag(idx: number) {
    onTagsChange(tags.filter((_, i) => i !== idx));
  }

  function toggleTag(idx: number) {
    const updated = [...tags];
    updated[idx] = { ...updated[idx], accepted: !updated[idx].accepted };
    onTagsChange(updated);
  }

  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold text-slate-900">Tags</h2>
      <p className="mb-4 text-sm text-slate-500">
        AI-generated tags help categorize this data source. You can add, remove, or toggle tags.
      </p>

      <div className="flex flex-wrap gap-2 mb-4">
        {tags.map((t, i) => (
          <span
            key={i}
            className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-sm ${
              t.accepted !== false
                ? t.source === "ai"
                  ? "bg-blue-100 text-blue-700"
                  : "bg-green-100 text-green-700"
                : "bg-slate-100 text-slate-400 line-through"
            }`}
          >
            <button onClick={() => toggleTag(i)} className="hover:opacity-70" title={t.accepted !== false ? "Reject" : "Accept"}>
              {t.tag}
            </button>
            {t.source === "ai" && t.confidence != null && (
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
          placeholder="Add a tag..."
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
        />
        <button
          onClick={addTag}
          disabled={!newTag.trim()}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
        >
          + Add Tag
        </button>
      </div>
    </div>
  );
}

function RecommendationsStep({
  recommendations,
  onRecommendationsChange,
}: {
  recommendations: Recommendation[];
  onRecommendationsChange: (recs: Recommendation[]) => void;
}) {
  function setStatus(idx: number, status: string) {
    const updated = [...recommendations];
    updated[idx] = { ...updated[idx], status };
    onRecommendationsChange(updated);
  }

  const severityColor: Record<string, string> = {
    critical: "border-red-200 bg-red-50",
    warning: "border-amber-200 bg-amber-50",
    info: "border-blue-200 bg-blue-50",
  };

  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold text-slate-900">AI Recommendations</h2>
      <p className="mb-4 text-sm text-slate-500">
        Review AI suggestions. Accept or reject each recommendation.
      </p>

      {recommendations.length === 0 ? (
        <p className="text-sm text-slate-400">No recommendations generated.</p>
      ) : (
        <div className="space-y-3">
          {recommendations.map((r, i) => (
            <div key={i} className={`rounded-lg border p-4 ${severityColor[r.severity] || severityColor.info}`}>
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                      r.severity === "critical" ? "bg-red-200 text-red-700" :
                      r.severity === "warning" ? "bg-amber-200 text-amber-700" :
                      "bg-blue-200 text-blue-700"
                    }`}>
                      {r.severity}
                    </span>
                    <span className="text-xs text-slate-400">{r.recommendation_type}</span>
                  </div>
                  <h3 className="mt-1 font-medium text-slate-900">{r.title}</h3>
                  <p className="mt-1 text-sm text-slate-600">{r.description}</p>
                </div>
                <div className="ml-4 flex gap-2">
                  <button
                    onClick={() => setStatus(i, "accepted")}
                    className={`rounded-md px-3 py-1 text-xs font-medium ${
                      r.status === "accepted"
                        ? "bg-green-600 text-white"
                        : "border border-green-300 text-green-600 hover:bg-green-50"
                    }`}
                  >
                    Accept
                  </button>
                  <button
                    onClick={() => setStatus(i, "rejected")}
                    className={`rounded-md px-3 py-1 text-xs font-medium ${
                      r.status === "rejected"
                        ? "bg-red-600 text-white"
                        : "border border-red-300 text-red-600 hover:bg-red-50"
                    }`}
                  >
                    Reject
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function NotesStep({
  userNotes,
  userNuances,
  onNotesChange,
  onNuancesChange,
}: {
  userNotes: string;
  userNuances: string;
  onNotesChange: (v: string) => void;
  onNuancesChange: (v: string) => void;
}) {
  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold text-slate-900">Documentation & Notes</h2>
      <p className="mb-4 text-sm text-slate-500">
        Add any context that will help AI understand this data source better in the future.
      </p>

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">General Notes</label>
          <textarea
            value={userNotes}
            onChange={(e) => onNotesChange(e.target.value)}
            placeholder="Business context, data source origin, refresh schedule, etc."
            rows={3}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Data Nuances / Caveats</label>
          <textarea
            value={userNuances}
            onChange={(e) => onNuancesChange(e.target.value)}
            placeholder="Known issues, join rules, field caveats, how data should or should not be used..."
            rows={3}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
      </div>
    </div>
  );
}

function FinalizeStep({
  analysis,
  tags,
  recommendations,
  userNotes,
  finalizing,
  finalResult,
  onFinalize,
}: {
  analysis: AnalysisResult | null;
  tags: TagChip[];
  recommendations: Recommendation[];
  userNotes: string;
  finalizing: boolean;
  finalResult: Record<string, unknown> | null;
  onFinalize: () => void;
}) {
  if (finalResult) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-green-200 bg-green-50 p-12">
        <svg className="h-12 w-12 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <h3 className="mt-3 text-lg font-semibold text-green-800">Data Source Created</h3>
        <p className="mt-1 text-sm text-green-600">
          {String(finalResult.message || "Data source saved with AI metadata.")}
        </p>
      </div>
    );
  }

  const acceptedTags = tags.filter((t) => t.accepted !== false);
  const acceptedRecs = recommendations.filter((r) => r.status === "accepted").length;
  const rejectedRecs = recommendations.filter((r) => r.status === "rejected").length;

  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold text-slate-900">Review & Save</h2>

      <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex justify-between text-sm">
          <span className="text-slate-500">File</span>
          <span className="font-medium">{analysis?.file.file_name}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-slate-500">Rows × Columns</span>
          <span>{analysis?.file.row_count.toLocaleString()} × {analysis?.file.column_count}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-slate-500">Tags</span>
          <span>{acceptedTags.length} accepted</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-slate-500">Recommendations</span>
          <span>{acceptedRecs} accepted, {rejectedRecs} rejected</span>
        </div>
        {userNotes && (
          <div className="flex justify-between text-sm">
            <span className="text-slate-500">Notes</span>
            <span className="max-w-xs truncate">{userNotes}</span>
          </div>
        )}
      </div>

      <div className="mt-6 text-center">
        <button
          onClick={onFinalize}
          disabled={finalizing}
          className="rounded-md bg-green-600 px-8 py-3 text-base font-medium text-white shadow-sm hover:bg-green-700 disabled:opacity-50"
        >
          {finalizing ? "Creating Data Source..." : "Save Data Source"}
        </button>
      </div>
    </div>
  );
}
