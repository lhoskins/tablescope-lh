import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const get = vi.fn();

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: (...args: unknown[]) => get(...args) },
}));

import { useItsmDashboardQuery } from "./use-itsm-dashboard-query";
import type { ItsmDashboardResult } from "./types";

function baseDashboard(cacheStatus: string): ItsmDashboardResult {
  return {
    dashboard: "incident",
    asOf: "2026-08-18T00:00:00Z",
    filters: {},
    metrics: [],
    charts: [],
    dataQuality: {
      latestCompleteMonth: "2026-07",
      missingMetrics: [],
      warnings: [],
      cacheStatus: cacheStatus as ItsmDashboardResult["dataQuality"]["cacheStatus"],
      cacheAgeSeconds: 0,
    },
  };
}

function Probe({ queryKey, dashboardUrl }: { queryKey: readonly unknown[]; dashboardUrl: string }) {
  const { dashboard, backgroundRefreshing } = useItsmDashboardQuery(queryKey as never, dashboardUrl, true);
  return (
    <div>
      <span data-testid="status">{dashboard?.dataQuality.cacheStatus ?? "loading"}</span>
      <span data-testid="refreshing">{String(backgroundRefreshing)}</span>
    </div>
  );
}

function renderProbe(dashboardUrl: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Probe queryKey={["test", dashboardUrl]} dashboardUrl={dashboardUrl} />
    </QueryClientProvider> as unknown as ReactNode,
  );
}

beforeEach(() => {
  get.mockReset();
  sessionStorage.clear();
});

describe("useItsmDashboardQuery", () => {
  it("does not force a live recompute when the backend served a fresh cache hit", async () => {
    get.mockResolvedValueOnce(baseDashboard("fresh"));
    renderProbe("/api/projects/1/itsm-dashboards/incident?a=fresh");

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("fresh"));
    // Give the background-refresh effect a chance to fire if it were going to.
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(get).toHaveBeenCalledTimes(1);
    expect(get).not.toHaveBeenCalledWith(expect.stringContaining("refresh=true"));
  });

  it("lazily overwrites a stale cache hit with a live recompute in the background", async () => {
    get.mockResolvedValueOnce(baseDashboard("stale"));
    get.mockResolvedValueOnce(baseDashboard("refreshed"));
    renderProbe("/api/projects/1/itsm-dashboards/incident?a=stale");

    // The "stale" cache hit renders first (possibly too briefly to observe
    // directly), then the background-refresh effect fires a second, forced
    // request and overwrites it with the live result.
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(get.mock.calls[1][0]).toContain("refresh=true");
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("refreshed"));
  });

  it("does not re-request when the initial response was already a live compute", async () => {
    get.mockResolvedValueOnce(baseDashboard("miss"));
    renderProbe("/api/projects/1/itsm-dashboards/incident?a=miss");

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("miss"));
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(get).toHaveBeenCalledTimes(1);
  });
});
