"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { InsightSeverity } from "./insight-severity";
import { InsightChart } from "./insight-chart";
import { InsightCallout } from "./insight-callout";
import { InsightConfidenceEvaluation } from "./insight-confidence-evaluation";
import { EvidenceFingerprint } from "./evidence-fingerprint";
import { VizDecision } from "./viz-decision";
import { VizCandidate } from "./viz-candidate";
import { InsightExplanation } from "./insight-explanation";
import { InsightDiagnostic } from "./insight-diagnostic";
import { ProposedAction } from "./proposed-action";
import { CrossReference } from "./cross-reference";
import { TimeSeriesViewState } from "./time-series-view-state";

export interface GroundingManifest {
  question: string;
  passageCount: number;
  kgNodeCount: number;
  kpiCount: number;
  retrievedAt: string;
  passages?: Array<{
    documentId?: number | null;
    chunkIndex?: number | null;
    title?: string;
    sourceType?: string;
    tier?: string;
    retrievalMethod?: string;
    retrievalScore?: number;
  }>;
  kgNodes?: Array<{ id?: number | string; nodeType: string; title: string }>;
  kpis?: Array<{ kpiKey: string; displayName?: string }>;
}

export interface InsightCard {
  id: string;
  /** Stable, server-generated identifier for this insight instance. */
  insightId?: string;
  projectId: string;
  projectName: string;
  projectColor: string;
  insightType: string;
  severity: InsightSeverity;
  title: string;
  /** Optional natural-language question that investigating this card should ask. */
  question?: string;
  summary: string;
  chart: InsightChart | null;
  callout: InsightCallout | null;
  sources: { tables: string[]; documents: string[] };
  executedAt: string;
  // Optional, backward-compatible metadata emitted by the insight-first
  // pipeline. The UI does not require these and ignores them when absent.
  insightMethod?: string;
  confidenceScore?: number;
  priorityScore?: number;
  validation?: {
    executionStatus?: string;
    rowCount?: number;
    columnsReturned?: string[];
    nonNullMetricCount?: number;
  };
  referenceDocuments?: string[];
  kpiReferences?: string[];
  relationshipMetadata?: {
    leftTable?: string;
    rightTable?: string;
    leftJoinKey?: string;
    rightJoinKey?: string;
    relationshipType?: string;
    joinConfidence?: number;
    confidenceReason?: string;
    rowMultiplicationRisk?: string;
  };
  /** Governed Analytical Method Engine envelope (hybrid mode only). */
  analyticalMethod?: MethodEnvelope;
  /**
   * Deeper-analysis dissection of THIS finding: each step states the question
   * it answers and why it was run, so the drill-down reads as a line of
   * reasoning rather than a pile of charts. Present only when the card was
   * dissected; a card without it must not advertise a full analysis.
   */
  diagnostics?: InsightDiagnostic[];
  /** Grounded next steps derived from what the diagnostics measured. */
  proposedActions?: ProposedAction[];
  /** Card-scoped questions for the ask box. */
  suggestedQuestions?: string[];
  /** Other tables and documents worth checking this finding against. */
  crossReferences?: CrossReference[];
  /**
   * Raw SQL and chart roles for data-backed cards. These are optional and
   * only present when the insight was generated from a successfully executed
   * query. When absent, the card is not eligible for "Save to dashboard".
   */
  sql?: string;
  chartType?: string;
  labelColumn?: string;
  valueColumn?: string;
  valueColumn2?: string;
  /** Structured explainability metadata produced by the insight pipeline. */
  explanation?: InsightExplanation;
  /** Canonical evidence fingerprints used for duplicate suppression. */
  evidenceFingerprint?: EvidenceFingerprint;
  /** Structured evidence-based confidence evaluation. */
  confidenceEvaluation?: InsightConfidenceEvaluation;
  /** Grounding manifest for document passages, KG nodes, and governed KPIs. */
  groundingManifest?: GroundingManifest;
  /** The selected visualization decision for this card's chart. */
  visualizationDecision?: VizDecision;
  /** Ranked compatible chart candidates the user can switch to. */
  chartCandidates?: VizCandidate[];
  /** Active time-series view (mode/interval/range) captured for Home pins and dashboards. */
  timeSeriesView?: TimeSeriesViewState;
}