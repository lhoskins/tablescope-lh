"use client";

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";

/**
 * A project document's actual content, rendered inline.
 *
 * Extracted from `DocumentViewerDialog` so the Workspace's Preview pane can
 * show a document without a modal wrapped around it. The dialog now renders
 * this too -- the format handling below is fiddly enough (six kinds, three of
 * them with their own truncation notices) that a second copy would drift.
 *
 * PDF and image bytes are fetched as an authenticated blob and handed to the
 * browser's own renderer. A plain `<embed src="/api/...">` would not carry the
 * app's Bearer token, so every request goes through apiClient, never a raw
 * URL. Every other format is rendered from the backend's already-bounded
 * structured preview (app/services/document_preview.py) rather than being
 * parsed in the browser.
 */

interface PreviewSlide {
  index: number;
  texts: string[];
}

interface PreviewSheet {
  name: string;
  rows: unknown[][];
  totalRows: number;
  totalCols: number;
  truncatedRows: boolean;
  truncatedCols: boolean;
}

export interface PreviewResponse {
  assetId: number;
  filename: string;
  contentType: string | null;
  fileSizeBytes: number | null;
  kind: "native" | "text" | "docx" | "pptx" | "spreadsheet" | "unsupported";
  text?: string;
  truncated?: boolean;
  paragraphs?: string[];
  slides?: PreviewSlide[];
  sheets?: PreviewSheet[];
  truncatedSheets?: boolean;
  reason?: string;
}

/** The fields a preview needs -- narrower than ProjectDocument or ProjectAsset
 *  so either can be passed straight in. */
export interface PreviewableDocument {
  id: number;
  filename: string;
  original_filename: string | null;
  file_extension: string | null;
}

const IMAGE_EXTENSIONS = new Set([
  ".jpg",
  ".jpeg",
  ".png",
  ".gif",
  ".webp",
  ".bmp",
  ".svg",
]);

/** Download the original bytes. Shared so the dialog's header button and the
 *  preview's own fallback buttons behave identically. */
