import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

/**
 * The AI Query Designer's "Describe" step must fold its structured
 * parameters (specific columns/metrics, period, dimension) into the single
 * free-text question generate-query-preview accepts -- mirroring the AI
 * Dashboard Designer's buildDesignPrompt pattern -- and hand off to
 * GenerateQueryPreviewModal for the preview/save step, with a working way
 * back to the parameters instead of losing them.
 */

const previewModalProps = vi.hoisted(() => ({
  current: null as null | { open: boolean; question: string; title?: string },
}));

vi.mock("@/components/ai/GenerateQueryPreviewModal", () => ({
  GenerateQueryPreviewModal: (props: {
    open: boolean;
    question: string;
    title?: string;
    onBack?: () => void;
  }) => {
    previewModalProps.current = props;
    if (!props.open) return null;
    return (
      <div data-testid="preview-modal">
        <div data-testid="preview-question">{props.question}</div>
        {props.onBack && (
          <button type="button" onClick={props.onBack}>
            Back
          </button>
        )}
      </div>
    );
  },
}));

import { AIQueryDesigner } from "./ai-query-designer";

function renderDesigner(open = true) {
  const notify = vi.fn();
  const onClose = vi.fn();
  render(
    <AIQueryDesigner
      open={open}
      projectId="42"
      onClose={onClose}
      notify={notify}
    />,
  );
  return { notify, onClose };
}

describe("AIQueryDesigner", () => {
  it("disables generation until the user provides a specific column or context", () => {
    renderDesigner();

    expect(
      screen.getByRole("button", { name: /analyze data & generate query/i }),
    ).toBeDisabled();

    fireEvent.change(
      screen.getByPlaceholderText("Example: Total revenue by month"),
      { target: { value: "Total revenue by month" } },
    );

    expect(
      screen.getByRole("button", { name: /analyze data & generate query/i }),
    ).not.toBeDisabled();
  });

  it("folds specific columns, period, and dimension into one question for the preview modal", () => {
    renderDesigner();

    fireEvent.change(
      screen.getByPlaceholderText("Example: Total revenue by month"),
      { target: { value: "Total revenue by month" } },
    );
    fireEvent.change(screen.getByDisplayValue("1 year"), {
      target: { value: "90_days" },
    });
    fireEvent.change(
      screen.getByPlaceholderText("Example: Site, Region, Team"),
      { target: { value: "Region" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: /analyze data & generate query/i }),
    );

    expect(screen.getByTestId("preview-modal")).toBeInTheDocument();
    const question = previewModalProps.current?.question ?? "";
    expect(question).toContain("Total revenue by month");
    expect(question).toContain("Default period: 90 days.");
    expect(question).toContain("Primary dimension: Region.");
  });

  it("returns to the parameters step instead of discarding them on Back", () => {
    renderDesigner();

    fireEvent.change(
      screen.getByPlaceholderText("Example: Total revenue by month"),
      { target: { value: "Total revenue by month" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: /analyze data & generate query/i }),
    );
    expect(screen.getByTestId("preview-modal")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /back/i }));

    expect(screen.queryByTestId("preview-modal")).not.toBeInTheDocument();
    expect(
      screen.getByDisplayValue("Total revenue by month"),
    ).toBeInTheDocument();
  });
});
