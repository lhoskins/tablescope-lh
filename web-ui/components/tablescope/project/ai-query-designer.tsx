"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  IconAlertTriangle,
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconPlus,
  IconSparkles,
  IconX,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  aiActionsApi,
  type GenerateQueryPreviewResult,
} from "@/lib/api/ai-actions";

const PERIODS = [
  ["30_days", "30 days"],
  ["60_days", "60 days"],
  ["90_days", "90 days"],
  ["6_months", "6 months"],
  ["1_year", "1 year"],
  ["2_years", "2 years"],
] as const;

const OUTPUTS = [
  ["table_chart", "Table + chart"],
  ["table", "Table"],
] as const;

const FORMATS = [
  ["auto", "Auto"],
  ["number", "Number"],
  ["usd", "$ USD"],
  ["eur", "€ Euro"],
  ["percent", "Percentage"],
] as const;

type DesignerStep = "describe" | "review" | "create";

type QueryDraft = {
  id: number;
  name: string;
  request: string;
  aggregate: string;
  groupBy: string;
  caseLogic: string;
  filter: string;
  sort: string;
  output: (typeof OUTPUTS)[number][0];
  format: (typeof FORMATS)[number][0];
};

type BatchPreview = {
  draft: QueryDraft;
  question: string;
  result?: GenerateQueryPreviewResult;
  error?: string;
};

type BatchSave = {
  preview: BatchPreview;
  queryId?: number;
  error?: string;
};

const EMPTY_DRAFT: Omit<QueryDraft, "id"> = {
  name: "",
  request: "",
  aggregate: "",
  groupBy: "",
  caseLogic: "",
  filter: "",
  sort: "",
  output: "table_chart",
  format: "auto",
};

const INSTRUCTION_FIELDS: Array<{
  key: "aggregate" | "groupBy" | "caseLogic" | "filter" | "sort";
  label: string;
  placeholder: string;
}> = [
  {
    key: "aggregate",
    label: "SUM / aggregate",
    placeholder:
      "Example: Sum backlog_amount and recognized_revenue. Show both totals for each month.",
  },
  {
    key: "groupBy",
    label: "GROUP BY",
    placeholder: "Example: Group results by order month and customer region.",
  },
  {
    key: "caseLogic",
    label: "CASE",
    placeholder:
      "Example: Label orders over 30 days late as Critical, 1–30 days as At Risk, otherwise On Track.",
  },
  {
    key: "filter",
    label: "FILTER",
    placeholder:
      "Example: Only include Open or Backordered orders from the last 24 months. Exclude cancelled orders.",
  },
  {
    key: "sort",
    label: "SORT",
    placeholder:
      "Example: Sort by month oldest to newest, then backlog amount highest to lowest.",
  },
];

const STEP_LABELS: Array<[DesignerStep, string]> = [
  ["describe", "1. Describe queries"],
  ["review", "2. Review AI plan"],
  ["create", "3. Validate & create"],
];

function instructionCount(draft: QueryDraft) {
  return INSTRUCTION_FIELDS.filter(({ key }) => draft[key].trim()).length;
}

/** Fold one query card into the existing governed generation contract. */
export function buildBatchQueryPrompt(
  draft: QueryDraft,
  periodLabel: string,
  dimensionLabel: string,
  validateJoinCardinality: boolean,
): string {
  const outputLabel =
    OUTPUTS.find(([value]) => value === draft.output)?.[1] ?? draft.output;
  const formatLabel =
    FORMATS.find(([value]) => value === draft.format)?.[1] ?? draft.format;
  const parts = [draft.request.trim()];
  const directives: Array<[string, string]> = [
    ["SUM / aggregate", draft.aggregate],
    ["GROUP BY", draft.groupBy],
    ["CASE", draft.caseLogic],
    ["FILTER", draft.filter],
    ["SORT", draft.sort],
  ];
  for (const [label, value] of directives) {
    if (value.trim()) parts.push(`${label}: ${value.trim()}`);
  }
  parts.push(`Default period: ${periodLabel}.`);
  if (dimensionLabel.trim()) parts.push(`Primary dimension: ${dimensionLabel.trim()}.`);
  parts.push(`Preferred output: ${outputLabel}.`);
  if (draft.format !== "auto") parts.push(`Display format: ${formatLabel}.`);
  if (validateJoinCardinality) {
    parts.push(
      "Validate join keys and cardinality, prevent fan-out, and preserve source lineage.",
    );
  }
  return parts.filter(Boolean).join(" ");
}

