"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api-client";
import { updateProject } from "@/lib/ui/use-shell-data";
import type { ToastTone } from "@/components/ui/toast";

/**
 * Compact Private/Shared switch for the project overview action bar. Reflects
 * the current `is_shared` state and persists via PUT /projects/:id.
 */
export function ShareToggle({
  projectId,
  shared,
  onToast,
}: {
  projectId: string;
  shared: boolean;
  onToast: (message: string, tone: ToastTone) => void;
}) {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (next: boolean) => updateProject(projectId, { is_shared: next }),
    onSuccess: async (_data, next) => {
      onToast(
        next ? "Project sharing enabled." : "Project sharing disabled.",
        "success",
      );
      await queryClient.invalidateQueries({ queryKey: ["projects", "summaries"] });
    },
    onError: (err: unknown) => {
      const status = err instanceof ApiError ? err.status : 0;
      if (status === 403) {
        onToast("Only the project owner or an admin can change sharing.", "error");
      } else {
        onToast("Could not update project sharing. Please try again.", "error");
      }
    },
  });

  const label = shared ? "Shared" : "Private";

  return (
    <div className="flex items-center gap-2 rounded-md border border-line-secondary bg-bg-primary px-2.5 h-8">
      <span className="text-[13px] font-medium text-ink-secondary">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={shared}
        aria-label={`Toggle project sharing (currently ${label})`}
        disabled={mutation.isPending}
        onClick={() => mutation.mutate(!shared)}
        className={`relative inline-flex h-4 w-7 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${
          shared ? "bg-brand" : "bg-line-secondary"
        }`}
      >
        <span
          className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
            shared ? "translate-x-3.5" : "translate-x-0.5"
          }`}
        />
      </button>
    </div>
  );
}
