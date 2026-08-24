import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const { getHomeActionSummary } = vi.hoisted(() => ({
  getHomeActionSummary: vi.fn(),
}));
const { getPreferences, updatePreferences } = vi.hoisted(() => ({
  getPreferences: vi.fn(),
  updatePreferences: vi.fn(),
}));

vi.mock("@/lib/api/home-actions", () => ({ getHomeActionSummary }));
vi.mock("@/lib/api/home-intelligence", () => ({ getPreferences, updatePreferences }));

import { PersonalizedHome } from "./personalized-home";

const BASE_SUMMARY = {
  highlights: { needs_attention: 2, due_this_week: 3, recently_completed: 1 },
  assigned: [],
  updates: [
    {
      id: 1,
      project_id: 9,
      project_name: "Sales Operations",
      title: "Approve backlog recovery milestones",
      status: "in_progress",
      priority: "high",
      percent_complete: 40,
      due_date: null,
      completed_at: null,
      updated_at: "2026-08-20T00:00:00Z",
    },
  ],
  updates_matched_focus: false,
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("PersonalizedHome", () => {
  it("labels updates as plain recency when nothing matched the user's focus", async () => {
    getHomeActionSummary.mockResolvedValue(BASE_SUMMARY);
    getPreferences.mockResolvedValue({ intelligence: { home_focus: ["Revenue vs backlog"] } });

    render(<PersonalizedHome projectCount={4} />, { wrapper });

    await waitFor(() =>
      expect(screen.getByText(/Recent changes across your project actions\./)).toBeTruthy(),
    );
    expect(screen.queryByText(/Only changes connected to your focus\./)).toBeNull();
  });

  it("labels updates as focus-connected when the backend matched the user's focus", async () => {
    getHomeActionSummary.mockResolvedValue({ ...BASE_SUMMARY, updates_matched_focus: true });
    getPreferences.mockResolvedValue({ intelligence: { home_focus: ["Revenue vs backlog"] } });

    render(<PersonalizedHome projectCount={4} />, { wrapper });

    await waitFor(() =>
      expect(screen.getByText(/Only changes connected to your focus\./)).toBeTruthy(),
    );
    expect(screen.queryByText(/Recent changes across your project actions\./)).toBeNull();
  });

  it("renders the user's saved focus topics as removable chips", async () => {
    getHomeActionSummary.mockResolvedValue(BASE_SUMMARY);
    getPreferences.mockResolvedValue({
      intelligence: { home_focus: ["Revenue vs backlog", "ITSM SLA risk"] },
    });

    render(<PersonalizedHome projectCount={4} />, { wrapper });

    await waitFor(() => expect(screen.getByText("Revenue vs backlog")).toBeTruthy());
    expect(screen.getByText("ITSM SLA risk")).toBeTruthy();
    expect(screen.getByLabelText("Remove Revenue vs backlog")).toBeTruthy();
  });
});
