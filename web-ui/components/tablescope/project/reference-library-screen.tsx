"use client";

import { useCallback, useEffect, useState } from "react";
import { IconPlus, IconSparkles } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { StatTile } from "@/components/ui/stat-tile";
import { cn } from "@/lib/cn";
import { ReferenceUploadModal } from "@/components/tablescope/reference-library/upload-modal";
import { DocumentTable } from "@/components/tablescope/reference-library/document-table";
import {
  referenceLibraryApi,
  type ProjectLibrary,
  type ReferenceDocument,
  type ReferenceMeta,
} from "@/lib/api/reference-library";

type Tab = "inherited" | "suggested" | "projectUnique";

export function ProjectReferenceLibraryPanel({ projectId }: { projectId: string }) {
  const pid = Number(projectId);
  const [meta, setMeta] = useState<ReferenceMeta | null>(null);
  const [data, setData] = useState<ProjectLibrary | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("inherited");
  const [showUpload, setShowUpload] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    referenceLibraryApi.meta().then(setMeta).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await referenceLibraryApi.projectLibrary(pid));
    } finally {
      setLoading(false);
    }
  }, [pid]);

  useEffect(() => {
    void load();
  }, [load]);

  async function generate() {
    setGenerating(true);
    setNotice(null);
    try {
      const res = await referenceLibraryApi.generateSuggestions(pid);
      setNotice(
        res.created > 0
          ? `${res.created} new suggestion${res.created === 1 ? "" : "s"} added.`
          : "No new suggestions — your project scope already covers the relevant standards.",
      );
      setTab("suggested");
      await load();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Suggestion generation failed");
    } finally {
      setGenerating(false);
    }
  }

  async function approve(doc: ReferenceDocument) {
    if (doc.assignmentId == null) return;
    await referenceLibraryApi.approveSuggestion(doc.assignmentId);
    await load();
  }
  async function dismiss(doc: ReferenceDocument) {
    if (doc.assignmentId == null) return;
    await referenceLibraryApi.dismissSuggestion(doc.assignmentId);
    await load();
  }
  async function removeInherited(doc: ReferenceDocument) {
    await referenceLibraryApi.removeInherited(pid, doc.id);
    await load();
  }

  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: "inherited", label: "Inherited", count: data?.summary.inherited ?? 0 },
    { key: "suggested", label: "Suggested", count: data?.summary.suggested ?? 0 },
    { key: "projectUnique", label: "Project-unique", count: data?.summary.projectUnique ?? 0 },
  ];

  const docs =
    tab === "inherited"
      ? data?.inherited ?? []
      : tab === "suggested"
        ? data?.suggested ?? []
        : data?.projectUnique ?? [];

  return (
    <>
      <div className="space-y-4">
      <div className="flex justify-end gap-2">
        <Button variant="brandSoft" onClick={generate} disabled={generating}>
          <IconSparkles size={14} />
          {generating ? "Analyzing…" : "Suggest references"}
        </Button>
        <Button variant="primary" onClick={() => setShowUpload(true)}>
          <IconPlus size={14} /> Add Reference
        </Button>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Active in AI scope" value={data?.summary.totalActive ?? 0} />
          <StatTile label="Inherited" value={data?.summary.inherited ?? 0} />
          <StatTile label="Suggested (pending)" value={data?.summary.suggestedPending ?? 0} />
          <StatTile label="Project-unique" value={data?.summary.projectUnique ?? 0} />
        </div>

        {notice && (
          <div className="rounded-md border border-line-tertiary bg-bg-tertiary px-3 py-2 text-[13px] text-ink-secondary">
            {notice}
          </div>
        )}

        <div className="flex gap-1 border-b border-line-tertiary">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={cn(
                "border-b-2 px-3 py-2 text-[13px] font-medium",
                tab === t.key
                  ? "border-brand-500 text-ink-primary"
                  : "border-transparent text-ink-tertiary hover:text-ink-secondary",
              )}
            >
              {t.label}
              <Badge tone="neutral" className="ml-1.5">{t.count}</Badge>
            </button>
          ))}
        </div>

        {tab === "inherited" && (
          <DocumentTable
            documents={docs}
            loading={loading}
            emptyText="No inherited references. Company documents marked 'inherit by default' appear here."
            renderActions={(d) =>
              d.tierBadge === "Company" ? (
                <Button variant="ghost" size="sm" onClick={() => void removeInherited(d)}>
                  Remove
                </Button>
              ) : null
            }
          />
        )}

        {tab === "suggested" && (
          <DocumentTable
            documents={docs}
            loading={loading}
            emptyText="No suggestions yet. Click 'Suggest references' to let AI scan this project."
            extraColumn={{
              header: "Why",
              render: (d) => (
                <span className="text-[12px] text-ink-secondary">{d.reasoning || "—"}</span>
              ),
            }}
            renderActions={(d) => (
              <div className="flex justify-end gap-1">
                <Button variant="brandSoft" size="sm" onClick={() => void approve(d)}>
                  Approve
                </Button>
                <Button variant="ghost" size="sm" onClick={() => void dismiss(d)}>
                  Dismiss
                </Button>
              </div>
            )}
          />
        )}

        {tab === "projectUnique" && (
          <DocumentTable
            documents={docs}
            loading={loading}
            emptyText="No project-specific references yet. Use 'Add Reference' to upload one."
          />
        )}
      </div>

      {showUpload && (
        <ReferenceUploadModal
          tier="project"
          projectId={pid}
          meta={meta}
          onClose={() => setShowUpload(false)}
          onCreated={load}
        />
      )}
    </>
  );
}

export const ReferenceLibraryScreen = ProjectReferenceLibraryPanel;
