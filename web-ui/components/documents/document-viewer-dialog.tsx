"use client";

import { useEffect } from "react";
import type { ProjectDocument } from "./DocumentsTab/project-document";
import { formatBytes } from "./DocumentsTab/format-bytes";
import { DocumentPreview, useAssetDownload } from "./document-preview";

/**
 * One responsive, keyboard-dismissible in-app viewer for a project document.
 *
 * The rendering itself lives in `DocumentPreview`, which the Workspace's
 * Preview pane also uses; this component is the modal around it -- title,
 * download, close, backdrop.
 */
export function DocumentViewerDialog({
  projectId,
  document: doc,
  onClose,
}: {
  projectId: number;
  document: ProjectDocument;
  onClose: () => void;
}) {
  const { download, downloading } = useAssetDownload(projectId, doc);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="flex h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg bg-white shadow-xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={doc.original_filename || doc.filename}
      >
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-slate-900">
              {doc.original_filename || doc.filename}
            </div>
            <div className="text-xs text-slate-500">
              {(doc.file_extension || "").replace(".", "").toUpperCase() || "File"} ·{" "}
              {formatBytes(doc.file_size_bytes)}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => void download()}
              disabled={downloading}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              {downloading ? "Downloading…" : "Download"}
            </button>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          </div>
        </div>

        <DocumentPreview projectId={projectId} document={doc} />
      </div>
    </div>
  );
}
