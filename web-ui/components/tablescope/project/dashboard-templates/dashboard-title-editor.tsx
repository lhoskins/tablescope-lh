"use client";

import { useEffect, useState } from "react";

/** Inline dashboard-name editor: clicking the title itself starts editing --
 * no separate pencil icon, matching the project name's own rename pattern
 * (see project/project-topbar.tsx). */
export function DashboardTitleEditor({
  name,
  onSave,
}: {
  name: string;
  onSave: (name: string) => void | Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(name);

  useEffect(() => {
    setValue(name);
  }, [name]);

  const commit = () => {
    const trimmed = value.trim();
    if (trimmed && trimmed !== name) void onSave(trimmed);
    setEditing(false);
  };

  if (editing) {
    return (
      <input
        autoFocus
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          } else if (event.key === "Escape") {
            event.preventDefault();
            setValue(name);
            setEditing(false);
          }
        }}
        onBlur={commit}
        aria-label="Dashboard name"
        className="h-9 w-full max-w-md truncate rounded-md border border-line-secondary bg-bg-primary px-2 text-h2 text-ink-primary focus:border-brand-500 focus:outline-none"
      />
    );
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      title="Click to rename"
      className="-mx-1 truncate rounded px-1 text-left hover:bg-bg-secondary"
    >
      {name}
    </button>
  );
}
