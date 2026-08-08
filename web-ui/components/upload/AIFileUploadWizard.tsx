"use client";


import { useState, useCallback } from "react";
import { apiClient } from "@/lib/api-client";import { AnalysisResult } from "./AIFileUploadWizard/analysis-result";
import { FileEntry } from "./AIFileUploadWizard/file-entry";
import { Phase } from "./AIFileUploadWizard/phase";
import { FileReviewCard } from "./AIFileUploadWizard/file-review-card";
import { UploadDropzone } from "./AIFileUploadWizard/upload-dropzone";



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
