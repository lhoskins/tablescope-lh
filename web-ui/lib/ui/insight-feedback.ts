import type { InsightFeedbackRecord } from "@/lib/api/insight-feedback";

export type FeedbackTone =
  | "success"
  | "warning"
  | "brand"
  | "danger"
  | "neutral"
  | "high";

export interface FeedbackDisplayState {
  label: string;
  tone: FeedbackTone;
  tooltip: string;
  reviewStatus: string | undefined;
}

export interface GovernanceDisplayState {
  label: string;
  tone: FeedbackTone;
  tooltip: string;
}

export function getInsightFeedbackDisplayState(
  feedback: InsightFeedbackRecord | null | undefined,
): FeedbackDisplayState | null {
  if (!feedback || feedback.status !== "active") return null;

  const reviewStatus = feedback.review_status;
  const isAgree = feedback.sentiment === "agree";

  if (isAgree || reviewStatus === "not_required") {
    return {
      label: "Feedback Saved",
      tone: "success",
      tooltip: "Your feedback has been saved.",
      reviewStatus,
    };
  }

  switch (reviewStatus) {
    case "pending":
      return {
        label: "Pending Review",
        tone: "warning",
        tooltip: "A reviewer will look at your feedback.",
        reviewStatus,
      };
    case "in_review":
      return {
        label: "In Review",
        tone: "brand",
        tooltip: "A reviewer is examining your feedback.",
        reviewStatus,
      };
    case "needs_more_information":
      return {
        label: "Response Needed",
        tone: "high",
        tooltip: "The reviewer asked for more information. Respond to continue.",
        reviewStatus,
      };
    case "accepted":
      return {
        label: "Feedback Accepted",
        tone: "neutral",
        tooltip: "The reviewer accepted your feedback. The insight is disputed and should be regenerated.",
        reviewStatus,
      };
    case "rejected":
      return {
        label: "Insight Upheld",
        tone: "success",
        tooltip: "The reviewer upheld the insight. Your disagreement was recorded.",
        reviewStatus,
      };
    default:
      return {
        label: "Pending Review",
        tone: "warning",
        tooltip: "Your feedback is awaiting review.",
        reviewStatus,
      };
  }
}

export function getInsightGovernanceDisplayState(
  governanceStatus: string | undefined,
): GovernanceDisplayState | null {
  switch (governanceStatus) {
    case "Under Review":
      return {
        label: "Under Review",
        tone: "warning",
        tooltip: "A team member has submitted feedback on this insight.",
      };
    case "Disputed":
      return {
        label: "Disputed",
        tone: "danger",
        tooltip: "A reviewer accepted the feedback. The insight should be regenerated before it is relied upon.",
      };
    case "Validated":
      return {
        label: "Validated",
        tone: "success",
        tooltip: "A reviewer reviewed and upheld this insight.",
      };
    case "Superseded":
      return {
        label: "Superseded",
        tone: "neutral",
        tooltip: "This insight has been replaced by a newer version.",
      };
    default:
      return null;
  }
}
