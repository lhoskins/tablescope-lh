"use client";

import { create } from "zustand";

export interface SavedScope {
  id: string;
  name: string;
  tables: string[];
  documentFamilies: string[];
}

interface ScopeState {
  projectId: string | null;
  /** 'all' or the id of a saved scope. */
  active: string;
  savedScopes: SavedScope[];
  setProject: (projectId: string, savedScopes?: SavedScope[]) => void;
  setActive: (active: string) => void;
  setSavedScopes: (scopes: SavedScope[]) => void;
  reset: () => void;
}

export const useScopeStore = create<ScopeState>((set) => ({
  projectId: null,
  active: "all",
  savedScopes: [],
  setProject: (projectId, savedScopes) =>
    set((state) =>
      state.projectId === projectId
        ? state
        : {
            projectId,
            active: "all",
            savedScopes: savedScopes ?? [],
          },
    ),
  setActive: (active) => set({ active }),
  setSavedScopes: (savedScopes) => set({ savedScopes }),
  reset: () => set({ projectId: null, active: "all", savedScopes: [] }),
}));

/** Human-readable label for the active scope, used in AI placeholders. */
export function activeScopeName(
  active: string,
  savedScopes: SavedScope[],
): string | null {
  if (active === "all") return null;
  return savedScopes.find((s) => s.id === active)?.name ?? null;
}
