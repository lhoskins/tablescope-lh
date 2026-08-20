"use client";

import { useState } from "react";
import { IconPencil } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";

export function DimensionLabelEditor({ label, onSave }: { label: string; onSave: (label: string) => void | Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(label);
  return <span className="relative inline-flex items-center gap-1">
    <span>{label}</span>
    <button type="button" onClick={() => { setValue(label); setEditing(true); }} className="rounded p-0.5 text-ink-tertiary hover:bg-bg-secondary" title="Configure dashboard dimension"><IconPencil size={12} /></button>
    {editing && <span className="absolute right-0 top-full z-30 mt-1 w-64 rounded-md border border-line-secondary bg-bg-primary p-3 text-left shadow-lg">
      <label className="block text-[11px] font-medium text-ink-secondary">Dimension label</label>
      <input autoFocus value={value} onChange={(event) => setValue(event.target.value)} placeholder="Site, Region, Plant…" className="mt-1 h-8 w-full rounded-md border px-2 text-[11px]" />
      <p className="mt-1 text-[10px] text-ink-tertiary">The approved template binding controls the datasource field.</p>
      <span className="mt-2 flex justify-end gap-1.5"><Button size="sm" variant="secondary" onClick={() => setEditing(false)}>Cancel</Button><Button size="sm" variant="primary" onClick={() => { if (value.trim()) void onSave(value.trim()); setEditing(false); }}>Save</Button></span>
    </span>}
  </span>;
}
