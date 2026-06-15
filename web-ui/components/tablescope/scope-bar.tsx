"use client";

import { useEffect } from "react";
import { IconPlus } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { useScopeStore, type SavedScope } from "@/lib/ui/scope-store";

export function ScopeBar({
  projectId,
  savedScopes,
  onAddScope,
}: {
  projectId: string;
  savedScopes: SavedScope[];
  onAddScope?: () => void;
}) {
  const active = useScopeStore((s) => s.active);
  const scopes = useScopeStore((s) => s.savedScopes);
  const setActive = useScopeStore((s) => s.setActive);
  const setProject = useScopeStore((s) => s.setProject);
  const setSavedScopes = useScopeStore((s) => s.setSavedScopes);

  useEffect(() => {
    setProject(projectId, savedScopes);
  }, [projectId, savedScopes, setProject]);

  useEffect(() => {
    setSavedScopes(savedScopes);
  }, [savedScopes, setSavedScopes]);

  const pill = (key: string, label: string) => (
    <button
      key={key}
      type="button"
      onClick={() => setActive(key)}
      className={cn(
        "rounded-full px-3 py-1 text-[12px] font-medium transition-colors",
        active === key
          ? "bg-brand text-brand-fg"
          : "text-ink-secondary hover:bg-bg-secondary",
      )}
    >
      {label}
    </button>
  );

  return (
    <div className="flex items-center gap-2 rounded-lg border border-line-tertiary bg-bg-primary px-3 py-2">
      <span className="text-caption uppercase tracking-wide text-ink-tertiary">
        Scope
      </span>
      {pill("all", "All tables")}
      {scopes.map((s) => pill(s.id, s.name))}
      <button
        type="button"
        onClick={onAddScope}
        className="ml-1 flex items-center gap-1 rounded-full px-2.5 py-1 text-[12px] text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
      >
        <IconPlus size={13} />
        Add scope
      </button>
    </div>
  );
}
