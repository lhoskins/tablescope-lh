"use client";

import { useState, useCallback, useRef, lazy, Suspense } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

const KnowledgeGraph = lazy(() =>
  import("./KnowledgeGraph").then((m) => ({ default: m.KnowledgeGraph }))
);

// ── Types ──────────────────────────────────────────────────────────

type ProjectDocument = {
  id: number;
  title: string | null;
  filename: string;
  original_filename: string;
  asset_type: string;
  content_type: string | null;
  file_extension: string | null;
  file_size_bytes: number | null;
  status: string;
  ai_status: string | null;
  ai_summary: string | null;
  ai_metadata: Record<string, unknown> | null;
  visibility: string;
  created_at: string;
};

type AITag = {
  tag_key: string;
  display_name: string;
  confidence: number;
  source: string;
};

type AIEntity = {
  entity_type: string;
  name: string;
  confidence: number;
  evidence: string;
};

type AIKPI = {
  kpi_key: string;
  display_name: string;
  confidence: number;
  reason: string;
};

// ── Helpers ────────────────────────────────────────────────────────

function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function statusBadge(status: string | null | undefined) {
  const s = (status ?? "pending").toLowerCase();
  const colors: Record<string, string> = {
    uploaded: "bg-blue-100 text-blue-700",
    extracting: "bg-yellow-100 text-yellow-700",
    chunking: "bg-yellow-100 text-yellow-700",
    profiling: "bg-purple-100 text-purple-700",
    profiled: "bg-green-100 text-green-700",
    failed: "bg-red-100 text-red-700",
    pending: "bg-slate-100 text-slate-500",
  };
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${colors[s] ?? colors.pending}`}>
      {s}
    </span>
  );
}

function fileIcon(ext: string | null | undefined) {
  const e = (ext ?? "").toLowerCase().replace(".", "");
  if (e === "pdf") return "📄";
  if (e === "docx" || e === "doc") return "📝";
  if (e === "pptx" || e === "ppt") return "📊";
  if (e === "md") return "📋";
  return "📃";
}

// ── Component ──────────────────────────────────────────────────────

export function DocumentsTab({ projectId, canEdit }: { projectId: number; canEdit: boolean }) {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);

  const [subTab, setSubTab] = useState<"documents" | "graph">("documents");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // ── Fetch documents ────────────────────────────────────────────
  const docsQuery = useQuery<ProjectDocument[]>({
    queryKey: ["project-documents", projectId],
    queryFn: () => apiClient.get(`/api/projects/${projectId}/assets`),
    refetchInterval: 10000,
  });

  const docs = docsQuery.data ?? [];

  // ── Upload ─────────────────────────────────────────────────────
  const handleUpload = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    setUploadError(null);

    const errors: string[] = [];
    for (const file of Array.from(files)) {
      try {
        await apiClient.upload(`/api/projects/${projectId}/assets/upload`, file, {
          asset_type: "document",
          visibility: "shared_project",
        });
      } catch (err) {
        errors.push(`${file.name}: ${err instanceof Error ? err.message : "upload failed"}`);
      }
    }

    if (errors.length) setUploadError(errors.join("; "));
    setUploading(false);
    queryClient.invalidateQueries({ queryKey: ["project-documents", projectId] });
  }, [projectId, queryClient]);

  // ── Delete ─────────────────────────────────────────────────────
  const deleteMutation = useMutation({
    mutationFn: (assetId: number) =>
      apiClient.delete(`/api/projects/${projectId}/assets/${assetId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-documents", projectId] });
    },
  });

  // ── Trigger AI processing ──────────────────────────────────────
  const processMutation = useMutation({
    mutationFn: (assetId: number) =>
      apiClient.post(`/api/projects/${projectId}/assets/${assetId}/ai/process`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-documents", projectId] });
    },
  });

  // ── Render ─────────────────────────────────────────────────────
  return (
    <div>
      {/* Sub-tabs: Documents | Knowledge Graph */}
      <div className="mb-4 flex gap-1 rounded-lg bg-slate-100 p-1 w-fit">
        <button
          type="button"
          onClick={() => setSubTab("documents")}
          className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
            subTab === "documents"
              ? "bg-white text-slate-900 shadow-sm"
              : "text-slate-500 hover:text-slate-700"
          }`}
        >
          Documents
        </button>
        <button
          type="button"
          onClick={() => setSubTab("graph")}
          className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
            subTab === "graph"
              ? "bg-white text-slate-900 shadow-sm"
              : "text-slate-500 hover:text-slate-700"
          }`}
        >
          Knowledge Graph
        </button>
      </div>

      {/* Knowledge Graph view */}
      {subTab === "graph" && (
        <Suspense fallback={<div className="text-sm text-slate-400 py-4">Loading graph...</div>}>
          <KnowledgeGraph projectId={projectId} />
        </Suspense>
      )}

      {/* Documents list view */}
      {subTab === "documents" && (
      <div>
      {/* Upload button */}
      {canEdit && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
          >
            {uploading ? "Uploading..." : "+ Upload Documents"}
          </button>
          <input
            ref={fileRef}
            type="file"
            multiple
            accept=".pdf,.docx,.pptx,.txt,.md"
            className="hidden"
            onChange={(e) => handleUpload(e.target.files)}
          />
          <span className="text-xs text-slate-400">
            PDF, DOCX, PPTX, TXT, MD
          </span>
        </div>
      )}
      {uploadError && (
        <div className="mb-3 rounded-md bg-red-50 p-3 text-sm text-red-700">{uploadError}</div>
      )}

      {/* Documents list */}
      {docsQuery.isLoading ? (
        <div className="text-sm text-slate-400">Loading documents...</div>
      ) : docs.length === 0 ? (
        <div className="py-12 text-center text-slate-400">
          <p className="text-4xl mb-3">📁</p>
          <p className="text-sm">No documents uploaded yet</p>
          <p className="text-xs mt-1">Upload PDFs, DOCX, PPTX, TXT, or Markdown files to get AI-powered analysis</p>
        </div>
      ) : (
        <div className="space-y-3">
          {docs.map((doc) => {
            const isExpanded = expandedId === doc.id;
            const meta = doc.ai_metadata as Record<string, unknown> | null;
            const tags = (meta?.tags ?? []) as AITag[];
            const entities = (meta?.entities ?? []) as AIEntity[];
            const kpis = (meta?.recommended_kpis ?? []) as AIKPI[];
            const domain = meta?.business_domain as string | undefined;
            const docType = meta?.document_type as string | undefined;
            const questions = (meta?.suggested_questions ?? []) as string[];

            return (
              <div
                key={doc.id}
                className="rounded-lg border border-slate-200 bg-white overflow-hidden"
              >
                {/* Row header */}
                <div
                  className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-slate-50"
                  onClick={() => setExpandedId(isExpanded ? null : doc.id)}
                >
                  <span className="text-xl">{fileIcon(doc.file_extension)}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-slate-900 truncate">
                        {doc.title || doc.original_filename || doc.filename}
                      </span>
                      {statusBadge(doc.ai_status)}
                      <span className="text-[10px] text-slate-400 uppercase">
                        {doc.file_extension?.replace(".", "") ?? doc.asset_type}
                      </span>
                    </div>
                    {doc.ai_summary && (
                      <p className="text-xs text-slate-500 mt-0.5 line-clamp-1">
                        {doc.ai_summary}
                      </p>
                    )}
                  </div>
                  <span className="text-xs text-slate-400">{formatBytes(doc.file_size_bytes)}</span>
                  <span className="text-xs text-slate-400">
                    {new Date(doc.created_at).toLocaleDateString()}
                  </span>
                  <svg
                    className={`h-4 w-4 text-slate-400 transition-transform ${isExpanded ? "rotate-180" : ""}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </div>

                {/* Expanded detail */}
                {isExpanded && (
                  <div className="border-t border-slate-100 px-4 py-4 space-y-4">
                    {/* AI Summary */}
                    {doc.ai_summary && (
                      <div>
                        <h4 className="text-xs font-semibold text-slate-500 uppercase mb-1">AI Summary</h4>
                        <p className="text-sm text-slate-700">{doc.ai_summary}</p>
                      </div>
                    )}

                    {/* Document type + domain */}
                    {(docType || domain) && (
                      <div className="flex gap-4">
                        {docType && (
                          <div>
                            <span className="text-[10px] text-slate-400 uppercase">Type</span>
                            <p className="text-sm text-slate-700">{docType.replace(/_/g, " ")}</p>
                          </div>
                        )}
                        {domain && (
                          <div>
                            <span className="text-[10px] text-slate-400 uppercase">Domain</span>
                            <p className="text-sm text-slate-700">{domain.replace(/_/g, " ")}</p>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Tags */}
                    {tags.length > 0 && (
                      <div>
                        <h4 className="text-xs font-semibold text-slate-500 uppercase mb-1">Tags</h4>
                        <div className="flex flex-wrap gap-1.5">
                          {tags.map((t, i) => (
                            <span
                              key={i}
                              className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700"
                            >
                              {t.display_name || t.tag_key}
                              {t.confidence && (
                                <span className="text-[10px] text-blue-400">
                                  {Math.round(t.confidence * 100)}%
                                </span>
                              )}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* KPIs */}
                    {kpis.length > 0 && (
                      <div>
                        <h4 className="text-xs font-semibold text-slate-500 uppercase mb-1">KPIs</h4>
                        <div className="flex flex-wrap gap-1.5">
                          {kpis.map((k, i) => (
                            <span
                              key={i}
                              className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700"
                              title={k.reason}
                            >
                              {k.display_name || k.kpi_key}
                              {k.confidence && (
                                <span className="text-[10px] text-amber-400">
                                  {Math.round(k.confidence * 100)}%
                                </span>
                              )}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Entities */}
                    {entities.length > 0 && (
                      <div>
                        <h4 className="text-xs font-semibold text-slate-500 uppercase mb-1">Entities</h4>
                        <div className="space-y-1">
                          {entities.map((e, i) => (
                            <div key={i} className="flex items-center gap-2 text-xs">
                              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600 font-medium">
                                {e.entity_type}
                              </span>
                              <span className="text-slate-700">{e.name}</span>
                              {e.evidence && (
                                <span className="text-slate-400 italic truncate max-w-xs">
                                  &ldquo;{e.evidence}&rdquo;
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Suggested Questions */}
                    {questions.length > 0 && (
                      <div>
                        <h4 className="text-xs font-semibold text-slate-500 uppercase mb-1">Suggested Questions</h4>
                        <ul className="space-y-1">
                          {questions.map((q, i) => (
                            <li key={i} className="text-xs text-slate-600 flex items-start gap-1">
                              <span className="text-slate-400">•</span>
                              {q}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Actions */}
                    <div className="flex gap-2 pt-2 border-t border-slate-100">
                      {doc.ai_status !== "profiled" && doc.ai_status !== "profiling" && canEdit && (
                        <button
                          type="button"
                          onClick={() => processMutation.mutate(doc.id)}
                          disabled={processMutation.isPending}
                          className="rounded-md bg-purple-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                        >
                          {processMutation.isPending ? "Processing..." : "Process with AI"}
                        </button>
                      )}
                      {doc.ai_status === "profiled" && canEdit && (
                        <button
                          type="button"
                          onClick={() => processMutation.mutate(doc.id)}
                          disabled={processMutation.isPending}
                          className="rounded-md bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200 disabled:opacity-50"
                        >
                          Reprocess
                        </button>
                      )}
                      {canEdit && (
                        <button
                          type="button"
                          onClick={() => {
                            if (confirm(`Delete "${doc.original_filename || doc.filename}"?`)) {
                              deleteMutation.mutate(doc.id);
                            }
                          }}
                          disabled={deleteMutation.isPending}
                          className="rounded-md bg-red-50 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-100 disabled:opacity-50"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      </div>
      )}
    </div>
  );
}
