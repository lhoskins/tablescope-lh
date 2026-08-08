"use client";

import { useEffect } from "react";
import { IconX } from "@tabler/icons-react";
import { AiUploadDropzone } from "@/components/tablescope/data-source-builder/ai-upload-dropzone";

/**
 * Modal wrapper around the single AI-Assisted Upload intake. Every upload entry
 * point (Project Overview quick action, Documents page, Data Sources page)
 * opens this dialog instead of implementing its own uploader.
 */
export function UnifiedUploadDialog({
  open,
  projectId,
  preferredAssetFamily,
  onClose,
  onUploadsDone,
}: {
  open: boolean;
  projectId: number;
  preferredAssetFamily?: "structured_tabular" | "unstructured_document";
  onClose: () => void;
  onUploadsDone?: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-16"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="AI-Assisted Upload"
        className="w-full max-w-xl rounded-xl bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-4">
          <div>
            <h3 className="text-base font-semibold text-ink-primary">
              AI-Assisted Upload
            </h3>
            <p className="mt-0.5 text-small text-ink-secondary">
              Files are classified before ingestion and routed to a Data Source
              or to Documents automatically.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="rounded-md p-1 text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
          >
            <IconX size={16} />
          </button>
        </div>
        <AiUploadDropzone
          projectId={projectId}
          preferredAssetFamily={preferredAssetFamily}
          onUploadsDone={onUploadsDone}
        />
      </div>
    </div>
  );
}
