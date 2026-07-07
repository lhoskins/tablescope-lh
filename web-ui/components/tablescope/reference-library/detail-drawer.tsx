"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { getUserMeta } from "@/lib/auth";
import {
  referenceLibraryApi,
  type ReferenceDocumentDetail,
} from "@/lib/api/reference-library";

function formatBytes(n: number | null): string | null {
  if (!n) return null;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  if (value == null || value === "") return null;
  return (
    <div>
      <span className="text-[10px] font-semibold uppercase text-ink-tertiary">
        {label}
      </span>
      <p className="text-[13px] text-ink-secondary">{value}</p>
    </div>
  );
}

export function ReferenceDetailDrawer({
  documentId,
  onClose,
  onChanged,
}: {
  documentId: number;
  onClose: () => void;
  onChanged?: () => void;
}) {
  const [detail, setDetail] = useState<ReferenceDocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canWrite = (getUserMeta()?.role ?? "viewer") !== "viewer";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setDetail(await referenceLibraryApi.getDocumentDetail(documentId));
    } catch {
      setError("Could not load document details.");
    } finally {
      setLoading(false);
    }
  }, [documentId]);

  useEffect(() => {
    void load();
  }, [load]);

  const doc = detail?.document;

  async function download() {
    if (!doc) return;
    try {
      await referenceLibraryApi.downloadDocument(
        doc.id,
        doc.originalFilename || `${doc.title}.${doc.fileType || "bin"}`,
      );
    } catch {
      setError("Download failed.");
    }
  }

  async function reprocess() {
    if (!doc) return;
    setBusy(true);
    setError(null);
    try {
      await referenceLibraryApi.reprocess(doc.id);
      await load();
      onChanged?.();
    } catch {
      setError("Could not reprocess document.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative h-full w-full max-w-lg overflow-y-auto bg-bg-primary shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 flex items-start justify-between border-b border-line-tertiary bg-bg-primary px-5 py-4">
          <div className="pr-4">
            <p className="text-[10px] font-semibold uppercase text-ink-tertiary">
              Reference Document
            </p>
            <h2 className="text-h3 text-ink-primary">
              {doc?.title ?? "Loading…"}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-2 py-1 text-[13px] text-ink-tertiary hover:bg-bg-tertiary"
          >
            Close
          </button>
        </div>

        {loading || !doc ? (
          <div className="p-5 text-[13px] text-ink-tertiary">
            {error ?? "Loading…"}
          </div>
        ) : (
          <div className="space-y-5 p-5">
            <div className="grid grid-cols-2 gap-4">
              <Field label="Issuing body" value={doc.issuingBody} />
              <Field label="Domain" value={doc.domainTag} />
              <Field label="Applicability" value={doc.applicabilityTag} />
              <Field label="Version" value={doc.versionLabel} />
              <Field label="Effective date" value={doc.effectiveDate} />
              <Field
                label="Status"
                value={<Badge tone="neutral">{doc.status}</Badge>}
              />
              <Field
                label="File"
                value={
                  doc.hasFile
                    ? [doc.fileType?.toUpperCase(), formatBytes(doc.fileSizeBytes)]
                        .filter(Boolean)
                        .join(" · ")
                    : "No file"
                }
              />
              <Field
                label="Source"
                value={
                  doc.sourceUrl ? (
                    <a
                      href={doc.sourceUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-brand-600 underline"
                    >
                      Link
                    </a>
                  ) : null
                }
              />
            </div>

            <div>
              <h4 className="mb-1 text-[11px] font-semibold uppercase text-ink-tertiary">
                AI summary
              </h4>
              {doc.aiSummary ? (
                <p className="whitespace-pre-wrap text-[13px] text-ink-secondary">
                  {doc.aiSummary}
                </p>
              ) : doc.aiErrorMessage ? (
                <p className="text-[13px] text-danger">{doc.aiErrorMessage}</p>
              ) : doc.status === "processing" ? (
                <p className="text-[13px] text-ai">Processing…</p>
              ) : (
                <p className="text-[13px] text-ink-tertiary">
                  No AI summary yet.
                </p>
              )}
            </div>

            {detail.versionFamily.length > 1 && (
              <div>
                <h4 className="mb-1 text-[11px] font-semibold uppercase text-ink-tertiary">
                  Version family
                </h4>
                <div className="space-y-1">
                  {detail.versionFamily.map((v) => (
                    <div
                      key={v.id}
                      className="flex items-center justify-between rounded-md border border-line-tertiary px-2.5 py-1.5 text-[12px]"
                    >
                      <span className="text-ink-secondary">
                        {v.title}
                        {v.versionLabel ? ` · ${v.versionLabel}` : ""}
                        {v.effectiveDate ? ` · ${v.effectiveDate}` : ""}
                      </span>
                      <span className="flex items-center gap-1">
                        {v.isCurrent && <Badge tone="brand">This document</Badge>}
                        <Badge
                          tone={v.status === "superseded" ? "warning" : "neutral"}
                        >
                          {v.status}
                        </Badge>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {detail.usage.length > 0 && (
              <div>
                <h4 className="mb-1 text-[11px] font-semibold uppercase text-ink-tertiary">
                  Used in projects
                </h4>
                <div className="flex flex-wrap gap-1.5">
                  {detail.usage.map((u) => (
                    <span
                      key={`${u.projectId}-${u.assignmentType}`}
                      className="inline-flex items-center gap-1 rounded-full bg-bg-secondary px-2 py-0.5 text-[12px] text-ink-secondary"
                      title={u.assignmentType.replace(/_/g, " ")}
                    >
                      {u.projectName}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {doc.inheritDefault && (
              <p className="text-[12px] text-ink-tertiary">
                Inherited by default into every project&apos;s library.
              </p>
            )}

            <div className="flex flex-wrap gap-2 border-t border-line-tertiary pt-4">
              {doc.hasFile && (
                <button
                  type="button"
                  onClick={() => void download()}
                  className="rounded-md bg-bg-secondary px-3 py-1.5 text-[12px] font-medium text-ink-secondary hover:bg-bg-tertiary"
                >
                  Download
                </button>
              )}
              {canWrite && doc.hasFile && (
                <button
                  type="button"
                  onClick={() => void reprocess()}
                  disabled={busy || doc.status === "processing"}
                  className="rounded-md bg-bg-secondary px-3 py-1.5 text-[12px] font-medium text-ink-secondary hover:bg-bg-tertiary disabled:opacity-50"
                >
                  {busy || doc.status === "processing"
                    ? "Reprocessing…"
                    : "Reprocess AI summary"}
                </button>
              )}
            </div>
            {error && <p className="text-[12px] text-danger">{error}</p>}
          </div>
        )}
      </div>
    </div>
  );
}
