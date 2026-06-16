"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import {
  IconAlertTriangle,
  IconCircleCheck,
  IconLoader2,
  IconMinus,
  IconPlus,
  IconX,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { applyChanges, type ApplyResult } from "@/lib/api/data-source-builder";

export function ConfirmationModal({
  open,
  tenantName,
  onClose,
}: {
  open: boolean;
  tenantName: string;
  onClose: () => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const getPendingChanges = useBuilderStore((s) => s.getPendingChanges);
  const reset = useBuilderStore((s) => s.reset);

  const [applying, setApplying] = useState(false);
  const [result, setResult] = useState<ApplyResult | null>(null);

  if (!open) return null;

  const pending = getPendingChanges();

  const run = async (mode: "all" | "remove-only") => {
    setApplying(true);
    try {
      const res = await applyChanges(pending, { mode });
      setResult(res);
      void queryClient.invalidateQueries({ queryKey: ["builder"] });
      void queryClient.invalidateQueries({ queryKey: ["home"] });
    } finally {
      setApplying(false);
    }
  };

  const allOk = result && result.failed === 0;
  const hasFailures = result && result.failed > 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={applying ? undefined : onClose}
    >
      <div
        className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-bg-primary p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {!result ? (
          <>
            <div className="mb-4 flex items-start gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-success-bg text-success">
                <IconCircleCheck size={20} />
              </span>
              <div className="flex-1">
                <h2 className="text-h2 text-ink-primary">
                  Review changes before applying
                </h2>
                <p className="text-small text-ink-tertiary">
                  Nothing is committed until you confirm. All events are logged
                  to your Audit Log.
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="flex h-7 w-7 items-center justify-center rounded text-ink-tertiary hover:bg-bg-secondary"
              >
                <IconX size={16} />
              </button>
            </div>

            {/* ADDING */}
            {pending.adding.length > 0 && (
              <div className="mb-4">
                <p className="mb-2 text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
                  Adding
                </p>
                <div className="space-y-1.5">
                  {pending.adding.map((a, i) => (
                    <div
                      key={`${a.source.id}-${a.projectId}-${i}`}
                      className="flex items-center gap-3 rounded-md border border-brand-500/30 bg-brand-50/30 px-3 py-2"
                    >
                      <IconPlus size={15} className="shrink-0 text-brand-700" />
                      <div className="min-w-0 flex-1">
                        <p className="text-[13px] font-medium text-ink-primary">
                          {a.source.displayName} ·{" "}
                          {a.source.isFileUpload
                            ? `1 file · ${a.source.fileMetadata?.rows ?? 0} rows`
                            : `${a.tableNames.length} tables · AI profiling on`}
                        </p>
                        <p className="truncate text-caption text-ink-tertiary">
                          {a.tableNames.join(", ")}
                        </p>
                      </div>
                      <span className="rounded-full bg-brand-500 px-2 py-0.5 text-[11px] font-medium text-white">
                        {a.projectName}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* REMOVING */}
            {pending.removing.length > 0 && (
              <div className="mb-4">
                <p className="mb-2 text-caption font-semibold uppercase tracking-wide text-danger">
                  Removing
                </p>
                <div className="space-y-1.5">
                  {pending.removing.map((r, i) => (
                    <div
                      key={`${r.source.sourceKey}-${r.projectId}-${i}`}
                      className="flex items-center gap-3 rounded-md border border-danger/30 bg-danger-bg/30 px-3 py-2"
                    >
                      <IconMinus size={15} className="shrink-0 text-danger" />
                      <div className="min-w-0 flex-1">
                        <p className="text-[13px] font-medium text-ink-primary">
                          {r.source.name} · {r.source.tableCount} tables will be
                          disconnected
                        </p>
                        <p className="flex items-center gap-1 text-caption text-danger">
                          <IconAlertTriangle size={12} />
                          Queries and dashboards using this may need review.
                        </p>
                      </div>
                      <span className="rounded-full bg-danger px-2 py-0.5 text-[11px] font-medium text-white">
                        {r.projectName}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <p className="mb-4 text-caption text-ink-tertiary">
              All changes immutably logged · Tenant: {tenantName} · AI profiling
              runs shortly after commit
            </p>

            <div className="flex items-center justify-between gap-3">
              <p className="max-w-xs text-caption text-ink-tertiary">
                Scoped to your tenant only. Changes are reversible from the Audit
                Log.
              </p>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={onClose} disabled={applying}>
                  Back
                </Button>
                {pending.removing.length > 0 && (
                  <Button
                    variant="danger"
                    onClick={() => run("remove-only")}
                    disabled={applying}
                  >
                    {applying && (
                      <IconLoader2 size={14} className="animate-spin" />
                    )}
                    Remove only
                  </Button>
                )}
                <Button
                  variant="primary"
                  onClick={() => run("all")}
                  disabled={applying}
                >
                  {applying && <IconLoader2 size={14} className="animate-spin" />}
                  Confirm &amp; apply all
                </Button>
              </div>
            </div>
          </>
        ) : (
          <div>
            {allOk ? (
              <div className="flex flex-col items-center gap-3 py-6 text-center">
                <span className="flex h-14 w-14 items-center justify-center rounded-full bg-success-bg text-success">
                  <IconCircleCheck size={32} />
                </span>
                <h2 className="text-h2 text-ink-primary">
                  All changes applied successfully
                </h2>
                <p className="text-small text-ink-tertiary">
                  {result.succeeded} operations completed · AI profiling in
                  progress
                </p>
                <div className="mt-3 flex gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => {
                      reset();
                      router.push("/data-sources");
                    }}
                  >
                    Go to Data Sources
                  </Button>
                  <Button
                    variant="primary"
                    onClick={() => {
                      reset();
                      setResult(null);
                      onClose();
                    }}
                  >
                    Start new session
                  </Button>
                </div>
              </div>
            ) : (
              <div>
                <h2 className="mb-1 text-h2 text-ink-primary">
                  Some changes need attention
                </h2>
                <p className="mb-4 text-small text-ink-tertiary">
                  {result.succeeded} succeeded · {result.failed} failed. Nothing
                  else was changed.
                </p>
                <div className="mb-4 space-y-1.5">
                  {result.results.map((op, i) => (
                    <div
                      key={i}
                      className="flex items-start gap-2 rounded-md border border-line-tertiary px-3 py-2 text-[12px]"
                    >
                      {op.ok ? (
                        <IconCircleCheck
                          size={15}
                          className="mt-0.5 shrink-0 text-success"
                        />
                      ) : (
                        <IconX
                          size={15}
                          className="mt-0.5 shrink-0 text-danger"
                        />
                      )}
                      <div className="min-w-0">
                        <p className="text-ink-primary">{op.label}</p>
                        {op.error && (
                          <p className="text-danger">{op.error}</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="flex justify-end gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setResult(null);
                      onClose();
                    }}
                  >
                    Skip &amp; finish
                  </Button>
                  <Button
                    variant="primary"
                    onClick={() => run("all")}
                    disabled={applying}
                  >
                    {applying && (
                      <IconLoader2 size={14} className="animate-spin" />
                    )}
                    Retry failed
                  </Button>
                </div>
              </div>
            )}
            {hasFailures ? null : null}
          </div>
        )}
      </div>
    </div>
  );
}
