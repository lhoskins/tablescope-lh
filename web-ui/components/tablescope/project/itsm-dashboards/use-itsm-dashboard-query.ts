"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { ItsmDashboardResult } from "./types";

/** Matches the backend's stale-eviction window (`itsm_metrics/cache.py`
 *  STALE_SECONDS) -- a session-cached entry older than this is no more
 *  trustworthy than not having one, so it's not used as `initialData`. */
const SESSION_CACHE_TTL_MS = 24 * 60 * 60 * 1000;

interface SessionCacheEntry {
  storedAt: number;
  data: ItsmDashboardResult;
}

function readSessionDashboard(key: string): ItsmDashboardResult | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return undefined;
    const entry = JSON.parse(raw) as Partial<SessionCacheEntry>;
    if (!entry?.storedAt || !entry.data || Date.now() - entry.storedAt > SESSION_CACHE_TTL_MS) {
      return undefined;
    }
    return entry.data;
  } catch {
    return undefined;
  }
}

/**
 * Fetches one ITSM dashboard preset with a stale-while-revalidate cache
 * chain: sessionStorage for an instant paint across page refreshes, the
 * backend's own 5-minute-fresh/24-hour-stale cache (`itsm_metrics/cache.py`)
 * for repeat opens, and a lazy background recompute only when the backend
 * says the response was actually `stale` -- a `fresh` response is trusted
 * as-is instead of being immediately re-fetched, which is what previously
 * defeated the backend cache on nearly every mount.
 *
 * Shared by `ItsmDashboardContent` (KPI presets) and
 * `ItsmInsightsDashboardContent` (insight presets), which previously carried
 * byte-identical copies of this logic.
 */
export function useItsmDashboardQuery(queryKey: QueryKey, dashboardUrl: string, enabled: boolean) {
  const queryClient = useQueryClient();
  const cacheToken = queryKey.join(":");
  const browserCacheKey = `itsm-dashboard:${cacheToken}`;
  const [backgroundRefreshing, setBackgroundRefreshing] = useState(false);
  const [manualRefreshing, setManualRefreshing] = useState(false);
  const refreshedKeys = useRef(new Set<string>());

  const {
    data: dashboard,
    isLoading,
    isFetching,
    error,
  } = useQuery<ItsmDashboardResult>({
    queryKey,
    queryFn: () => apiClient.get<ItsmDashboardResult>(dashboardUrl),
    enabled,
    initialData: () => readSessionDashboard(browserCacheKey),
    refetchOnMount: "always",
    staleTime: 5 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
  });

  useEffect(() => {
    if (!dashboard || typeof window === "undefined") return;
    try {
      sessionStorage.setItem(browserCacheKey, JSON.stringify({ storedAt: Date.now(), data: dashboard }));
    } catch {
      // React Query remains the in-memory fallback when storage is unavailable.
    }
  }, [browserCacheKey, dashboard]);

  useEffect(() => {
    if (!dashboard || isFetching || refreshedKeys.current.has(cacheToken)) return;
    refreshedKeys.current.add(cacheToken);
    // Only a "stale" hit (served past the backend's fresh window but before
    // its 24h eviction) needs a lazy background recompute. "fresh" is
    // trustworthy as-is; "miss"/"refreshed" are already a live compute.
    if (dashboard.dataQuality.cacheStatus !== "stale") return;
    let cancelled = false;
    setBackgroundRefreshing(true);
    apiClient
      .get<ItsmDashboardResult>(`${dashboardUrl}&refresh=true`)
      .then((liveDashboard) => {
        if (!cancelled) queryClient.setQueryData(queryKey, liveDashboard);
      })
      .catch(() => {
        // Keep the instantly rendered cached snapshot if background refresh fails.
      })
      .finally(() => {
        if (!cancelled) setBackgroundRefreshing(false);
      });
    return () => {
      cancelled = true;
    };
  }, [cacheToken, dashboard, dashboardUrl, isFetching, queryClient, queryKey]);

  const forceRefresh = async () => {
    setManualRefreshing(true);
    try {
      const liveDashboard = await apiClient.get<ItsmDashboardResult>(`${dashboardUrl}&refresh=true`);
      queryClient.setQueryData(queryKey, liveDashboard);
    } finally {
      setManualRefreshing(false);
    }
  };

  return { dashboard, isLoading, isFetching, error, backgroundRefreshing, manualRefreshing, forceRefresh };
}
