"use client";

import { useState } from "react";

export type ScopeDraft = {
  sourceTable: string;
  sourceColumn: string;
  targetTable: string;
  targetColumn: string;
};

type Props = {
  initial?: Partial<ScopeDraft>;
  onSubmit: (draft: ScopeDraft) => void;
  submitting?: boolean;
};

export function ScopeForm({ initial, onSubmit, submitting }: Props) {
  const [draft, setDraft] = useState<ScopeDraft>({
    sourceTable: initial?.sourceTable ?? "",
    sourceColumn: initial?.sourceColumn ?? "",
    targetTable: initial?.targetTable ?? "",
    targetColumn: initial?.targetColumn ?? "",
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(draft);
      }}
      className="grid grid-cols-1 gap-3 md:grid-cols-5"
    >
      {(["sourceTable", "sourceColumn", "targetTable", "targetColumn"] as const).map((field) => (
        <input
          key={field}
          value={draft[field]}
          onChange={(e) => setDraft((prev) => ({ ...prev, [field]: e.target.value }))}
          placeholder={field}
          className="rounded-md border border-slate-200 px-3 py-2 text-sm"
        />
      ))}
      <button
        type="submit"
        disabled={submitting}
        className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg disabled:opacity-50"
      >
        {submitting ? "Saving…" : "Save"}
      </button>
    </form>
  );
}