export function useAssetDownload(projectId: number, doc: PreviewableDocument) {
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const download = useCallback(async () => {
    setDownloading(true);
    try {
      const res = await apiClient.stream(
        `/api/projects/${projectId}/assets/${doc.id}/content`,
      );
      if (!res.ok) throw new Error(`Download failed (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = doc.original_filename || doc.filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      setDownloadError("Download failed. Please try again.");
    } finally {
      setDownloading(false);
    }
  }, [projectId, doc.id, doc.original_filename, doc.filename]);

  return { download, downloading, downloadError };
}

export function DocumentPreview({
  projectId,
  document: doc,
}: {
  projectId: number;
  document: PreviewableDocument;
}) {
  const extension = (doc.file_extension || "").toLowerCase();
  const isImage = IMAGE_EXTENSIONS.has(extension);
  const isPdf = extension === ".pdf";
  const isNative = isImage || isPdf;

  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeSheet, setActiveSheet] = useState(0);
  const { download, downloading } = useAssetDownload(projectId, doc);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setLoading(true);
    setError(null);
    setPreview(null);
    setBlobUrl(null);
    setActiveSheet(0);

    async function load() {
      try {
        if (isNative) {
          const res = await apiClient.stream(
            `/api/projects/${projectId}/assets/${doc.id}/content`,
          );
          if (!res.ok) throw new Error(`This document could not be loaded (${res.status}).`);
          const blob = await res.blob();
          objectUrl = URL.createObjectURL(blob);
          if (active) setBlobUrl(objectUrl);
        } else {
          const data = await apiClient.get<PreviewResponse>(
            `/api/projects/${projectId}/assets/${doc.id}/preview`,
          );
          if (active) setPreview(data);
        }
      } catch (err) {
        if (active) {
          setError(
            err instanceof Error ? err.message : "This document could not be loaded.",
          );
        }
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [projectId, doc.id, isNative]);

  return (
    <div className="flex-1 overflow-auto bg-slate-50">
      {loading && (
        <div className="flex h-full items-center justify-center text-sm text-slate-500">
          Loading…
        </div>
      )}

      {!loading && error && (
        <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
          <p className="text-sm text-slate-600">{error}</p>
          <button
            type="button"
            onClick={() => void download()}
            disabled={downloading}
            className="rounded-md bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {downloading ? "Downloading…" : "Download instead"}
          </button>
        </div>
      )}

      {!loading && !error && isNative && blobUrl && isPdf && (
        <embed src={blobUrl} type="application/pdf" className="h-full w-full" />
      )}
      {!loading && !error && isNative && blobUrl && isImage && (
        <div className="flex h-full items-center justify-center p-4">
          {/* eslint-disable-next-line @next/next/no-img-element -- blobUrl is a
              runtime object URL from an authenticated fetch, not a static/remote
              asset next/image can manage. */}
          <img
            src={blobUrl}
            alt={doc.original_filename || doc.filename}
            className="max-h-full max-w-full object-contain"
          />
        </div>
      )}

      {!loading && !error && !isNative && preview?.kind === "text" && (
        <div className="p-4">
          {preview.truncated && (
            <p className="mb-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
              This preview is truncated. Download the file to see the full content.
            </p>
          )}
          <pre className="whitespace-pre-wrap break-words rounded-md bg-white p-3 text-xs text-slate-800 shadow-sm">
            {preview.text}
          </pre>
        </div>
      )}

      {!loading && !error && !isNative && preview?.kind === "docx" && (
        <div className="space-y-3 p-4">
          {preview.truncated && (
            <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
              This preview is truncated. Download the file to see the full document.
            </p>
          )}
          <div className="space-y-2 rounded-md bg-white p-4 shadow-sm">
            {(preview.paragraphs ?? []).map((paragraph, index) => (
              <p key={index} className="text-sm text-slate-800">
                {paragraph}
              </p>
            ))}
          </div>
        </div>
      )}

      {!loading && !error && !isNative && preview?.kind === "pptx" && (
        <div className="space-y-3 p-4">
          {preview.truncated && (
            <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
              This preview is truncated. Download the file to see every slide.
            </p>
          )}
          {(preview.slides ?? []).map((slide) => (
            <div key={slide.index} className="rounded-md bg-white p-3 shadow-sm">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                Slide {slide.index}
              </div>
              {slide.texts.map((text, index) => (
                <p key={index} className="text-sm text-slate-800">
                  {text}
                </p>
              ))}
            </div>
          ))}
        </div>
      )}

      {!loading && !error && !isNative && preview?.kind === "spreadsheet" && (
        <div className="flex h-full flex-col">
          {(preview.sheets?.length ?? 0) > 1 && (
            <div className="flex gap-1 overflow-x-auto border-b border-slate-200 bg-white px-2 py-1.5">
              {preview.sheets!.map((sheet, index) => (
                <button
                  key={sheet.name}
                  type="button"
                  onClick={() => setActiveSheet(index)}
                  className={`shrink-0 rounded-md px-2.5 py-1 text-xs font-medium ${
                    index === activeSheet
                      ? "bg-brand-600 text-white"
                      : "text-slate-600 hover:bg-slate-100"
                  }`}
                >
                  {sheet.name}
                </button>
              ))}
            </div>
          )}
          {preview.truncatedSheets && (
            <p className="bg-amber-50 px-3 py-2 text-xs text-amber-700">
              Only the first {preview.sheets?.length ?? 0} sheets are shown. Download the
              file to see the rest.
            </p>
          )}
          {(() => {
            const sheet = preview.sheets?.[activeSheet];
            if (!sheet) return null;
            return (
              <div className="flex-1 overflow-auto p-2">
                {(sheet.truncatedRows || sheet.truncatedCols) && (
                  <p className="mb-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
                    Showing {Math.min(sheet.rows.length, sheet.totalRows)} of{" "}
                    {sheet.totalRows.toLocaleString()} rows
                    {sheet.truncatedCols
                      ? ` and the first ${sheet.rows[0]?.length ?? 0} of ${sheet.totalCols} columns`
                      : ""}
                    . Download the file for the full workbook.
                  </p>
                )}
                <table className="min-w-full border-collapse bg-white text-xs shadow-sm">
                  <tbody>
                    {sheet.rows.map((row, rowIndex) => (
                      <tr
                        key={rowIndex}
                        className={
                          rowIndex === 0
                            ? "bg-slate-100 font-semibold"
                            : "odd:bg-white even:bg-slate-50"
                        }
                      >
                        {row.map((cell, cellIndex) => (
                          <td
                            key={cellIndex}
                            className="border border-slate-200 px-2 py-1 text-slate-800"
                          >
                            {cell === null || cell === undefined ? "" : String(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })()}
        </div>
      )}

      {!loading && !error && !isNative && preview?.kind === "unsupported" && (
        <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
          <p className="text-sm text-slate-600">
            {preview.reason || "This file can't be previewed."}
          </p>
          <button
            type="button"
            onClick={() => void download()}
            disabled={downloading}
            className="rounded-md bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {downloading ? "Downloading…" : "Download"}
          </button>
        </div>
      )}
    </div>
  );
}
