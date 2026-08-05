"use client";


import { useState, useCallback } from "react";
import { apiClient } from "@/lib/api-client";import { FileEntry } from "./file-entry";



// ── File Review Card ──────────────────────────────────────────────────────

export function FileReviewCard({
  entry,
  onToggleTag,
  onRemoveTag,
  onAddTag,
  onNewTagChange,
  onToggleKpi,
  onNotesChange,
  onDisplayNameChange,
  onCreate,
  onRemove,
}: {
  entry: FileEntry;
  onToggleTag: (idx: number) => void;
  onRemoveTag: (idx: number) => void;
  onAddTag: () => void;
  onNewTagChange: (v: string) => void;
  onToggleKpi: (idx: number) => void;
  onNotesChange: (v: string) => void;
  onDisplayNameChange: (v: string) => void;
  onCreate: () => void;
  onRemove: () => void;
}) {
  const { analysis } = entry;

  // Analyzing
  if (entry.status === "analyzing") {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-4">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-blue-200 border-t-blue-600" />
        <span className="text-sm text-slate-600">{entry.fileName}</span>
        <span className="text-xs text-slate-400">Analyzing...</span>
        <button onClick={onRemove} className="ml-auto text-slate-400 hover:text-red-500 text-sm">&times;</button>
      </div>
    );
  }

  // Error
  if (entry.status === "error") {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-4">
        <span className="text-sm font-medium text-red-700">{entry.fileName}</span>
        <span className="text-xs text-red-500">{entry.error}</span>
        <button onClick={onRemove} className="ml-auto text-red-400 hover:text-red-600 text-sm">&times;</button>
      </div>
    );
  }

  // Done
  if (entry.status === "done") {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-green-200 bg-green-50 px-4 py-4">
        <svg className="h-5 w-5 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span className="text-sm font-medium text-green-800">{entry.displayName}</span>
        <span className="text-xs text-green-600">Datasource created</span>
      </div>
    );
  }

  // Creating
  if (entry.status === "creating") {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-4">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-green-200 border-t-green-600" />
        <span className="text-sm text-slate-600">{entry.displayName}</span>
        <span className="text-xs text-slate-400">Creating datasource...</span>
      </div>
    );
  }

  // Ready for review
  if (!analysis) return null;

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      {/* File header */}
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <span className="text-sm font-semibold text-slate-900">{entry.fileName}</span>
        <button onClick={onRemove} className="text-slate-400 hover:text-red-500 text-sm">&times;</button>
      </div>

      <div className="space-y-4 p-4">
        {/* Error within this card */}
        {entry.error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{entry.error}</div>
        )}

        {/* Grid: File info + AI Summary */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <h3 className="mb-2 text-xs font-medium uppercase text-slate-400">File Info</h3>
            <div className="space-y-1 text-sm">
              <p>
                <span className="text-slate-500">Name:</span>{" "}
                <input
                  value={entry.displayName}
                  onChange={(e) => onDisplayNameChange(e.target.value)}
                  className="ml-1 rounded border border-slate-200 px-2 py-0.5 text-sm"
                />
              </p>
              <p><span className="text-slate-500">Type:</span> {analysis.file.file_type.toUpperCase()}</p>
              <p><span className="text-slate-500">Size:</span> {(analysis.file.file_size_bytes / 1024).toFixed(1)} KB</p>
              <p><span className="text-slate-500">Rows:</span> {analysis.file.row_count.toLocaleString()}</p>
              <p><span className="text-slate-500">Columns:</span> {analysis.file.column_count}</p>
            </div>
          </div>

          <div className="space-y-3">
            <div className="rounded-lg border border-blue-100 bg-blue-50 p-3">
              <h3 className="mb-1 text-xs font-medium uppercase text-blue-600">AI Summary</h3>
              <p className="text-sm text-slate-700">{analysis.summary.ai_summary}</p>
            </div>
            {analysis.summary.business_domain && (
              <div className="flex gap-3 text-sm">
                <span className="rounded-full bg-purple-100 px-3 py-1 text-purple-700">
                  {analysis.summary.business_domain.replace(/_/g, " ")}
                </span>
                {analysis.summary.process_area && (
                  <span className="rounded-full bg-indigo-100 px-3 py-1 text-indigo-700">
                    {analysis.summary.process_area.replace(/_/g, " ")}
                  </span>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Tags */}
        <div>
          <h3 className="mb-2 text-sm font-semibold text-slate-900">Tags</h3>
          <p className="mb-2 text-xs text-slate-400">
            Governed catalog tags. Click to toggle, &times; to remove, or add custom tags.
          </p>
          <div className="flex flex-wrap gap-2 mb-2">
            {entry.tags.map((t, i) => (
              <span
                key={i}
                className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-sm cursor-pointer transition-colors ${
                  t.accepted !== false
                    ? t.source === "user"
                      ? "bg-green-100 text-green-700"
                      : "bg-blue-100 text-blue-700"
                    : "bg-slate-100 text-slate-400 line-through"
                }`}
              >
                <button onClick={() => onToggleTag(i)} className="hover:opacity-70">
                  {t.display_name || t.tag}
                </button>
                {t.confidence != null && (
                  <span className="text-[10px] opacity-60">{(t.confidence * 100).toFixed(0)}%</span>
                )}
                <button onClick={() => onRemoveTag(i)} className="ml-0.5 text-current opacity-50 hover:opacity-100">&times;</button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={entry.newTag}
              onChange={(e) => onNewTagChange(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && onAddTag()}
              placeholder="Add tag..."
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
            <button
              onClick={onAddTag}
              disabled={!entry.newTag.trim()}
              className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
            >
              + Add
            </button>
          </div>
        </div>

        {/* KPIs */}
        {entry.kpis.length > 0 && (
          <div>
            <h3 className="mb-2 text-sm font-semibold text-slate-900">Recommended KPIs</h3>
            <p className="mb-2 text-xs text-slate-400">
              KPIs matched from the governed catalog based on this file&apos;s columns. Click to toggle.
            </p>
            <div className="flex flex-wrap gap-2">
              {entry.kpis.map((k, i) => (
                <span
                  key={i}
                  onClick={() => onToggleKpi(i)}
                  className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-sm cursor-pointer transition-colors ${
                    k.accepted !== false
                      ? "bg-amber-100 text-amber-800"
                      : "bg-slate-100 text-slate-400 line-through"
                  }`}
                  title={k.reason || k.kpi_key}
                >
                  {k.display_name}
                  {k.confidence != null && (
                    <span className="text-[10px] opacity-60">{(k.confidence * 100).toFixed(0)}%</span>
                  )}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Quality & Relationships */}
        {(analysis.data_quality_notes?.length || analysis.relationship_hints?.length) ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {analysis.data_quality_notes && analysis.data_quality_notes.length > 0 && (
              <div className="rounded-lg border border-amber-100 bg-amber-50 p-3">
                <h3 className="mb-1 text-xs font-medium uppercase text-amber-600">Data Quality Notes</h3>
                <ul className="space-y-1 text-sm text-slate-700 list-disc list-inside">
                  {analysis.data_quality_notes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              </div>
            )}
            {analysis.relationship_hints && analysis.relationship_hints.length > 0 && (
              <div className="rounded-lg border border-purple-100 bg-purple-50 p-3">
                <h3 className="mb-1 text-xs font-medium uppercase text-purple-600">Relationship Hints</h3>
                <ul className="space-y-1 text-sm text-slate-700">
                  {analysis.relationship_hints.map((r, i) => (
                    <li key={i}>
                      <span className="font-medium">{r.source_field}</span>
                      <span className="mx-1 text-slate-400">&rarr;</span>
                      <span>{r.possible_target}</span>
                      <span className="ml-1 text-xs text-slate-400">({(r.confidence * 100).toFixed(0)}%)</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : null}

        {/* Notes */}
        <div>
          <h3 className="mb-1 text-sm font-semibold text-slate-900">Notes (optional)</h3>
          <textarea
            value={entry.userNotes}
            onChange={(e) => onNotesChange(e.target.value)}
            placeholder="Business context, data source origin, refresh schedule, known caveats..."
            rows={2}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        {/* Create button */}
        <div className="flex justify-end">
          <button
            onClick={onCreate}
            className="rounded-md bg-green-600 px-6 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-green-700"
          >
            Create Datasource
          </button>
        </div>
      </div>
    </div>
  );
}