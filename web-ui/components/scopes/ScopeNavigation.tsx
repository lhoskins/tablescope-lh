"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { IconPlus, IconSparkles, IconTrash } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format-datetime";
import { scopesApi, type ScopeSet } from "@/lib/api/scopes";

function mappingsLabel(s: ScopeSet): string {
  if (s.scope_count === 0) {
    return s.type === "ai_generated" ? "No suggestions" : "Empty";
  }
  const noun = s.type === "ai_generated" ? "suggested mapping" : "field mapping";
  return `${s.scope_count} ${noun}${s.scope_count === 1 ? "" : "s"}`;
}

function creatorLabel(s: ScopeSet): string {
  return s.creator_name || s.creator_email || "—";
}

export function ScopeNavigation({ projectId }: { projectId: number }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const queryKey = ["project", projectId, "scope_sets"];
  const [pendingDelete, setPendingDelete] = useState<ScopeSet | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: () => scopesApi.listScopeSets(projectId),
  });

  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      scopesApi.updateScopeSet(id, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });

  const remove = useMutation({
    mutationFn: (id: number) => scopesApi.deleteScopeSet(id),
    onSuccess: () => {
      setPendingDelete(null);
      queryClient.invalidateQueries({ queryKey });
    },
  });

  const scopeSets = data ?? [];

  const open = (id: number) =>
    router.push(`/projects/${projectId}/scopes/${id}/map`);

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-[15px] font-semibold text-ink-primary">
            Query Scopes
          </h2>
          <p className="mt-1 max-w-2xl text-[12.5px] text-ink-secondary">
            Drill-down relationships between saved queries. Each scope can be
            enabled or disabled independently. Click a scoped cell in a query
            result to drill into the target query filtered by that value.
          </p>
        </div>
        <Button
          variant="primary"
          onClick={() => router.push(`/projects/${projectId}/scopes/new`)}
        >
          <IconPlus size={14} />
          Create Scope
        </Button>
      </div>

      {isLoading ? (
        <p className="text-[13px] text-ink-tertiary">Loading scopes…</p>
      ) : error ? (
        <p className="text-[13px] text-danger">
          {(error as Error).message || "Failed to load scopes"}
        </p>
      ) : scopeSets.length === 0 ? (
        <div className="rounded-lg border border-dashed border-line-secondary bg-bg-secondary/40 p-8 text-center">
          <p className="text-[13px] font-medium text-ink-primary">
            No scope sets yet
          </p>
          <p className="mt-1 text-[12.5px] text-ink-secondary">
            Create a scope to visually map fields between your queries.
          </p>
          <div className="mt-3 flex justify-center">
            <Button
              variant="secondary"
              onClick={() => router.push(`/projects/${projectId}/scopes/new`)}
            >
              <IconPlus size={14} />
              Create Scope
            </Button>
          </div>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-line-tertiary">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-line-tertiary bg-bg-secondary/40 text-left text-caption uppercase tracking-wide text-ink-tertiary">
                <th className="px-4 py-2 font-medium">Scope</th>
                <th className="px-4 py-2 font-medium">Mappings</th>
                <th className="px-4 py-2 font-medium">Created by</th>
                <th className="px-4 py-2 font-medium">Created date</th>
                <th className="px-4 py-2 font-medium">Enabled</th>
                <th className="px-4 py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {scopeSets.map((s) => (
                <tr
                  key={s.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => open(s.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      open(s.id);
                    }
                  }}
                  className={cn(
                    "cursor-pointer border-b border-line-tertiary last:border-0 transition-colors hover:bg-bg-secondary/40",
                    !s.enabled && "opacity-60",
                  )}
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-ink-primary">
                        {s.name}
                      </span>
                      {s.type === "ai_generated" && (
                        <Badge tone="ai" className="gap-1">
                          <IconSparkles size={11} />
                          AI
                        </Badge>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-ink-secondary">
                    {mappingsLabel(s)}
                  </td>
                  <td className="px-4 py-3 text-ink-secondary">
                    {creatorLabel(s)}
                  </td>
                  <td className="px-4 py-3 text-ink-secondary">
                    {formatDateTime(s.created_at) ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      title={s.enabled ? "Disable scope" : "Enable scope"}
                      aria-label={s.enabled ? "Disable scope" : "Enable scope"}
                      onClick={(e) => {
                        e.stopPropagation();
                        toggle.mutate({ id: s.id, enabled: !s.enabled });
                      }}
                      disabled={toggle.isPending}
                    >
                      <span
                        className={cn(
                          "relative inline-flex h-5 w-9 items-center rounded-full transition-colors",
                          s.enabled ? "bg-brand-500" : "bg-line-secondary",
                        )}
                      >
                        <span
                          className="inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform"
                          style={{
                            transform: s.enabled
                              ? "translateX(18px)"
                              : "translateX(3px)",
                          }}
                        />
                      </span>
                    </button>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {s.can_delete && (
                      <button
                        type="button"
                        title="Delete scope"
                        aria-label="Delete scope"
                        onClick={(e) => {
                          e.stopPropagation();
                          setPendingDelete(s);
                        }}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ink-tertiary hover:bg-danger/10 hover:text-danger"
                      >
                        <IconTrash size={15} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {pendingDelete && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          role="dialog"
          aria-modal="true"
          onClick={() => !remove.isPending && setPendingDelete(null)}
        >
          <div
            className="w-full max-w-md rounded-lg border border-line-secondary bg-bg-primary p-5 shadow-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-[14px] font-semibold text-ink-primary">
              Delete scope
            </h3>
            <p className="mt-2 text-[13px] text-ink-secondary">
              Delete <span className="font-medium">{pendingDelete.name}</span>?
              This removes its field mappings and relationship map. This cannot
              be undone.
            </p>
            {remove.isError && (
              <p className="mt-2 text-[12.5px] text-danger">
                {(remove.error as Error).message || "Failed to delete scope"}
              </p>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <Button
                variant="secondary"
                onClick={() => setPendingDelete(null)}
                disabled={remove.isPending}
              >
                Cancel
              </Button>
              <Button
                variant="danger"
                onClick={() => remove.mutate(pendingDelete.id)}
                disabled={remove.isPending}
              >
                {remove.isPending ? "Deleting…" : "Delete scope"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
