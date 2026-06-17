"use client";

import { useRef, useState } from "react";
import { IconX, IconUpload, IconDownload, IconRefresh } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  referenceLibraryApi,
  type BulkImportRow,
  type BulkValidateResult,
} from "@/lib/api/reference-library";

type Phase = "select" | "preview" | "running" | "done";

interface RowState extends BulkImportRow {
  liveStatus: string;
  liveReason?: string | null;
}

function statusTone(status: string): "success" | "warning" | "neutral" | "ai" | "danger" {
  if (status === "active" || status === "ready") return "success";
  if (status === "processing" || status === "fetching") return "ai";
  if (status === "skipped") return "warning";
  if (status === "failed" || status === "error") return "danger";
  return "neutral";
}

export function BulkImportModal({
  onClose,
  onComplete,
}: {
  onClose: () => void;
  onComplete: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("select");
  const [validation, setValidation] = useState<BulkValidateResult | null>(null);
  const [rows, setRows] = useState<RowState[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState<{
    succeededCount: number;
    failedCount: number;
    skippedCount: number;
  } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    setBusy(true);
    setError(null);
    try {
      const res = await referenceLibraryApi.bulkValidate(file);
      setValidation(res);
      setRows(res.rows.map((r) => ({ ...r, liveStatus: r.status })));
      setPhase("preview");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Validation failed");
    } finally {
      setBusy(false);
    }
  }

  async function startImport(retry = false) {
    if (!validation) return;
    setPhase("running");
    setError(null);
    try {
      if (retry) await referenceLibraryApi.bulkRetry(validation.batchId);
      else await referenceLibraryApi.bulkRun(validation.batchId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start import");
      return;
    }
    void streamProgress(validation.batchId);
  }

  async function streamProgress(batchId: number) {
    const response = await referenceLibraryApi.bulkStream(batchId);
    if (!response.ok || !response.body) {
      setError(`Progress stream failed: ${response.status}`);
      return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const line = frame.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        const json = line.slice(5).trim();
        if (!json) continue;
        try {
          handleEvent(JSON.parse(json));
        } catch {
          /* ignore */
        }
      }
    }
  }

  async function downloadFailures() {
    if (!validation) return;
    try {
      const blob = await referenceLibraryApi.downloadFailures(validation.batchId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `batch-${validation.batchId}-failures.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed");
    }
  }

  function handleEvent(ev: {
    type: string;
    rowNumber?: number;
    status?: string;
    failureReason?: string | null;
    succeededCount?: number;
    failedCount?: number;
    skippedCount?: number;
  }) {
    if (ev.type === "row_update" && ev.rowNumber != null) {
      setRows((prev) =>
        prev.map((r) =>
          r.rowNumber === ev.rowNumber
            ? { ...r, liveStatus: ev.status ?? r.liveStatus, liveReason: ev.failureReason }
            : r,
        ),
      );
    } else if (ev.type === "batch_complete") {
      setSummary({
        succeededCount: ev.succeededCount ?? 0,
        failedCount: ev.failedCount ?? 0,
        skippedCount: ev.skippedCount ?? 0,
      });
      setPhase("done");
      onComplete();
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-lg border border-line-tertiary bg-bg-primary shadow-xl">
        <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
          <h3 className="text-h3 text-ink-primary">Bulk URL Import — Industry</h3>
          <button onClick={onClose} className="text-ink-tertiary hover:text-ink-primary">
            <IconX size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4 text-[13px]">
          {phase === "select" && (
            <div className="space-y-3">
              <p className="text-ink-secondary">
                Upload a CSV with columns <code>title, source_url</code> (plus optional{" "}
                <code>issuing_body, domain_tag, applicability_tag, version_label, fetch_method</code>).
                Rows marked <code>paywalled</code> or <code>manual_required</code> are skipped
                automatically. Tablescope fetches each URL server-side.
              </p>
              <div
                onClick={() => fileRef.current?.click()}
                className="flex cursor-pointer items-center gap-2 rounded-md border border-dashed border-line-secondary px-3 py-6 text-ink-secondary hover:border-brand-500"
              >
                <IconUpload size={16} />
                Click to choose a CSV file
              </div>
              <input
                ref={fileRef}
                type="file"
                accept=".csv"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void handleFile(f);
                }}
              />
              {busy && <div className="text-ai">Validating…</div>}
            </div>
          )}

          {(phase === "preview" || phase === "running" || phase === "done") && validation && (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <Badge tone="neutral">Total {validation.totalRows}</Badge>
                <Badge tone="success">Ready {validation.readyCount}</Badge>
                <Badge tone="warning">Skipped {validation.skippedCount}</Badge>
                <Badge tone="danger">Errors {validation.errorCount}</Badge>
                <Badge tone="outline">Warnings {validation.warningCount}</Badge>
              </div>

              {summary && (
                <div className="rounded-md border border-line-tertiary bg-bg-tertiary px-3 py-2">
                  Import complete — <strong>{summary.succeededCount}</strong> succeeded,{" "}
                  <strong>{summary.failedCount}</strong> failed,{" "}
                  <strong>{summary.skippedCount}</strong> skipped.
                </div>
              )}

              <div className="max-h-[45vh] overflow-y-auto rounded-md border border-line-tertiary">
                <table className="w-full text-[12px]">
                  <thead className="sticky top-0 bg-bg-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
                    <tr>
                      <th className="px-3 py-2">#</th>
                      <th className="px-3 py-2">Title</th>
                      <th className="px-3 py-2">Domain</th>
                      <th className="px-3 py-2">Status</th>
                      <th className="px-3 py-2">Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.rowNumber} className="border-t border-line-tertiary">
                        <td className="px-3 py-2 text-ink-tertiary">{r.rowNumber}</td>
                        <td className="px-3 py-2">
                          <div className="font-medium text-ink-primary">{r.title}</div>
                          <div className="max-w-xs truncate text-ink-tertiary">{r.sourceUrl}</div>
                        </td>
                        <td className="px-3 py-2 text-ink-secondary">{r.domainTag ?? "—"}</td>
                        <td className="px-3 py-2">
                          <Badge tone={statusTone(r.liveStatus)}>{r.liveStatus}</Badge>
                        </td>
                        <td className="px-3 py-2 text-ink-tertiary">
                          {r.liveReason || r.failureReason || r.warnings.join(", ") || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {error && <div className="text-danger">{error}</div>}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-line-tertiary px-4 py-3">
          {phase === "preview" && (
            <>
              <Button variant="ghost" onClick={onClose}>Cancel</Button>
              <Button
                variant="primary"
                onClick={() => startImport(false)}
                disabled={!validation || validation.readyCount === 0}
              >
                Import {validation?.readyCount ?? 0} ready rows
              </Button>
            </>
          )}
          {phase === "running" && (
            <span className="text-ai">Importing… fetching and processing rows.</span>
          )}
          {phase === "done" && validation && (
            <>
              <Button variant="secondary" onClick={() => void downloadFailures()}>
                <IconDownload size={14} /> Failure report
              </Button>
              {(summary?.failedCount ?? 0) > 0 && (
                <Button variant="secondary" onClick={() => startImport(true)}>
                  <IconRefresh size={14} /> Retry failed
                </Button>
              )}
              <Button variant="primary" onClick={onClose}>Done</Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
