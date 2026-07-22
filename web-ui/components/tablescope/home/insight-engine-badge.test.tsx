import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { MethodEnvelope } from "@/lib/api/ai-actions";
import {
  getInsightEngineDisplay,
  InsightAnalysisDetails,
  RAnalyticsBadge,
  shouldShowRAnalyticsBadge,
} from "./insight-engine-badge";

const rEnvelope: MethodEnvelope = {
  method: "describe_numeric",
  methodName: "Describe numeric",
  status: "ok",
  executionEngine: "r",
  quality: "reliable",
  n: 42,
};

const fallbackEnvelope: MethodEnvelope = {
  method: "describe_numeric",
  methodName: "Describe numeric",
  status: "ok",
  executionEngine: "python",
  fallbackFrom: "r",
  quality: "reliable",
};

const pythonEnvelope: MethodEnvelope = {
  method: "pearson_correlation",
  methodName: "Pearson correlation",
  status: "ok",
  executionEngine: "python",
};

describe("insight engine display", () => {
  it("labels an R envelope as R Analytics", () => {
    expect(getInsightEngineDisplay(rEnvelope).label).toBe("R Analytics");
  });

  it("labels a fallback envelope as a fallback", () => {
    expect(getInsightEngineDisplay(fallbackEnvelope).label).toBe("python fallback");
  });

  it("shows the R badge only for clean R ok envelopes", () => {
    expect(shouldShowRAnalyticsBadge(rEnvelope)).toBe(true);
    expect(shouldShowRAnalyticsBadge(fallbackEnvelope)).toBe(false);
    expect(shouldShowRAnalyticsBadge(pythonEnvelope)).toBe(false);
    expect(shouldShowRAnalyticsBadge({ ...rEnvelope, status: "insufficient_data" })).toBe(false);
    expect(shouldShowRAnalyticsBadge(null)).toBe(false);
  });
});

describe("RAnalyticsBadge", () => {
  it("renders for an R envelope", () => {
    render(<RAnalyticsBadge envelope={rEnvelope} />);
    expect(screen.getByText("R Analytics")).toBeTruthy();
  });

  it("renders nothing for a fallback envelope", () => {
    const { container } = render(<RAnalyticsBadge envelope={fallbackEnvelope} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("InsightAnalysisDetails", () => {
  it("renders the provenance not available state when no envelope exists", () => {
    render(<InsightAnalysisDetails />);
    expect(screen.getByText(/Provenance not available/i)).toBeTruthy();
  });

  it("renders method details for a supplied envelope", () => {
    render(<InsightAnalysisDetails envelope={rEnvelope} />);
    expect(screen.getByText(/Analysis details/i)).toBeTruthy();
    expect(screen.getByText(/Analytical method: Describe numeric/i)).toBeTruthy();
  });
});
