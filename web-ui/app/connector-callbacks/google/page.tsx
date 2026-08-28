"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { completeGoogleSheetsAuthorization } from "@/lib/api/connectors";

function CallbackInner() {
  const params = useSearchParams();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("Completing Google authorization…");

  useEffect(() => {
    const code = params.get("code");
    const state = params.get("state");

    if (!code || !state) {
      setStatus("error");
      setMessage("Missing authorization code or state from Google.");
      return;
    }

    let cancelled = false;
    completeGoogleSheetsAuthorization({ code, state, display_name: "Google Drive" })
      .then(() => {
        if (cancelled) return;
        setStatus("success");
        setMessage("Google Drive connected. You can close this window.");
        if (window.opener) {
          window.opener.postMessage({ type: "google-sheets-connected" }, window.location.origin);
          window.close();
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setStatus("error");
        setMessage(err instanceof Error ? err.message : "Could not complete Google authorization.");
      });

    return () => {
      cancelled = true;
    };
  }, [params]);

  return (
    <main className="mx-auto max-w-lg px-6 py-16 text-center">
      <h1 className="mb-2 text-h1 text-ink-primary">Google Drive</h1>
      <p className="text-body text-ink-secondary">
        {status === "error" ? "❌ " : status === "success" ? "✅ " : ""}
        {message}
      </p>
      {status === "success" && !window.opener && (
        <p className="mt-4 text-small text-ink-tertiary">
          Return to the Data Source Builder and select your spreadsheet.
        </p>
      )}
    </main>
  );
}

export default function GoogleSheetsCallbackPage() {
  return (
    <Suspense fallback={<div className="p-10 text-center">Loading…</div>}>
      <CallbackInner />
    </Suspense>
  );
}
