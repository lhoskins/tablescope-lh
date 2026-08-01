"use client";

import { useState } from "react";
import { IconLink } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { importFromUrl } from "@/lib/api/data-source-builder";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { ImportProgress } from "./import-progress";
import { sessionSourceFromPreview, type ImportStage } from "./import-source";

/** Host and file name only — a URL's query string can carry a signed token. */
function safeSummary(raw: string): { host: string; fileName: string } | null {
  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== "https:") return null;
    const last = parsed.pathname.split("/").filter(Boolean).pop();
    return { host: parsed.host, fileName: last ? decodeURIComponent(last) : "—" };
  } catch {
    return null;
  }
}

export function UrlImportForm({ onImported }: { onImported?: () => void }) {
  const addSource = useBuilderStore((s) => s.addSource);
  const markCreated = useBuilderStore((s) => s.markCreated);

  const [url, setUrl] = useState("");
  const [stage, setStage] = useState<ImportStage>("idle");
  const [error, setError] = useState<string | null>(null);

  const summary = safeSummary(url.trim());
  const canSubmit = Boolean(summary) && stage !== "validating";

  const run = async () => {
    setError(null);
    setStage("validating");
    try {
      setStage("transferring");
      const preview = await importFromUrl(url.trim());
      setStage("profiling");
      const source = sessionSourceFromPreview(preview);
      addSource(source);
      markCreated([source.id]);
      setStage("ready");
      setUrl("");
      onImported?.();
    } catch (err) {
      setStage("error");
      setError(
        err instanceof Error
          ? err.message
          : "That file could not be imported from the web.",
      );
    }
  };

  return (
    <div>
      <label
        htmlFor="import-url"
        className="block text-caption font-medium text-ink-secondary"
      >
        File URL (https only)
      </label>
      <div className="mt-1 flex gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-line-secondary bg-bg-primary px-3 py-2 focus-within:border-brand-100 focus-within:ring-2 focus-within:ring-brand-100">
          <IconLink size={16} className="shrink-0 text-ink-tertiary" />
          <input
            id="import-url"
            type="url"
            inputMode="url"
            autoComplete="off"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com/reports/sales.csv"
            className="min-w-0 flex-1 bg-transparent text-[13px] text-ink-primary outline-none placeholder:text-ink-tertiary"
          />
        </div>
        <Button
          variant="primary"
          disabled={!canSubmit}
          onClick={() => void run()}
        >
          Import &amp; analyze
        </Button>
      </div>

      {url.trim() && !summary && (
        <p className="mt-1.5 text-caption text-danger">
          Enter a full https:// URL that points directly at a file.
        </p>
      )}
      {summary && (
        <p className="mt-1.5 text-caption text-ink-tertiary">
          Source: <span className="font-medium">{summary.host}</span> · File:{" "}
          <span className="font-mono">{summary.fileName}</span>
        </p>
      )}

      <ImportProgress
        stage={stage}
        error={error}
        onRetry={() => setStage("idle")}
      />

      <p className="mt-2 text-caption text-ink-tertiary">
        The file is downloaded by Tablescope, security-scanned, and stored as a
        snapshot. It is not re-read from the web later.
      </p>
    </div>
  );
}
