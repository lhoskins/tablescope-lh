"use client";

import { useCallback, useEffect, useMemo } from "react";
import { usePathname } from "next/navigation";
import { useCurrentUser, useProjectSummaries } from "@/lib/ui/use-shell-data";

const STORAGE_KEY = "tablescope:last-project-intelligence";

function storageKey(tenantSlug: string, userId?: number | string): string {
  if (!userId) return STORAGE_KEY;
  return `${STORAGE_KEY}:${tenantSlug}:${String(userId)}`;
}

/**
 * Returns the project ID to use for Project Intelligence Settings links.
 * Order of resolution:
 * 1. A project ID already present in the current pathname.
 * 2. The last selected project ID for this tenant/user, if still accessible.
 * 3. `null` if no accessible project has been selected yet.
 */
export function useProjectIntelligenceSelection(): {
  selectedProjectId: string | null;
  setSelectedProjectId: (projectId: string | null) => void;
} {
  const pathname = usePathname();
  const { data: identity } = useCurrentUser();
  const { data: summaries } = useProjectSummaries();

  const accessible = useMemo(
    () => new Set((summaries ?? []).map((p) => p.id)),
    [summaries],
  );

  const routeProjectId = useMemo(() => {
    if (!pathname) return null;
    const match = pathname.match(
      /\/admin\/settings\/project-intelligence\/([^/]+)(?:\/|$)/,
    );
    return match?.[1] ?? null;
  }, [pathname]);

  const storedProjectId = useMemo(() => {
    if (typeof window === "undefined") return null;
    const tenant = identity?.tenant.slug ?? "";
    const userId = identity?.user.id;
    try {
      return window.localStorage.getItem(storageKey(tenant, userId));
    } catch {
      return null;
    }
  }, [identity?.tenant.slug, identity?.user.id]);

  const selectedProjectId = useMemo(() => {
    if (routeProjectId && accessible.has(routeProjectId)) return routeProjectId;
    if (storedProjectId && accessible.has(storedProjectId))
      return storedProjectId;
    return null;
  }, [routeProjectId, storedProjectId, accessible]);

  const setSelectedProjectId = useCallback(
    (projectId: string | null) => {
      const tenant = identity?.tenant.slug ?? "";
      const userId = identity?.user.id;
      try {
        const key = storageKey(tenant, userId);
        if (projectId) {
          window.localStorage.setItem(key, projectId);
        } else {
          window.localStorage.removeItem(key);
        }
      } catch {
        /* ignore storage failures */
      }
    },
    [identity?.tenant.slug, identity?.user.id],
  );

  // Persist the route-derived project ID whenever it is valid and accessible.
  useEffect(() => {
    if (routeProjectId && accessible.has(routeProjectId)) {
      setSelectedProjectId(routeProjectId);
    }
  }, [routeProjectId, accessible, setSelectedProjectId]);

  return { selectedProjectId, setSelectedProjectId };
}
