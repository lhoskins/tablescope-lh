"use client";

import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { IconChevronRight, IconPlus, IconSparkles } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { scopesApi, type ScopeSet } from "@/lib/api/scopes";

function subtitleFor(s: ScopeSet): string {
  if (s.type === "ai_generated") {
    return `${s.scope_count} suggested mapping${s.scope_count === 1 ? "" : "s"}`;
  }
  if (s.scope_count === 0) return "Empty scope map";
  return `${s.scope_count} field mapping${s.scope_count === 1 ? "" : "s"} · saved scope map`;
}

export function ScopeNavigation({ projectId }: { projectId: number }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const queryKey = ["project", projectId, "scope_sets"];

  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: () => scopesApi.listScopeSets(projectId),
  });

  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      scopesApi.updateScopeSet(id, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });

  const scopeSets = data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-[15px] font-semibold text-ink-primary">
            Query Scopes
          </h2>
          <p className="mt-1 max-w-2xl text-[12.5px] text-ink-secondary">
            Drill-down relationships between saved queries. Click a scoped cell
            in a query result to drill into the target query filtered by that
            value.
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
        <ul className="space-y-2">
          {scopeSets.map((s) => (
            <li key={s.id}>
              <div
                role="button"
                tabIndex={0}
                onClick={() =>
                  router.push(`/projects/${projectId}/scopes/${s.id}/map`)
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    router.push(`/projects/${projectId}/scopes/${s.id}/map`);
                  }
                }}
                className={cn(
                  "flex cursor-pointer items-center justify-between gap-4 rounded-lg border border-line-tertiary bg-bg-primary px-4 py-3 transition-colors hover:border-line-secondary hover:bg-bg-secondary/40",
                  !s.enabled && "opacity-60",
                )}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <IconChevronRight
                    size={16}
                    className="shrink-0 text-ink-tertiary"
                  />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[13.5px] font-medium text-ink-primary">
                        {s.name}
                      </span>
                      {s.type === "ai_generated" && (
                        <Badge tone="ai" className="gap-1">
                          <IconSparkles size={11} />
                          AI
                        </Badge>
                      )}
                    </div>
                    <p className="truncate text-[12px] text-ink-secondary">
                      {subtitleFor(s)}
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  title={s.enabled ? "Disable scope set" : "Enable scope set"}
                  onClick={(e) => {
                    e.stopPropagation();
                    toggle.mutate({ id: s.id, enabled: !s.enabled });
                  }}
                  disabled={toggle.isPending}
                  className="shrink-0"
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
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
