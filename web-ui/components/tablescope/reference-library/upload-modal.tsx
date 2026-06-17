"use client";

import { useEffect, useRef, useState } from "react";
import { IconUpload, IconX, IconSparkles } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  referenceLibraryApi,
  type ReferenceMeta,
  type ReferenceTier,
  type ReferenceDocument,
} from "@/lib/api/reference-library";

interface UploadModalProps {
  tier: ReferenceTier;
  projectId?: number;
  meta: ReferenceMeta | null;
  onClose: () => void;
  onCreated: () => void;
}

export function ReferenceUploadModal({
  tier,
  projectId,
  meta,
  onClose,
  onCreated,
}: UploadModalProps) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [issuingBody, setIssuingBody] = useState("");
  const [domainTag, setDomainTag] = useState("");
  const [applicabilityTag, setApplicabilityTag] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [versionLabel, setVersionLabel] = useState("");
  const [existingId, setExistingId] = useState<number | null>(null);
  const [autofilled, setAutofilled] = useState(false);
  const [overrideDuplicate, setOverrideDuplicate] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Starter-catalog auto-fill: when the typed title closely matches an existing
  // Industry reference (incl. metadata-only stubs), pull in its metadata.
  useEffect(() => {
    const term = title.trim();
    if (term.length < 4) return;
    const handle = setTimeout(async () => {
      try {
        const res = await referenceLibraryApi.listDocuments({
          tier: "industry",
          search: term,
        });
        const match = bestMatch(term, res.documents);
        if (match) {
          setIssuingBody((v) => v || match.issuingBody || "");
          setDomainTag((v) => v || match.domainTag || "");
          setSourceUrl((v) => v || match.sourceUrl || "");
          setVersionLabel((v) => v || match.versionLabel || "");
          if (tier === "industry" && !match.hasFile) setExistingId(match.id);
          setAutofilled(true);
        }
      } catch {
        /* best-effort */
      }
    }, 400);
    return () => clearTimeout(handle);
  }, [title, tier]);

  async function submit() {
    if (!title.trim()) {
      setError("Title is required");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("tier", tier);
      form.append("title", title.trim());
      if (issuingBody) form.append("issuing_body", issuingBody);
      if (domainTag) form.append("domain_tag", domainTag);
      if (applicabilityTag) form.append("applicability_tag", applicabilityTag);
      if (sourceUrl) form.append("source_url", sourceUrl);
      if (effectiveDate) form.append("effective_date", effectiveDate);
      if (versionLabel) form.append("version_label", versionLabel);
      if (projectId != null) form.append("project_id", String(projectId));
      if (existingId != null) form.append("existing_document_id", String(existingId));
      if (overrideDuplicate) form.append("override_duplicate", "true");
      if (file) form.append("file", file);
      await referenceLibraryApi.createDocument(form);
      onCreated();
      onClose();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Upload failed";
      if (msg.toLowerCase().includes("duplicate")) {
        setError("A similar reference already exists. Check 'Import anyway' to proceed.");
      } else {
        setError(msg);
      }
    } finally {
      setSubmitting(false);
    }
  }

  const tierLabel =
    tier === "industry" ? "Industry" : tier === "company" ? "Company" : "Project";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-lg border border-line-tertiary bg-bg-primary shadow-xl">
        <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
          <h3 className="text-h3 text-ink-primary">
            Add {tierLabel} Reference
          </h3>
          <button onClick={onClose} className="text-ink-tertiary hover:text-ink-primary">
            <IconX size={18} />
          </button>
        </div>

        <div className="space-y-3 overflow-y-auto px-4 py-4 text-[13px]">
          {autofilled && (
            <div className="flex items-center gap-1.5 rounded-md bg-ai-bg px-2.5 py-1.5 text-[12px] text-ai">
              <IconSparkles size={13} />
              Auto-filled from the starter catalog — review before saving.
            </div>
          )}

          <Field label="Title *">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. NIST SP 800-161"
              className={inputCls}
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Issuing body">
              <input
                list="ref-issuers"
                value={issuingBody}
                onChange={(e) => setIssuingBody(e.target.value)}
                className={inputCls}
              />
              <datalist id="ref-issuers">
                {meta?.issuers.map((i) => <option key={i} value={i} />)}
              </datalist>
            </Field>
            <Field label="Domain">
              <select
                value={domainTag}
                onChange={(e) => setDomainTag(e.target.value)}
                className={inputCls}
              >
                <option value="">Select…</option>
                {meta?.domains.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Applicability">
              <select
                value={applicabilityTag}
                onChange={(e) => setApplicabilityTag(e.target.value)}
                className={inputCls}
              >
                <option value="">Select…</option>
                {meta?.applicabilityTags.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
            </Field>
            <Field label="Version label">
              <input
                value={versionLabel}
                onChange={(e) => setVersionLabel(e.target.value)}
                placeholder="e.g. rev. 2024"
                className={inputCls}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Source URL">
              <input
                value={sourceUrl}
                onChange={(e) => setSourceUrl(e.target.value)}
                placeholder="https://…"
                className={inputCls}
              />
            </Field>
            <Field label="Effective date">
              <input
                type="date"
                value={effectiveDate}
                onChange={(e) => setEffectiveDate(e.target.value)}
                className={inputCls}
              />
            </Field>
          </div>

          <Field label="Document file">
            <div
              onClick={() => fileRef.current?.click()}
              className="flex cursor-pointer items-center gap-2 rounded-md border border-dashed border-line-secondary px-3 py-3 text-ink-secondary hover:border-brand-500"
            >
              <IconUpload size={16} />
              {file ? file.name : "Click to choose a PDF / DOCX / HTML / TXT file (optional)"}
            </div>
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.docx,.pptx,.txt,.md,.html,.htm"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </Field>

          <label className="flex items-center gap-2 text-[12px] text-ink-secondary">
            <input
              type="checkbox"
              checked={overrideDuplicate}
              onChange={(e) => setOverrideDuplicate(e.target.checked)}
            />
            Import anyway despite possible duplicates
          </label>

          {error && <div className="text-[12px] text-danger">{error}</div>}
        </div>

        <div className="flex justify-end gap-2 border-t border-line-tertiary px-4 py-3">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={submitting}>
            {submitting ? "Saving…" : "Save reference"}
          </Button>
        </div>
      </div>
    </div>
  );
}

const inputCls =
  "h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-2.5 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-caption uppercase tracking-wide text-ink-tertiary">
        {label}
      </span>
      {children}
    </label>
  );
}

function bestMatch(term: string, docs: ReferenceDocument[]): ReferenceDocument | null {
  const t = term.toLowerCase();
  let best: ReferenceDocument | null = null;
  let bestScore = 0;
  for (const d of docs) {
    const title = d.title.toLowerCase();
    let score = 0;
    if (title === t) score = 1;
    else if (title.startsWith(t) || t.startsWith(title)) score = 0.9;
    else if (title.includes(t) || t.includes(title)) score = 0.8;
    if (score > bestScore) {
      bestScore = score;
      best = d;
    }
  }
  return bestScore >= 0.8 ? best : null;
}
