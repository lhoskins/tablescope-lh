"use client";


import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  IconSparkles,
  IconSearch,
  IconTarget,
  IconPlus,
  IconArchive,
  IconArrowBackUp,
  IconTrash,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import {
  ContextPanel,
  ContextSection,
} from "@/components/tablescope/context-panel";
import { AddDatasourceModal } from "@/components/datasource/AddDatasourceModal";
import { StatTile } from "@/components/ui/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { apiClient } from "@/lib/api-client";
import { timeAgo } from "@/lib/ui/format";
import {
  useProjectQueries,
  useProjectArchivedQueries,
  useProjectDataSources,
  type SavedQuery,
} from "@/lib/ui/use-project-data";
import {
  QueryResultView,
  QueryBuilderEdit,
  QueryBuilderCreate,
} from "@/components/tablescope/project/detail-views";import { runtimeLabel } from "./runtime-label";
import { tablesFor } from "./tables-for";
import { Row } from "./row";



export function QueryPreviewPanel({
  query,
  collapsible = true,
}: {
  query: SavedQuery | null;
  collapsible?: boolean;
}) {
  if (!query) {
    return (
      <ContextPanel title="Query Preview" askPlaceholder="Ask about this query…" collapsible={collapsible}>
        <div className="px-1 py-8 text-center text-small text-ink-tertiary">
          Select a query to preview its SQL and metadata.
        </div>
      </ContextPanel>
    );
  }
  return (
    <ContextPanel title="Query Preview" askPlaceholder="Ask about this query…">
      <div className="space-y-1">
        <div className="min-w-0 truncate text-caption uppercase tracking-wide text-ink-tertiary">
          {query.name}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {query.ai_generated && <Badge tone="ai">AI generated</Badge>}
          {query.is_shared && <Badge tone="success">Shared</Badge>}
          <span className="text-small text-ink-tertiary">
            {query.left_datasource ?? "—"} · {query.run_count} runs
          </span>
        </div>
      </div>

      {query.sql_text && (
        <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-lg bg-[#1e1b2e] p-3 font-code text-[12px] leading-relaxed text-[#d6d3e8]">
          {query.sql_text}
        </pre>
      )}

      <ContextSection title="Query Metadata">
        <dl className="space-y-1 text-[13px]">
          <Row label="Source" value={query.left_datasource ?? "—"} />
          <Row label="Tables" value={tablesFor(query)} />
          <Row label="Avg runtime" value={runtimeLabel(query.avg_runtime_ms)} />
          <Row
            label="Last run"
            value={query.last_run_at ? timeAgo(query.last_run_at) : "—"}
          />
          <Row
            label="Created"
            value={`${query.ai_generated ? "AI · " : ""}${timeAgo(query.created_at)}`}
          />
        </dl>
      </ContextSection>
    </ContextPanel>
  );
}