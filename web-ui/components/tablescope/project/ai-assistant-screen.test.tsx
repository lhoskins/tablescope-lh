import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { AiAskResponse } from "@/lib/ui/use-project-data";

const askProjectAi = vi.fn();

vi.mock("@/lib/ui/use-project-data", () => ({
  askProjectAi: (...args: unknown[]) => askProjectAi(...args),
  useProjectShell: () => ({
    project: { name: "Acme", documentCount: 2, queryCount: 5 },
    tenant: { name: "Acme Inc" },
  }),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

// The full project shell (nav, router, shell data) is irrelevant here — render
// just the chat body so the test stays focused on presenter integration.
vi.mock("@/components/tablescope/project-shell", () => ({
  ProjectShell: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

// The chart renderer (only reached for data envelopes) pulls in recharts.
vi.mock("@/components/tablescope/home/intelligence-card", () => ({
  InsightChartBlock: () => <div data-testid="chart" />,
}));

import { AiAssistantScreen } from "./ai-assistant-screen";

function ask(text: string) {
  fireEvent.click(screen.getByRole("button", { name: text }));
}

describe("AiAssistantScreen", () => {
  beforeEach(() => askProjectAi.mockReset());

  it("renders the assistant reply through the shared presenter when an envelope is present (M4)", async () => {
    const res: AiAskResponse = {
      answer: "This project holds shipment logs.",
      model_used: "m",
      request_id: "r",
      context_summary: {},
      audit_id: null,
      presentation: { mode: "conversational", sections: ["prose_answer"] },
      envelope: {
        mode: "conversational",
        sections: ["prose_answer"],
        answer: "This project holds shipment logs.",
      },
    };
    askProjectAi.mockResolvedValue(res);
    render(<AiAssistantScreen projectId="7" />);

    ask("Summarize what this project contains");

    const presenter = await screen.findByTestId("response-presenter");
    expect(presenter.dataset.mode).toBe("conversational");
    expect(screen.getByText("This project holds shipment logs.")).toBeTruthy();
    // A conversational reply carries no data table.
    expect(screen.queryByTestId("chart")).toBeNull();
  });

  it("falls back to plain text when the response has no envelope (backward-compat)", async () => {
    const res: AiAskResponse = {
      answer: "Legacy prose reply.",
      model_used: "m",
      request_id: "r",
      context_summary: {},
      audit_id: null,
    };
    askProjectAi.mockResolvedValue(res);
    render(<AiAssistantScreen projectId="7" />);

    ask("Which tables can be joined together?");

    expect(await screen.findByText("Legacy prose reply.")).toBeTruthy();
    expect(screen.queryByTestId("response-presenter")).toBeNull();
  });
});
