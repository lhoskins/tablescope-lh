"use client";

import { useState } from "react";
import {
  IconArrowDown,
  IconArrowUp,
  IconCheck,
  IconCopy,
  IconPlus,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import { createReport } from "@/lib/api/home-intelligence";
import { useReportBuilder } from "@/lib/stores/report-builder-store";
import { IntelligenceCard } from "./intelligence-card";

export function ReportBuilderPanel() {
  const {
    open,
    title,
    sections,
    previews,
    closePanel,
    setTitle,
    addTextBlock,
    updateTextBlock,
    removeSection,
    reorderSections,
    reset,
  } = useReportBuilder();

  const [saving, setSaving] = useState(false);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const report = await createReport({
        title: title || "Untitled report",
        sections: sections.map((s) => ({
          id: s.id,
          kind: s.kind,
          insight: s.insight,
          text: s.text,
        })),
        share_settings: { isPublic: true },
      });
      const fullUrl =
        typeof window !== "undefined"
          ? `${window.location.origin}${report.shareUrl}`
          : report.shareUrl;
      setShareUrl(fullUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save report");
    } finally {
      setSaving(false);
    }
  };

  const handleCopy = async () => {
    if (!shareUrl) return;
    await navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-black/30"
        onClick={closePanel}
        aria-hidden
      />
      <div className="relative flex h-full w-[640px] max-w-full flex-col bg-bg-primary shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line-tertiary px-5 py-3">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="min-w-0 flex-1 bg-transparent text-h2 text-ink-primary outline-none"
            placeholder="Untitled report"
          />
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || sections.length === 0}
              className="rounded-md bg-brand px-3 py-1.5 text-small font-medium text-brand-fg transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save & share"}
            </button>
            <button
              type="button"
              onClick={() => window.print()}
              className="rounded-md border border-line-tertiary px-3 py-1.5 text-small font-medium text-ink-secondary transition-colors hover:bg-bg-tertiary"
            >
              Export PDF
            </button>
            <button
              type="button"
              onClick={closePanel}
              aria-label="Close"
              className="rounded-md p-1.5 text-ink-tertiary transition-colors hover:bg-bg-tertiary"
            >
              <IconX size={18} />
            </button>
          </div>
        </div>

        {/* Share URL banner */}
        {shareUrl && (
          <div className="flex items-center gap-2 border-b border-line-tertiary bg-success/10 px-5 py-2.5 text-small">
            <span className="truncate text-ink-secondary">{shareUrl}</span>
            <button
              type="button"
              onClick={handleCopy}
              className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-ink-secondary hover:bg-bg-tertiary"
            >
              {copied ? <IconCheck size={13} /> : <IconCopy size={13} />}
              {copied ? "Copied" : "Copy link"}
            </button>
          </div>
        )}
        {error && (
          <div className="border-b border-line-tertiary bg-danger/10 px-5 py-2.5 text-small text-danger">
            {error}
          </div>
        )}

        {/* Sections */}
        <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
          {sections.length === 0 && (
            <div className="rounded-lg border border-dashed border-line-secondary p-8 text-center text-small text-ink-tertiary">
              Add insight cards from the feed, or add a text block to start your
              report.
            </div>
          )}
          {sections.map((section, i) => (
            <div
              key={section.id}
              className="rounded-lg border border-line-tertiary bg-bg-secondary p-2"
            >
              <div className="mb-1 flex items-center justify-end gap-1">
                <button
                  type="button"
                  aria-label="Move up"
                  disabled={i === 0}
                  onClick={() => reorderSections(i, i - 1)}
                  className="rounded p-1 text-ink-tertiary hover:bg-bg-tertiary disabled:opacity-30"
                >
                  <IconArrowUp size={14} />
                </button>
                <button
                  type="button"
                  aria-label="Move down"
                  disabled={i === sections.length - 1}
                  onClick={() => reorderSections(i, i + 1)}
                  className="rounded p-1 text-ink-tertiary hover:bg-bg-tertiary disabled:opacity-30"
                >
                  <IconArrowDown size={14} />
                </button>
                <button
                  type="button"
                  aria-label="Remove section"
                  onClick={() => removeSection(section.id)}
                  className="rounded p-1 text-ink-tertiary hover:bg-danger/10 hover:text-danger"
                >
                  <IconTrash size={14} />
                </button>
              </div>
              {section.kind === "insight" && previews[section.id] ? (
                <IntelligenceCard card={previews[section.id]} hideActions />
              ) : section.kind === "insight" ? (
                <div className="rounded-md border border-line-tertiary bg-bg-primary p-3 text-small text-ink-secondary">
                  <div className="font-medium text-ink-primary">
                    {section.insight?.title}
                  </div>
                  <div className="text-caption text-ink-tertiary">
                    {section.insight?.projectName} · {section.insight?.insightType}
                  </div>
                </div>
              ) : (
                <textarea
                  value={section.text ?? ""}
                  onChange={(e) => updateTextBlock(section.id, e.target.value)}
                  placeholder="Add a note or context…"
                  rows={3}
                  className="w-full resize-y rounded-md border border-line-tertiary bg-bg-primary p-2 text-small text-ink-primary outline-none focus:border-brand"
                />
              )}
            </div>
          ))}

          <button
            type="button"
            onClick={addTextBlock}
            className="inline-flex items-center gap-1 rounded-md border border-line-tertiary px-3 py-1.5 text-small text-ink-secondary transition-colors hover:bg-bg-tertiary"
          >
            <IconPlus size={14} /> Add text block
          </button>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-line-tertiary px-5 py-2.5">
          <span className="text-caption text-ink-tertiary">
            {sections.length} section{sections.length === 1 ? "" : "s"}
          </span>
          <button
            type="button"
            onClick={() => {
              reset();
              setShareUrl(null);
            }}
            className="text-caption text-ink-tertiary hover:text-ink-secondary"
          >
            Clear report
          </button>
        </div>
      </div>
    </div>
  );
}