function InstructionCard({
  draft,
  field,
  onChange,
}: {
  draft: QueryDraft;
  field: (typeof INSTRUCTION_FIELDS)[number];
  onChange: (value: string) => void;
}) {
  return (
    <label className="rounded-lg border border-line-tertiary bg-bg-primary p-2.5">
      <span className="flex items-center justify-between gap-2 text-[11px] font-semibold text-ink-primary">
        <span className="flex items-center gap-1.5">
          <IconSparkles size={13} className="text-ai" />
          {field.label}
        </span>
        <span className="font-normal text-ink-tertiary">Optional</span>
      </span>
      <textarea
        value={draft[field.key]}
        onChange={(event) => onChange(event.target.value)}
        rows={3}
        aria-label={`${field.label} instructions`}
        placeholder={field.placeholder}
        className="mt-2 w-full resize-y rounded-md border border-line-secondary bg-bg-primary p-2 text-[12px] leading-4 text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
      />
    </label>
  );
}

function StatusBadge({ preview }: { preview: BatchPreview }) {
  const status = preview.result?.status;
  if (status === "success") {
    return (
      <span className="rounded-full bg-success-bg px-2 py-0.5 text-[11px] font-medium text-success">
        Ready
      </span>
    );
  }
  if (status === "needs_clarification") {
    return (
      <span className="rounded-full bg-warning-bg px-2 py-0.5 text-[11px] font-medium text-warning">
        Needs review
      </span>
    );
  }
  return (
    <span className="rounded-full bg-danger-bg px-2 py-0.5 text-[11px] font-medium text-danger">
      Failed
    </span>
  );
}

