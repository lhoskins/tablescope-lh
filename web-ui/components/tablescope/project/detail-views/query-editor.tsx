"use client";


import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  IconArrowLeft,
  IconFileText,
  IconDatabase,
  IconPencil,
  IconX,
} from "@tabler/icons-react";
import { DataGrid } from "@/components/data-grid/DataGrid";
import { TanStackDataGrid } from "@/components/data-grid/TanStackDataGrid";
import { DashboardViewer } from "@/components/dashboard/DashboardViewer";
import { QueryBuilder } from "@/components/query-builder/QueryBuilder";
import type { Dashboard as ViewerDashboard, WidgetConfig } from "@/components/dashboard/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiClient } from "@/lib/api-client";
import { timeAgo } from "@/lib/ui/format";
import {
  columnLabel,
  useProjectQueries,
  type SavedQuery,
  type DataSource,
  type Dashboard,
  type ProjectAsset,
} from "@/lib/ui/use-project-data";


// ── Editable query preview (right rail) ──────────────────────────────

export function QueryEditor({
  projectId,
  query,
  onClose,
}: {
  projectId: string;
  query: SavedQuery;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(query.name);
  const [sql, setSql] = useState(query.sql_text ?? "");
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () =>
      apiClient.put(`/api/projects/${projectId}/queries/${query.id}`, {
        name,
        sql_text: sql,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "queries"],
      });
      setError(null);
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div className="space-y-2">
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="h-8 w-full rounded-md border border-line-secondary bg-bg-primary px-2.5 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
      />
      <textarea
        value={sql}
        onChange={(e) => setSql(e.target.value)}
        rows={8}
        spellCheck={false}
        className="w-full resize-y rounded-lg border border-line-secondary bg-[#1e1b2e] p-3 font-code text-[12px] leading-relaxed text-[#d6d3e8] focus:border-brand-500 focus:outline-none"
      />
      {error && <p className="text-small text-danger">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button variant="secondary" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={() => save.mutate()}
          disabled={save.isPending || !name.trim()}
        >
          {save.isPending ? "Saving…" : "Save"}
        </Button>
      </div>
    </div>
  );
}