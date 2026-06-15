"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api-client";

export function NewProjectDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isShared, setIsShared] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: (payload: {
      name: string;
      description: string;
      is_shared: boolean;
    }) => apiClient.post<{ id: number }>("/api/projects", payload),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setName("");
      setDescription("");
      setIsShared(false);
      setError(null);
      onClose();
      router.push(`/projects/${created.id}`);
    },
    onError: (err: Error) => setError(err.message),
  });

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="w-full max-w-md rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg">
        <h2 className="text-h2 text-ink-primary">New project</h2>
        <form
          className="mt-4 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            createMutation.mutate({ name, description, is_shared: isShared });
          }}
        >
          <div>
            <label className="mb-1 block text-small font-medium text-ink-secondary">
              Project name
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              autoFocus
              placeholder="Supply Chain Q3"
              className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-small font-medium text-ink-secondary">
              Description
            </label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional"
              className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
            />
          </div>
          <label className="flex items-center gap-2 text-[13px] text-ink-secondary">
            <input
              type="checkbox"
              checked={isShared}
              onChange={(e) => setIsShared(e.target.checked)}
            />
            Shared with the team
          </label>

          {error && <p className="text-small text-red-600">{error}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="secondary" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              type="submit"
              disabled={createMutation.isPending || !name.trim()}
            >
              {createMutation.isPending ? "Creating…" : "Create project"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
