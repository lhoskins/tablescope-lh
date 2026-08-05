"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


/** One step of a card's Deeper-analysis dissection. */
export interface InsightDiagnostic {
  /** localise | when | quantify | explain | project | corroborate */
  stage: string;
  title: string;
  question: string;
  /** Why this step was run — shown so the ladder reads as reasoning. */
  rationale: string;
  /** What it found, in business language. */
  finding: string;
  /** Headline figure, when the method exposes one. */
  highlight?: string;
  /** Set when the step ran because a trigger fired (e.g. a period comparison). */
  triggeredBy?: string | null;
  analyticalMethod?: MethodEnvelope;
  sql?: string;
  result?: { columns?: string[]; rows?: Record<string, unknown>[] };
  /** Governed intent this step ran (e.g. `detect_anomalies`). */
  intent?: string;
  /**
   * Chart family and analytical layers for this step's evidence, chosen from
   * the intent. Without it the caller has to guess, and guessing "bar" reorders
   * a timeline by magnitude.
   */
  presentation?: { chart?: string; layers?: string[] };
  /**
   * Point-level annotations **from the method itself**. `anomalyIndices` are
   * 0-based positions in the period-ordered series; re-deriving them in the
   * renderer would mark different points than the method flagged.
   */
  markers?: {
    anomalyIndices?: number[];
    changePointIndex?: number;
    band?: { expected: number[]; lower: number[]; upper: number[] };
  };
  /** Which column carries the x axis, the measure, and any second measure. */
  roles?: { x?: string; y?: string; y2?: string };
  /**
   * Set when this step was produced by checking an independent source. The
   * named table has already been tested, so it is no longer an open lead.
   */
  crossReference?: string;
  /**
   * For a claim-verification step: whether the data bore out the assertion the
   * card's own summary made. `contradicted` means the narrative is wrong.
   */
  claimVerdict?: "supported" | "contradicted" | "inconclusive" | "untestable";
  /** The measure that was tested to reach that verdict. */
  claimMeasure?: string;
  claimTable?: string;
}