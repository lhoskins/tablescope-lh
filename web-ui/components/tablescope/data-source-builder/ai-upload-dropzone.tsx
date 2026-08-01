"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { IconCloudUpload, IconLoader2 } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { apiClient } from "@/lib/api-client";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { analyzeFile } from "@/lib/api/data-source-builder";
import { sessionSourceFromPreview } from "./import-source";
import {
  FALLBACK_CAPABILITIES,
  acceptAttribute,
  classifyFile,
  destinationLabel,
  familyLabel,
  fetchCapabilities,
  type Classification,
  type UploadCapabilities,
  type UploadDestination,
} from "@/lib/uploads/intake";

type ItemStatus =
  | "classifying"
  | "awaiting_choice"
  | "processing"
  | "done"
  | "error";

interface IntakeItem {
  id: string;
  fileName: string;
  sizeBytes: number;
  status: ItemStatus;
  family?: string;
  destination?: UploadDestination;
  reason?: string;
  message?: string;
}

interface AiUploadDropzoneProps {
  /**
   * Project the intake assigns ingested files to. Documents can only be
   * ingested when a project is known; structured files may also be staged in
   * the builder without one.
   */
  projectId?: number;
  /** Hint used for copy only — the server still classifies by content. */
  preferredAssetFamily?: "structured_tabular" | "unstructured_document";
  /** Called after all selected files have been processed and at least one was ingested without error. */
  onUploadsDone?: () => void;
}

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * The single governed file-intake surface. Every supported upload — structured
 * spreadsheets and business documents alike — is classified here and then
 * routed to the structured pipeline (Data Source) or the document pipeline
 * (Document); nothing is ingested before its family is known.
 */
