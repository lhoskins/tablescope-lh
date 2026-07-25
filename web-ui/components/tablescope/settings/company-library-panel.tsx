"use client";

import { useCallback, useEffect, useState } from "react";
import { IconPlus, IconSend } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { StatTile } from "@/components/ui/stat-tile";
import { ReferenceUploadModal } from "@/components/tablescope/reference-library/upload-modal";
import { DocumentTable } from "@/components/tablescope/reference-library/document-table";
import {
  referenceLibraryApi,
  type ReferenceDocument,
  type ReferenceMeta,
} from "@/lib/api/reference-library";

function RequestModal({
  meta,
  onClose,
}: {
  meta: ReferenceMeta | null;
  onClose: () => void;
}) {
  const [title, setTitle] = useState("");
  const [issuingBody, setIssuingBody] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [domainTag, setDomainTag] = useState("");
  const [justification, setJustification] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!title.trim()) {
      setError("Title is required");
      return;
    }
    setSubmitting(true);
    try {
      await referenceLibraryApi.createRequest({
        title: title.trim(),
        issuing_body: issuingBody || undefined,
        source_url: sourceUrl || undefined,
        domain_tag: domainTag || undefined,
        justification: justification || undefined,
      });
      setDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setSubmitting(false);
    }
  }

  const inputCls =
    "h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-2.5 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-lg border border-line-tertiary bg-bg-primary shadow-xl">
        <div className="border-b border-line-tertiary px-4 py-3">
          <h3 className="text-h3 text-ink-primary">Request Industry Addition</h3>
        </div>
        <div className="space-y-3 px-4 py-4 text-[13px]">
          {done ? (
            <p className="text-success">
              Request submitted. Tablescope staff will review it.
            </p>
          ) : (
            <>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Standard title *"
                className={inputCls}
              />
              <input
                value={issuingBody}
                onChange={(e) => setIssuingBody(e.target.value)}
                placeholder="Issuing body"
                className={inputCls}
              />
              <input
                value={sourceUrl}
                onChange={(e) => setSourceUrl(e.target.value)}
                placeholder="Source URL"
                className={inputCls}
              />
              <select
                value={domainTag}
                onChange={(e) => setDomainTag(e.target.value)}
                className={inputCls}
              >
                <option value="">Domain…</option>
                {meta?.domains.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
              <textarea
                value={justification}
                onChange={(e) => setJustification(e.target.value)}
                placeholder="Why should this be added to the shared Industry catalog?"
                className="min-h-[80px] w-full rounded-md border border-line-secondary bg-bg-primary px-2.5 py-2 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
              />
              {error && <div className="text-[12px] text-danger">{error}</div>}
            </>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-line-tertiary px-4 py-3">
          <Button variant="ghost" onClick={onClose}>
            {done ? "Close" : "Cancel"}
          </Button>
          {!done && (
            <Button variant="primary" onClick={submit} disabled={submitting}>
              {submitting ? "Submitting…" : "Submit request"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

export function CompanyLibraryPanel() {
  const [meta, setMeta] = useState<ReferenceMeta | null>(null);
  const [docs, setDocs] = useState<ReferenceDocument[]>([]);
  const [stats, setStats] = useState({ total: 0, inheritByDefault: 0 });
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [showRequest, setShowRequest] = useState(false);

  useEffect(() => {
    referenceLibraryApi.meta().then(setMeta).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await referenceLibraryApi.companyLibrary();
      setDocs(res.documents);
      setStats({ total: res.stats.total, inheritByDefault: res.stats.inheritByDefault });
    } catch (e) {
      if (e instanceof Error && e.message.includes("403")) setForbidden(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggleInherit(doc: ReferenceDocument) {
    await referenceLibraryApi.updateDocument(doc.id, {
      inherit_default: !doc.inheritDefault,
    });
    void load();
  }

  const canWrite = meta?.permissions.companyWrite ?? false;

  return (
    <section>
      <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-ink-primary">
            Company Library
          </h2>
          <p className="mt-1 text-sm text-ink-tertiary">
            Internal policies and standards for your company. Visible only within
            your tenant. Toggle <strong>Inherit by default</strong> to auto-include
            a document in every project&apos;s library.
          </p>
        </div>
        {canWrite && (
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setShowRequest(true)}>
              <IconSend size={14} /> Request Industry addition
            </Button>
            <Button variant="primary" onClick={() => setShowUpload(true)}>
              <IconPlus size={14} /> Add Reference
            </Button>
          </div>
        )}
      </header>

      {forbidden ? (
        <div className="rounded-lg border border-line-tertiary bg-bg-tertiary px-4 py-10 text-center text-ink-secondary">
          The Company Library is available to tenant administrators only.
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <StatTile label="References" value={stats.total} />
            <StatTile label="Inherited by default" value={stats.inheritByDefault} />
          </div>

          <DocumentTable
            documents={docs}
            loading={loading}
            emptyText="No company references yet."
            extraColumn={{
              header: "Inherit by default",
              render: (d) => (
                <label className="inline-flex cursor-pointer items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={d.inheritDefault}
                    disabled={!canWrite}
                    onChange={() => void toggleInherit(d)}
                    className="h-3.5 w-3.5 rounded border-line-secondary text-brand focus:ring-brand"
                  />
                </label>
              ),
            }}
          />
        </div>
      )}

      {showUpload && (
        <ReferenceUploadModal
          tier="company"
          meta={meta}
          onClose={() => setShowUpload(false)}
          onCreated={load}
        />
      )}
      {showRequest && (
        <RequestModal meta={meta} onClose={() => setShowRequest(false)} />
      )}
    </section>
  );
}
