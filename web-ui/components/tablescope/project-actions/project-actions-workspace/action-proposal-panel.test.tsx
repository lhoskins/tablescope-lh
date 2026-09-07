import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ProjectAction } from "@/lib/api/project-actions";
import { ActionOutcomePanel } from "./action-outcome-panel";
import { ActionProposalPanel } from "./action-proposal-panel";

const proposal = {
  id: 17,
  project_id: 3,
  title: "Escalate chronic late deliveries",
  status: "pending_review",
  priority: "high",
  reviewer_user_id: 9,
  source_surface: "project_insight",
  source_insight_id: "risk-17",
  source_insight_title: "Supplier lead time exceeds SLA",
  proposal_metadata: {
    successCriteria: [{ name: "On-time delivery", metric: "On-time delivery rate", target_value: 95, unit: "%", cadence: "weekly" }],
    duplicateCheck: "No matching open or completed action",
  },
  lock_version: 2,
  subtasks: [
    { id: 1, title: "Validate late-order cohort", archived_at: null },
  ],
} as unknown as ProjectAction;

describe("AI action proposal closed loop", () => {
  it("requires an explicit accept decision", () => {
    const onReview = vi.fn();
    render(
      <ActionProposalPanel
        projectId="3"
        action={proposal}
        canManage
        reviewing={false}
        onReview={onReview}
      />,
    );
    expect(screen.getByText("Human approval required", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("On-time delivery")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(onReview).toHaveBeenCalledWith({
      decision: "accept",
      note: "",
      expected_version: 2,
    });
  });

  it("shows which refreshed insight surfaces ground the result", () => {
    const completed = {
      ...proposal,
      status: "completed",
      outcome_status: "grounded",
      outcome_snapshot: {
        updatedInsight: { title: "SLA risk reduced", summary: "Late deliveries fell to 4%." },
        surfaces: {
          business_insight: { title: "SLA risk reduced" },
          project_insight: { title: "SLA risk reduced" },
        },
      },
    } as unknown as ProjectAction;
    render(<ActionOutcomePanel projectId="3" action={completed} />);
    expect(screen.getByText("Business Insight refreshed")).toBeInTheDocument();
    expect(screen.getByText("Project Insight refreshed")).toBeInTheDocument();
  });
});