export function AiUploadDropzone({
  projectId,
  preferredAssetFamily,
  onUploadsDone,
}: AiUploadDropzoneProps = {}) {
  const addSource = useBuilderStore((s) => s.addSource);
  const hasSource = useBuilderStore((s) => s.hasSource);
  const markCreated = useBuilderStore((s) => s.markCreated);
  const inputRef = useRef<HTMLInputElement>(null);

  const [dragActive, setDragActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<IntakeItem[]>([]);
  const [capabilities, setCapabilities] =
    useState<UploadCapabilities>(FALLBACK_CAPABILITIES);
  const pendingChoices = useRef(new Map<string, File>());

  useEffect(() => {
    let cancelled = false;
    void fetchCapabilities().then((caps) => {
      if (!cancelled) setCapabilities(caps);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const patch = useCallback((id: string, next: Partial<IntakeItem>) => {
    setItems((prev) =>
      prev.map((item) => (item.id === id ? { ...item, ...next } : item)),
    );
  }, []);

  const ingestStructured = useCallback(
    async (file: File) => {
      if (hasSource((s) => s.isFileUpload && s.displayName === file.name)) {
        throw new Error(`${file.name} is already in this session.`);
      }
      const preview = await analyzeFile(file, projectId);
      const source = sessionSourceFromPreview(preview);
      addSource(source);
      markCreated([source.id]);
      return `Staged as data source ${source.viewName}.`;
    },
    [addSource, hasSource, markCreated, projectId],
  );

  const ingestDocument = useCallback(
    async (file: File) => {
      if (!projectId) {
        throw new Error(
          `${file.name} is a document — open this upload from a project to add it.`,
        );
      }
      await apiClient.upload(`/api/projects/${projectId}/assets/upload`, file, {
        asset_type: "document",
        visibility: "shared_project",
      });
      return "Added to Documents — extraction and indexing continue in the background.";
    },
    [projectId],
  );

  const route = useCallback(
    async (id: string, file: File, destination: UploadDestination) => {
      patch(id, { status: "processing", destination });
      try {
        const message =
          destination === "data_source"
            ? await ingestStructured(file)
            : await ingestDocument(file);
        patch(id, { status: "done", message });
        return true;
      } catch (err) {
        patch(id, {
          status: "error",
          message:
            err instanceof Error
              ? err.message
              : `Could not process ${file.name}.`,
        });
        return false;
      }
    },
    [ingestDocument, ingestStructured, patch],
  );

  const handleFiles = useCallback(
    async (files: FileList | null) => {
      if (!files || files.length === 0) return;
      setError(null);
      setBusy(true);
      let added = false;
      let hadError = false;
      try {
        for (const file of Array.from(files)) {
          const id = crypto.randomUUID();
          setItems((prev) => [
            ...prev,
            {
              id,
              fileName: file.name,
              sizeBytes: file.size,
              status: "classifying",
            },
          ]);
          let classification: Classification;
          try {
            classification = await classifyFile(file, capabilities);
          } catch (err) {
            hadError = true;
            patch(id, {
              status: "error",
              message:
                err instanceof Error
                  ? err.message
                  : `${file.name} could not be classified.`,
            });
            continue;
          }
          patch(id, {
            family: classification.family,
            destination: classification.destination,
            reason: classification.reason,
          });
          if (classification.ambiguous) {
            // TXT/JSON/XML the classifier is unsure about: the user decides,
            // and the choice is recorded with the resulting asset.
            pendingChoices.current.set(id, file);
            patch(id, { status: "awaiting_choice" });
            continue;
          }
          const ok = await route(id, file, classification.destination);
          added = added || ok;
          hadError = hadError || !ok;
        }
      } finally {
        setBusy(false);
        if (inputRef.current) inputRef.current.value = "";
      }
      if (added && !hadError) onUploadsDone?.();
    },
    [capabilities, onUploadsDone, patch, route],
  );

  const resolveChoice = useCallback(
    async (id: string, destination: UploadDestination) => {
      const file = pendingChoices.current.get(id);
      if (!file) return;
      pendingChoices.current.delete(id);
      const ok = await route(id, file, destination);
      if (ok) onUploadsDone?.();
    },
    [onUploadsDone, route],
  );

  const accepted = acceptAttribute(capabilities);
  const documentsHint =
    preferredAssetFamily === "unstructured_document"
      ? "Upload a business document — or a spreadsheet, which will be set up as a data source instead."
      : "Upload structured data or business documents. TableScope will detect the file type and guide the appropriate setup.";

  return (
    <div>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragActive(false);
          void handleFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
          dragActive
            ? "border-brand-500 bg-brand-50/50"
            : "border-brand-300 bg-brand-50/30 hover:border-brand-500 hover:bg-brand-50/50",
        )}
      >
        <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-brand-100 text-brand-600">
          {busy ? (
            <IconLoader2 size={24} className="animate-spin" />
          ) : (
            <IconCloudUpload size={24} />
          )}
        </span>
        <span className="flex items-center gap-2 text-[15px] font-semibold text-ink-primary">
          AI-Assisted File Upload
          <span className="rounded bg-brand-100 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-brand-700">
            AI
          </span>
        </span>
        <span className="max-w-md text-small text-ink-secondary">
          {busy ? "Detecting file type and preparing ingestion…" : documentsHint}
        </span>
        <span className="max-w-md text-caption text-ink-tertiary">
          Accepted: {accepted.replace(/,/g, " ")} · up to{" "}
          {Math.round(capabilities.maxFileSizeBytes / (1024 * 1024))}MB
        </span>
        <input
          ref={inputRef}
          type="file"
          accept={accepted}
          multiple
          className="hidden"
          onChange={(e) => void handleFiles(e.target.files)}
        />
      </button>

      {items.length > 0 && (
        <ul className="mt-3 space-y-2">
          {items.map((item) => (
            <li
              key={item.id}
              className="rounded-lg border border-line-tertiary px-3 py-2 text-[13px]"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="truncate font-medium text-ink-primary">
                  {item.fileName}
                </span>
                <span className="shrink-0 text-caption text-ink-tertiary">
                  {humanSize(item.sizeBytes)}
                </span>
              </div>
              <div className="mt-0.5 text-caption text-ink-secondary">
                {item.status === "classifying" && "Detecting file type…"}
                {item.status !== "classifying" && item.family && (
                  <>
                    {familyLabel(item.family)}
                    {item.destination
                      ? ` → ${destinationLabel(item.destination)}`
                      : ""}
                    {item.reason ? ` · ${item.reason}` : ""}
                  </>
                )}
              </div>
              {item.status === "awaiting_choice" && (
                <div className="mt-2 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void resolveChoice(item.id, "data_source")}
                    className="rounded-md border border-line-primary px-2 py-1 text-caption font-medium text-ink-primary hover:bg-bg-secondary"
                  >
                    Use as data
                  </button>
                  <button
                    type="button"
                    onClick={() => void resolveChoice(item.id, "document")}
                    className="rounded-md border border-line-primary px-2 py-1 text-caption font-medium text-ink-primary hover:bg-bg-secondary"
                  >
                    Use as document
                  </button>
                </div>
              )}
              {item.status === "processing" && (
                <p className="mt-1 text-caption text-ink-tertiary">Processing…</p>
              )}
              {item.status === "done" && item.message && (
                <p className="mt-1 text-caption text-ink-secondary">
                  {item.message}
                </p>
              )}
              {item.status === "error" && (
                <p className="mt-1 text-caption text-danger">{item.message}</p>
              )}
            </li>
          ))}
        </ul>
      )}

      {error && <p className="mt-2 text-caption text-danger">{error}</p>}
    </div>
  );
}
