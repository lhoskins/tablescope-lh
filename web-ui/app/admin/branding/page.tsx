"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient, getApiBaseUrl } from "@/lib/api-client";

type CompanyLogo = { logo_url: string | null };

const QUERY_KEY = ["company-logo"] as const;
const MAX_BYTES = 5 * 1024 * 1024;
const ACCEPTED = ["image/png", "image/jpeg", "image/jpg", "image/webp"];

function absolute(url: string | null): string | null {
  if (!url) return null;
  if (/^https?:\/\//.test(url)) return url;
  return `${getApiBaseUrl()}${url}`;
}

export default function BrandingPage() {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);

  const logoQuery = useQuery<CompanyLogo>({
    queryKey: QUERY_KEY,
    queryFn: () => apiClient.get<CompanyLogo>("/api/tenants/current/logo"),
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) =>
      apiClient.upload<CompanyLogo>("/api/tenants/current/logo", file),
    onSuccess: (data) => {
      queryClient.setQueryData(QUERY_KEY, data);
      // Refresh the identity so the top-header logo updates without a reload.
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      setError(null);
      if (inputRef.current) inputRef.current.value = "";
    },
    onError: (err: Error) => setError(err.message),
  });

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    setError(null);
    const file = e.target.files?.[0];
    if (!file) return;
    if (!ACCEPTED.includes(file.type)) {
      setError("Unsupported image type. Use PNG, JPG, or WEBP.");
      return;
    }
    if (file.size > MAX_BYTES) {
      setError("Image too large (max 5 MB).");
      return;
    }
    uploadMutation.mutate(file);
  }

  const logoUrl = absolute(logoQuery.data?.logo_url ?? null);

  return (
    <section className="max-w-3xl">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">Branding</h1>
        <p className="mt-1 text-sm text-slate-500">
          Upload your company logo. It appears on the right side of the top
          header across the app for everyone in your organization. This is your
          company branding and is separate from the Tablescope product logo.
        </p>
      </header>

      <div className="space-y-6">
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-sm font-medium text-slate-900">
            Company logo
          </h2>

          <div className="mb-4 flex flex-col items-start gap-4 sm:flex-row sm:items-center">
            <div className="flex h-16 w-40 items-center justify-center rounded-md border border-dashed border-slate-300 bg-slate-50">
              {logoQuery.isLoading ? (
                <span className="text-xs text-slate-400">Loading…</span>
              ) : logoUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={logoUrl}
                  alt="Company logo"
                  className="max-h-14 max-w-[150px] object-contain"
                />
              ) : (
                <span className="text-xs text-slate-400">No logo yet</span>
              )}
            </div>
            <div className="text-xs text-slate-500">
              PNG, JPG, or WEBP. Max 5 MB. The logo is scaled to fit without
              stretching.
            </div>
          </div>

          <input
            ref={inputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={handleFile}
            className="hidden"
          />
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={uploadMutation.isPending}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
          >
            {uploadMutation.isPending
              ? "Uploading…"
              : logoUrl
                ? "Replace logo"
                : "Upload logo"}
          </button>

          {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
        </div>
      </div>
    </section>
  );
}