export function AIQueryDesigner({
  open,
  projectId,
  onClose,
  onSaved,
  notify,
}: {
  open: boolean;
  projectId: string;
  onClose: () => void;
  onSaved?: (queryId: number) => void;
  notify: (message: string, tone?: "success" | "error" | "info") => void;
}) {
  const nextId = useRef(2);
  const [step, setStep] = useState<DesignerStep>("describe");
  const [drafts, setDrafts] = useState<QueryDraft[]>([{ id: 1, ...EMPTY_DRAFT }]);
  const [expandedId, setExpandedId] = useState(1);
  const [period, setPeriod] = useState("1_year");
  const [dimensionLabel, setDimensionLabel] = useState("");
  const [validateJoinCardinality, setValidateJoinCardinality] = useState(true);
  const [requirePreview, setRequirePreview] = useState(true);
  const [previews, setPreviews] = useState<BatchPreview[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [expandedPreviewId, setExpandedPreviewId] = useState<number | null>(null);
  const [saveResults, setSaveResults] = useState<BatchSave[]>([]);

  useEffect(() => {
    if (!open) return;
    nextId.current = 2;
    setStep("describe");
    setDrafts([{ id: 1, ...EMPTY_DRAFT }]);
    setExpandedId(1);
    setPeriod("1_year");
    setDimensionLabel("");
    setValidateJoinCardinality(true);
    setRequirePreview(true);
    setPreviews([]);
    setSelectedIds(new Set());
    setExpandedPreviewId(null);
    setSaveResults([]);
  }, [open]);

  const periodLabel = PERIODS.find(([value]) => value === period)?.[1] ?? period;
  const validDrafts = useMemo(
    () => drafts.filter((draft) => draft.request.trim()),
    [drafts],
  );

  const previewMutation = useMutation<BatchPreview[], Error, QueryDraft[]>({
    mutationFn: async (items) =>
      Promise.all(
        items.map(async (draft) => {
          const question = buildBatchQueryPrompt(
            draft,
            periodLabel,
            dimensionLabel,
            validateJoinCardinality,
          );
          try {
            const result = await aiActionsApi.generateQueryPreview(
              projectId,
              question,
              draft.name.trim() || undefined,
              draft.request.trim(),
            );
            return { draft, question, result };
          } catch (error) {
            return {
              draft,
              question,
              error: error instanceof Error ? error.message : "Query generation failed.",
            };
          }
        }),
      ),
    onSuccess: (items) => {
      setPreviews(items);
      const readyItems = items.filter(
        (item) => item.result?.status === "success",
      );
      setSelectedIds(
        new Set(readyItems.map((item) => item.draft.id)),
      );
      setExpandedPreviewId(items[0]?.draft.id ?? null);
      setStep("review");
    },
    onError: (error) => notify(error.message, "error"),
  });

  const saveMutation = useMutation<BatchSave[], Error, BatchPreview[]>({
    mutationFn: async (items) =>
      Promise.all(
        items.map(async (preview) => {
          if (!preview.result?.sql) {
            return { preview, error: "No validated SQL is available." };
          }
          try {
            const saved = await aiActionsApi.saveQuery(
              projectId,
              preview.result.title ||
                preview.draft.name.trim() ||
                preview.draft.request.trim().slice(0, 120),
              preview.result.sql,
              preview.result.description || preview.draft.request.trim(),
            );
            return { preview, queryId: saved.query_id };
          } catch (error) {
            return {
              preview,
              error: error instanceof Error ? error.message : "Query save failed.",
            };
          }
        }),
      ),
    onSuccess: (items) => {
      setSaveResults(items);
      setStep("create");
      const saved = items.filter((item) => item.queryId != null);
      saved.forEach((item) => onSaved?.(item.queryId!));
      if (saved.length) {
        notify(`Saved ${saved.length} ${saved.length === 1 ? "query" : "queries"}`, "success");
      }
      const failed = items.length - saved.length;
      if (failed) notify(`${failed} queries could not be saved`, "error");
    },
    onError: (error) => notify(error.message, "error"),
  });

  useEffect(() => {
    if (requirePreview || step !== "review" || previews.length === 0) return;
    const readyItems = previews.filter(
      (preview) => preview.result?.status === "success",
    );
    if (readyItems.length > 0) saveMutation.mutate(readyItems);
    // Run once when a newly generated batch enters review with preview disabled.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requirePreview, step, previews]);

  if (!open) return null;

  const updateDraft = (id: number, patch: Partial<QueryDraft>) => {
    setDrafts((current) =>
      current.map((draft) => (draft.id === id ? { ...draft, ...patch } : draft)),
    );
  };

  const addDraft = () => {
    const id = nextId.current++;
    setDrafts((current) => [...current, { id, ...EMPTY_DRAFT }]);
    setExpandedId(id);
  };

  const removeDraft = (id: number) => {
    setDrafts((current) => {
      const next = current.filter((draft) => draft.id !== id);
      if (expandedId === id) setExpandedId(next[0]?.id ?? 0);
      return next;
    });
  };

  const selectedPreviews = previews.filter(
    (preview) =>
      selectedIds.has(preview.draft.id) && preview.result?.status === "success",
  );

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/35 p-3 sm:p-5">
      <div className="mx-auto my-3 w-full max-w-6xl rounded-xl border border-line-tertiary bg-bg-primary shadow-xl">
        <header className="flex items-start justify-between gap-3 border-b border-line-tertiary px-4 py-4 sm:px-5">
          <div>
            <div className="flex items-center gap-2">
              <IconSparkles size={18} className="text-ai" />
              <h2 className="text-h2 text-ink-primary">Create queries with AI</h2>
              <span className="rounded-full bg-ai/10 px-2 py-0.5 text-[11px] font-medium text-ai">
                No configuration
              </span>
            </div>
            <p className="mt-1 text-small text-ink-tertiary">
              Describe the questions you need answered. Tablescope will design,
              validate, and save the complete query batch.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close AI query designer"
            className="shrink-0 rounded p-1 text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
          >
            <IconX size={18} />
          </button>
        </header>

        <div className="flex flex-wrap gap-2 border-b border-line-tertiary px-4 py-3 sm:px-5">
          {STEP_LABELS.map(([value, label]) => (
            <div
              key={value}
              className={`rounded-full border px-3 py-1.5 text-[12px] font-medium ${
                step === value
                  ? "border-brand-500 bg-brand-50 text-brand-700"
                  : "border-line-tertiary text-ink-tertiary"
              }`}
            >
              {label}
            </div>
          ))}
        </div>

        {step === "describe" && (
          <section className="p-4 sm:p-5">
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1.75fr)_minmax(280px,.65fr)]">
              <Card className="p-4">
                <div className="text-h3 text-ink-primary">Queries to generate</div>
                <p className="mt-1 text-small text-ink-tertiary">
                  Describe each outcome, then optionally add calculations,
                  grouping, filters, and sorting in plain language.
                </p>

                <div className="mt-3 space-y-2.5">
                  {drafts.map((draft, index) => {
                    const expanded = expandedId === draft.id;
                    const count = instructionCount(draft);
                    return (
                      <div key={draft.id} className="rounded-lg border border-line-tertiary bg-bg-primary">
                        <div className="flex items-center gap-2 px-3 py-2.5">
                          <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-brand-600 text-[11px] font-semibold text-white">
                            {index + 1}
                          </span>
                          <button
                            type="button"
                            onClick={() => setExpandedId(expanded ? 0 : draft.id)}
                            className="flex min-w-0 flex-1 items-center gap-2 text-left"
                          >
                            <span className="truncate text-[13px] font-semibold text-ink-primary">
                              {draft.name.trim() || `Untitled query ${index + 1}`}
                            </span>
                            {!expanded && count > 0 && (
                              <span className="rounded bg-bg-secondary px-1.5 py-0.5 text-[10px] text-ink-secondary">
                                {count} guided {count === 1 ? "instruction" : "instructions"}
                              </span>
                            )}
                          </button>
                          {drafts.length > 1 && (
                            <button
                              type="button"
                              aria-label={`Remove query ${index + 1}`}
                              onClick={() => removeDraft(draft.id)}
                              className="rounded p-1 text-ink-tertiary hover:bg-bg-secondary hover:text-danger"
                            >
                              <IconX size={14} />
                            </button>
                          )}
                          <button
                            type="button"
                            aria-label={expanded ? "Collapse query" : "Expand query"}
                            onClick={() => setExpandedId(expanded ? 0 : draft.id)}
                            className="rounded p-1 text-ink-tertiary hover:bg-bg-secondary"
                          >
                            {expanded ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
                          </button>
                        </div>

                        {expanded && (
                          <div className="border-t border-line-tertiary px-3 pb-3 pt-3">
                            <label className="text-[11px] font-medium text-ink-secondary">
                              Query name (optional)
                              <input
                                value={draft.name}
                                onChange={(event) => updateDraft(draft.id, { name: event.target.value })}
                                placeholder="Example: Monthly Backlog vs Monthly Revenue"
                                className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-2.5 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
                              />
                            </label>
                            <label className="mt-2.5 block text-[11px] font-medium text-ink-secondary">
                              Business request
                              <textarea
                                value={draft.request}
                                onChange={(event) => updateDraft(draft.id, { request: event.target.value })}
                                rows={2}
                                placeholder="Example: Join SalesOrders and OrderLines on sales_order_id. Compare open backlog with recognized revenue by month."
                                className="mt-1 w-full resize-y rounded-md border border-line-secondary bg-bg-primary p-2.5 text-[13px] leading-5 text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
                              />
                            </label>

                            <div className="mt-3 flex flex-wrap items-center gap-2">
                              <span className="text-[12px] font-semibold text-ink-primary">Optional query instructions</span>
                              <span className="rounded-full bg-ai/10 px-2 py-0.5 text-[10px] font-medium text-ai">Describe in plain language</span>
                              <span className="text-[11px] text-ink-tertiary">AI translates these instructions into governed SQL for review.</span>
                            </div>
                            <div className="mt-2 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                              {INSTRUCTION_FIELDS.map((field) => (
                                <InstructionCard
                                  key={field.key}
                                  draft={draft}
                                  field={field}
                                  onChange={(value) => updateDraft(draft.id, { [field.key]: value })}
                                />
                              ))}
                            </div>

                            <div className="mt-3 flex flex-wrap items-end gap-3 border-t border-line-tertiary pt-3">
                              <label className="text-[11px] font-medium text-ink-secondary">
                                Output
                                <select
                                  value={draft.output}
                                  onChange={(event) => updateDraft(draft.id, { output: event.target.value as QueryDraft["output"] })}
                                  className="mt-1 h-9 min-w-[150px] rounded-md border border-line-secondary bg-bg-primary px-2 text-[12px]"
                                >
                                  {OUTPUTS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                                </select>
                              </label>
                              <label className="text-[11px] font-medium text-ink-secondary">
                                Format
                                <select
                                  value={draft.format}
                                  onChange={(event) => updateDraft(draft.id, { format: event.target.value as QueryDraft["format"] })}
                                  className="mt-1 h-9 min-w-[130px] rounded-md border border-line-secondary bg-bg-primary px-2 text-[12px]"
                                >
                                  {FORMATS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                                </select>
                              </label>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                <Button size="sm" variant="secondary" className="mt-3" onClick={addDraft}>
                  <IconPlus size={14} />
                  Add another query
                </Button>
              </Card>

              <Card className="p-4">
                <h3 className="text-h3 text-ink-primary">Creation context</h3>
                <div className="mt-3 grid gap-3">
                  <label className="text-small font-medium text-ink-secondary">
                    Default period
                    <select
                      value={period}
                      onChange={(event) => setPeriod(event.target.value)}
                      className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-2 text-[12px]"
                    >
                      {PERIODS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </label>
                  <label className="text-small font-medium text-ink-secondary">
                    Primary dimension (optional)
                    <input
                      value={dimensionLabel}
                      onChange={(event) => setDimensionLabel(event.target.value)}
                      placeholder="Example: Site, Region, Team"
                      className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-2 text-[12px]"
                    />
                  </label>
                </div>
                <div className="mt-5 space-y-4 border-t border-line-tertiary pt-4">
                  <label className="flex items-start justify-between gap-3">
                    <span>
                      <span className="block text-small font-medium text-ink-secondary">Validate join cardinality</span>
                      <span className="mt-0.5 block text-[11px] leading-4 text-ink-tertiary">AI validates join paths and cardinality before saving.</span>
                    </span>
                    <input
                      type="checkbox"
                      checked={validateJoinCardinality}
                      onChange={(event) => setValidateJoinCardinality(event.target.checked)}
                      className="mt-1 h-4 w-4 accent-brand-600"
                    />
                  </label>
                  <label className="flex items-start justify-between gap-3">
                    <span>
                      <span className="block text-small font-medium text-ink-secondary">Require preview before save</span>
                      <span className="mt-0.5 block text-[11px] leading-4 text-ink-tertiary">Review each generated plan and result before queries are saved.</span>
                    </span>
                    <input
                      type="checkbox"
                      checked={requirePreview}
                      onChange={(event) => setRequirePreview(event.target.checked)}
                      className="mt-1 h-4 w-4 accent-brand-600"
                    />
                  </label>
                </div>
                <p className="mt-5 text-[11px] leading-4 text-ink-tertiary">
                  Tablescope profiles authorized project data, generates read-only SQL,
                  and preserves query lineage automatically.
                </p>
              </Card>
            </div>

            <div className="mt-4 flex justify-end">
              <Button
                variant="primary"
                disabled={validDrafts.length === 0 || previewMutation.isPending}
                onClick={() => previewMutation.mutate(validDrafts)}
              >
                <IconSparkles size={14} />
                {previewMutation.isPending
                  ? `Analyzing ${validDrafts.length} ${validDrafts.length === 1 ? "query" : "queries"}…`
                  : "Analyze data & propose queries"}
              </Button>
            </div>
          </section>
        )}

        {step === "review" && (
          <section className="p-4 sm:p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-h3 text-ink-primary">Review query batch</h3>
                <p className="mt-1 text-small text-ink-tertiary">Review generated SQL and sample results. Failed queries do not block ready queries.</p>
              </div>
              <button
                type="button"
                className="text-[12px] font-medium text-brand-600 hover:text-brand-700"
                onClick={() => setSelectedIds(new Set(previews.filter((preview) => preview.result?.status === "success").map((preview) => preview.draft.id)))}
              >
                Select all ready
              </button>
            </div>

            <div className="mt-4 space-y-2.5">
              {previews.map((preview, index) => {
                const expanded = expandedPreviewId === preview.draft.id;
                const ready = preview.result?.status === "success";
                const rows = preview.result?.rows ?? [];
                const columns = preview.result?.columns ?? [];
                return (
                  <Card key={preview.draft.id} className="overflow-hidden">
                    <div className="flex items-center gap-3 p-3">
                      <input
                        type="checkbox"
                        aria-label={`Select ${preview.result?.title || preview.draft.name || `query ${index + 1}`}`}
                        checked={selectedIds.has(preview.draft.id)}
                        disabled={!ready}
                        onChange={(event) => {
                          setSelectedIds((current) => {
                            const next = new Set(current);
                            if (event.target.checked) next.add(preview.draft.id);
                            else next.delete(preview.draft.id);
                            return next;
                          });
                        }}
                        className="h-4 w-4 accent-brand-600"
                      />
                      <button
                        type="button"
                        onClick={() => setExpandedPreviewId(expanded ? null : preview.draft.id)}
                        className="flex min-w-0 flex-1 items-center gap-2 text-left"
                      >
                        <span className="truncate text-[13px] font-semibold text-ink-primary">
                          {preview.result?.title || preview.draft.name || `Query ${index + 1}`}
                        </span>
                        <StatusBadge preview={preview} />
                        {ready && <span className="text-[11px] text-ink-tertiary">{rows.length} preview {rows.length === 1 ? "row" : "rows"}</span>}
                      </button>
                      <button
                        type="button"
                        aria-label={expanded ? "Collapse query plan" : "Expand query plan"}
                        onClick={() => setExpandedPreviewId(expanded ? null : preview.draft.id)}
                        className="rounded p-1 text-ink-tertiary hover:bg-bg-secondary"
                      >
                        {expanded ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
                      </button>
                    </div>

                    {expanded && (
                      <div className="border-t border-line-tertiary bg-bg-secondary/40 p-3">
                        {(preview.error || preview.result?.error) && (
                          <div className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger-bg p-2.5 text-[12px] text-danger">
                            <IconAlertTriangle size={15} className="mt-0.5 shrink-0" />
                            <span>{preview.error || preview.result?.error}</span>
                          </div>
                        )}
                        {ready && (
                          <>
                            <div className="grid gap-3 lg:grid-cols-2">
                              <div>
                                <div className="text-[11px] font-semibold text-ink-secondary">AI plan</div>
                                <p className="mt-1 text-[12px] leading-5 text-ink-secondary">{preview.result?.description || preview.draft.request}</p>
                                {(preview.result?.dataSourcesUsed ?? []).length > 0 && (
                                  <div className="mt-2 text-[11px] text-ink-tertiary">Sources: {preview.result?.dataSourcesUsed.filter(Boolean).join(", ")}</div>
                                )}
                              </div>
                              <div>
                                <div className="text-[11px] font-semibold text-ink-secondary">Validated SQL</div>
                                <pre className="mt-1 max-h-32 overflow-auto rounded-md bg-bg-secondary p-2 text-[11px] leading-4 text-ink-primary">{preview.result?.sql}</pre>
                              </div>
                            </div>
                            {columns.length > 0 && rows.length > 0 && (
                              <div className="mt-3 overflow-x-auto rounded-md border border-line-tertiary bg-bg-primary">
                                <table className="w-full text-left text-[11px]">
                                  <thead className="bg-bg-secondary text-ink-secondary">
                                    <tr>{columns.map((column) => <th key={column} className="whitespace-nowrap px-2 py-1.5 font-semibold">{column}</th>)}</tr>
                                  </thead>
                                  <tbody>
                                    {rows.slice(0, 5).map((row, rowIndex) => (
                                      <tr key={rowIndex} className="border-t border-line-tertiary">
                                        {columns.map((column) => <td key={column} className="max-w-[220px] truncate px-2 py-1.5 text-ink-secondary">{String(row[column] ?? "")}</td>)}
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </Card>
                );
              })}
            </div>

            <div className="mt-5 flex flex-wrap justify-end gap-2 border-t border-line-tertiary pt-4">
              <Button variant="secondary" onClick={() => setStep("describe")}>Back</Button>
              <Button
                variant="primary"
                disabled={selectedPreviews.length === 0 || saveMutation.isPending}
                onClick={() => saveMutation.mutate(selectedPreviews)}
              >
                <IconCheck size={15} />
                {saveMutation.isPending
                  ? "Saving selected queries…"
                  : `Validate & create ${selectedPreviews.length} selected ${selectedPreviews.length === 1 ? "query" : "queries"}`}
              </Button>
            </div>
          </section>
        )}

        {step === "create" && (
          <section className="p-4 sm:p-5">
            <div className="mx-auto max-w-3xl">
              <h3 className="text-h3 text-ink-primary">Query batch complete</h3>
              <p className="mt-1 text-small text-ink-tertiary">Each query was saved independently so a failed item never rolls back successful queries.</p>
              <div className="mt-4 space-y-2">
                {saveResults.map((item, index) => (
                  <div key={item.preview.draft.id} className="flex items-start gap-3 rounded-lg border border-line-tertiary p-3">
                    {item.queryId != null ? (
                      <IconCheck size={18} className="mt-0.5 shrink-0 text-success" />
                    ) : (
                      <IconAlertTriangle size={18} className="mt-0.5 shrink-0 text-danger" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-semibold text-ink-primary">{item.preview.result?.title || item.preview.draft.name || `Query ${index + 1}`}</div>
                      <div className="mt-0.5 text-[12px] text-ink-tertiary">{item.queryId != null ? `Saved as query #${item.queryId}` : item.error}</div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-5 flex justify-end"><Button variant="primary" onClick={onClose}>Done</Button></div>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
