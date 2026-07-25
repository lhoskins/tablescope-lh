"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { IconSearch, IconPlus, IconCloudUpload } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { StatTile } from "@/components/ui/stat-tile";
import { ReferenceUploadModal } from "@/components/tablescope/reference-library/upload-modal";
import { BulkImportModal } from "@/components/tablescope/reference-library/bulk-import-modal";
import { DocumentTable } from "@/components/tablescope/reference-library/document-table";
import {
  referenceLibraryApi,
  type ReferenceDocument,
  type ReferenceMeta,
} from "@/lib/api/reference-library";

export function ReferenceLibraryPanel() {
  const [meta, setMeta] = useState<ReferenceMeta | null>(null);
  const [docs, setDocs] = useState<ReferenceDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [domain, setDomain] = useState("");
  const [showUpload, setShowUpload] = useState(false);
  const [showBulk, setShowBulk] = useState(false);

  useEffect(() => {
    referenceLibraryApi.meta().then(setMeta).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await referenceLibraryApi.listDocuments({
        tier: "industry",
        domain: domain || undefined,
        search: search || undefined,
      });
      setDocs(res.documents);
    } finally {
      setLoading(false);
    }
  }, [domain, search]);

  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [load]);

  const canWrite = meta?.permissions.industryWrite ?? false;
  const stats = useMemo(() => {
    const processed = docs.filter((d) => d.hasFile && d.status === "active").length;
    const needsDocument = docs.filter((d) => !d.hasFile).length;
    return { total: docs.length, processed, needsDocument };
  }, [docs]);

  return (
    <section>
      <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-ink-primary">
            Reference Library
          </h2>
          <p className="mt-1 text-sm text-ink-tertiary">
            Globally available standards, regulations, and frameworks curated by
            Tablescope. Visible to all tenants; editable by platform staff only.
          </p>
        </div>
        {canWrite && (
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setShowBulk(true)}>
              <IconCloudUpload size={14} /> Bulk URL Import
            </Button>
            <Button variant="primary" onClick={() => setShowUpload(true)}>
              <IconPlus size={14} /> Add Reference
            </Button>
          </div>
        )}
      </header>

      <div className="space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <StatTile label="References" value={stats.total} />
          <StatTile label="Processed" value={stats.processed} />
          <StatTile label="Needs document" value={stats.needsDocument} />
        </div>

        <div className="flex flex-wrap gap-2">
          <div className="relative max-w-sm flex-1">
            <IconSearch
              size={15}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-tertiary"
            />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search references…"
              className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary pl-8 pr-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
            />
          </div>
          <select
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            className="h-9 rounded-md border border-line-secondary bg-bg-primary px-2.5 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
          >
            <option value="">All domains</option>
            {meta?.domains.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>

        <DocumentTable documents={docs} loading={loading} />
      </div>

      {showUpload && (
        <ReferenceUploadModal
          tier="industry"
          meta={meta}
          onClose={() => setShowUpload(false)}
          onCreated={load}
        />
      )}
      {showBulk && (
        <BulkImportModal onClose={() => setShowBulk(false)} onComplete={load} />
      )}
    </section>
  );
}
