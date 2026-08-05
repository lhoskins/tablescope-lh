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
} from "@/lib/ui/use-project-data";import { DetailBackBar } from "./detail-back-bar";
import { AITag } from "./aitag";
import { AIEntity } from "./aientity";
import { AIKpi } from "./aikpi";
import { DocFamily } from "./doc-family";
import { humanSize } from "./human-size";
import { MetaSection } from "./meta-section";



export function DocumentDetailView({
  asset,
  backLabel,
  onBack,
}: {
  asset: ProjectAsset;
  backLabel: string;
  onBack: () => void;
}) {
  const meta = (asset.ai_metadata ?? {}) as Record<string, unknown>;
  const tags = (meta.tags ?? []) as AITag[];
  const entities = (meta.entities ?? []) as AIEntity[];
  const kpis = (meta.recommended_kpis ?? []) as AIKpi[];
  const questions = (meta.suggested_questions ?? []) as string[];
  const domain = typeof meta.business_domain === "string" ? meta.business_domain : null;
  const docType = typeof meta.document_type === "string" ? meta.document_type : null;
  const family = (meta.document_family ?? null) as DocFamily | null;
  const type =
    asset.file_extension?.replace(".", "").toUpperCase() ||
    asset.asset_type.toUpperCase();

  return (
    <div className="space-y-4">
      <DetailBackBar label={backLabel} onBack={onBack} />

      <header className="flex items-start gap-2.5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-bg-secondary text-ink-tertiary">
          <IconFileText size={18} />
        </span>
        <div className="min-w-0">
          <h1 className="text-h1 text-ink-primary">{asset.title}</h1>
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-small text-ink-tertiary">
            <Badge tone="neutral">{type}</Badge>
            <span>{humanSize(asset.file_size_bytes)}</span>
            <span>· Uploaded {timeAgo(asset.created_at)}</span>
          </p>
        </div>
      </header>

      {asset.ai_summary && (
        <Card className="space-y-1.5 p-4">
          <MetaSection title="AI Summary">
            <p className="text-[13px] leading-relaxed text-ink-primary">
              {asset.ai_summary}
            </p>
          </MetaSection>
        </Card>
      )}

      {family && (
        <Card className="space-y-1 p-4">
          <MetaSection title="Document Family">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[13px] font-medium text-ink-primary">
                {family.family_name}
              </span>
              {family.auto_link != null && (
                <Badge tone={family.auto_link ? "success" : "warning"}>
                  {family.auto_link ? "Linked" : "Suggested"}
                </Badge>
              )}
              {family.confidence != null && (
                <span className="text-small text-ink-tertiary">
                  {Math.round(family.confidence * 100)}%
                </span>
              )}
            </div>
            {(family.family_type || family.role) && (
              <p className="mt-1 text-small text-ink-tertiary">
                {[family.family_type, family.role]
                  .filter((v) => v && v !== "unknown")
                  .map((v) => v!.replace(/_/g, " "))
                  .join(" · ")}
              </p>
            )}
            {family.reason && (
              <p className="mt-1 text-small text-ink-tertiary">{family.reason}</p>
            )}
          </MetaSection>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {(docType || domain) && (
          <Card className="space-y-2 p-4">
            {docType && (
              <MetaSection title="Document Type">
                <p className="text-[13px] text-ink-primary">{docType}</p>
              </MetaSection>
            )}
            {domain && (
              <MetaSection title="Business Domain">
                <p className="text-[13px] text-ink-primary">{domain}</p>
              </MetaSection>
            )}
          </Card>
        )}

        {tags.length > 0 && (
          <Card className="p-4">
            <MetaSection title="Tags">
              <div className="flex flex-wrap gap-1.5">
                {tags.map((t, i) => (
                  <Badge key={i} tone="outline">
                    {t.display_name ?? t.tag_key}
                  </Badge>
                ))}
              </div>
            </MetaSection>
          </Card>
        )}

        {kpis.length > 0 && (
          <Card className="p-4">
            <MetaSection title="Recommended KPIs">
              <ul className="space-y-1 text-[13px] text-ink-secondary">
                {kpis.map((k, i) => (
                  <li key={i}>
                    <span className="text-ink-primary">
                      {k.display_name ?? k.kpi_key}
                    </span>
                    {k.reason && (
                      <span className="text-ink-tertiary"> — {k.reason}</span>
                    )}
                  </li>
                ))}
              </ul>
            </MetaSection>
          </Card>
        )}

        {entities.length > 0 && (
          <Card className="p-4">
            <MetaSection title="Entities">
              <ul className="space-y-1 text-[13px] text-ink-secondary">
                {entities.map((e, i) => (
                  <li key={i} className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-bg-secondary px-1.5 py-0.5 text-small font-medium text-ink-tertiary">
                      {e.entity_type}
                    </span>
                    <span className="text-ink-primary">{e.name}</span>
                  </li>
                ))}
              </ul>
            </MetaSection>
          </Card>
        )}
      </div>

      {questions.length > 0 && (
        <Card className="p-4">
          <MetaSection title="Suggested Questions">
            <ul className="space-y-1 text-[13px] text-ink-secondary">
              {questions.map((q, i) => (
                <li key={i} className="flex items-start gap-1.5">
                  <span className="text-ink-tertiary">•</span>
                  {q}
                </li>
              ))}
            </ul>
          </MetaSection>
        </Card>
      )}
    </div>
  );
}