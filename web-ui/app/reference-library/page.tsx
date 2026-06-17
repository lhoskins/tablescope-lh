"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { IconSearch, IconPlus, IconCloudUpload } from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { Button } from "@/components/ui/button";
import { StatTile } from "@/components/ui/stat-tile";
import { ReferenceUploadModal } from "@/components/tablescope/reference-library/upload-modal";
import { BulkImportModal } from "@/components/tablescope/reference-library/bulk-import-modal";
import { DocumentTable } from "@/components/tablescope/reference-library/document-table";
import { getUserMeta } from "@/lib/auth";
import { useCurrentUser, useProjectSummaries } from "@/lib/ui/use-shell-data";
import type { CurrentUser, TenantSummary } from "@/lib/ui/types";
import {
  referenceLibraryApi,
  type ReferenceDocument,
  type ReferenceMeta,
} from "@/lib/api/reference-library";

const FALLBACK_USER: CurrentUser = {
  name: "", email: "", role: "", tenantName: "", initials: "··",
};
const FALLBACK_TENANT: TenantSummary = { name: "Tablescope", slug: "", initials: "TS" };

export default function IndustryLibraryPage() {
  const router = useRouter();
  const { data: identity } = useCurrentUser();
  const { data: projects } = useProjectSummaries();
  const [meta, setMeta] = useState<ReferenceMeta | null>(null);
  const [docs, setDocs] = useState<ReferenceDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [domain, setDomain] = useState("");
  const [showUpload, setShowUpload] = useState(false);
  const [showBulk, setShowBulk] = useState(false);

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

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
    const withFile = docs.filter((d) => d.hasFile).length;
    const active = docs.filter((d) => d.status === "active").length;
    return { total: docs.length, withFile, active };
  }, [docs]);

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  return (
    <AppShell
      mode="home"
      activeNav="reference-library"
      tenant={tenant}
      user={user}
      counts={{ projects: projects?.length }}
      centered
      topBarLeft={<span className="text-h2 text-ink-primary">Industry Reference Library</span>}
      topBarRight={
        canWrite ? (
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setShowBulk(true)}>
              <IconCloudUpload size={14} /> Bulk URL Import
            </Button>
            <Button variant="primary" onClick={() => setShowUpload(true)}>
              <IconPlus size={14} /> Add Reference
            </Button>
          </div>
        ) : undefined
      }
    >
      <div className="space-y-4">
        <p className="text-[13px] text-ink-secondary">
          Globally available standards, regulations, and frameworks curated by Tablescope.
          Visible to all tenants; editable by platform staff only.
        </p>

        <div className="grid grid-cols-3 gap-3">
          <StatTile label="References" value={stats.total} />
          <StatTile label="With document" value={stats.withFile} />
          <StatTile label="Active" value={stats.active} />
        </div>

        <div className="flex gap-2">
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
            {meta?.domains.map((d) => <option key={d} value={d}>{d}</option>)}
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
    </AppShell>
  );
}
