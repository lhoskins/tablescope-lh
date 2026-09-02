import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ResponsePresenter } from "./ResponsePresenter";
import type { ResponseEnvelope } from "@/lib/api/ai-actions";

function summaryEnvelope(summary: string): ResponseEnvelope {
  return {
    mode: "data",
    sections: ["summary"],
    summary,
  };
}

describe("ResponsePresenter", () => {
  it("renders **bold** markdown in the summary as real emphasis, not literal asterisks", () => {
    render(
      <ResponsePresenter
        envelope={summaryEnvelope(
          "Network has the highest average resolution time at **44.43 hours**.",
        )}
      />,
    );
    expect(screen.queryByText(/\*\*/)).not.toBeInTheDocument();
    expect(screen.getByText("44.43 hours", { selector: "strong" })).toBeInTheDocument();
  });

  it("renders plain summary text unchanged when it has no markdown", () => {
    render(<ResponsePresenter envelope={summaryEnvelope("Here are the results.")} />);
    expect(screen.getByText("Here are the results.")).toBeInTheDocument();
  });
});
