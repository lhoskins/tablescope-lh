"use client";

import { useState } from "react";
import { getApiBaseUrl } from "@/lib/api-client";

const TOKEN_KEY = "tablescope.token";

export function FileUploader({ onUploaded }: { onUploaded?: (path: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const token =
        typeof window !== "undefined"
          ? window.localStorage.getItem(TOKEN_KEY)
          : null;
      const response = await fetch(`${getApiBaseUrl()}/api/upload`, {
        method: "POST",
        body: form,
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail ?? `Upload failed: ${response.status}`);
      }
      const data = (await response.json()) as { path: string };
      onUploaded?.(data.path);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm hover:border-brand">
        <input type="file" className="hidden" disabled={busy} onChange={onChange} />
        {busy ? "Uploading…" : "Upload file"}
      </label>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}
