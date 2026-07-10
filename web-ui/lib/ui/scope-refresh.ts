"use client";

import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

/**
 * Custom DOM event fired whenever scopes change (toggle / create / edit /
 * delete). Non-React-Query consumers (e.g. the scope store) can listen for it
 * to refresh without a full page reload.
 */
export const SCOPES_CHANGED_EVENT = "tablescope:scopes-changed";

/**
 * Returns a callback that live-refreshes every view affected by a scope change
 * without reloading the page. It invalidates the project-scoped React Query
 * caches (the query-scopes list is the single source of truth for which
 * columns are drillable) and broadcasts a DOM event for non-RQ listeners.
 */
export function useNotifyScopesChanged() {
  const queryClient = useQueryClient();
  return useCallback(() => {
    // Broad prefix invalidation is robust to string/number projectId keys.
    queryClient.invalidateQueries({ queryKey: ["project"] });
    queryClient.invalidateQueries({ queryKey: ["query-scopes"] });
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent(SCOPES_CHANGED_EVENT));
    }
  }, [queryClient]);
}
