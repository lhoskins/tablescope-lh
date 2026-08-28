"use client";

import { useEffect, useRef, useState } from "react";
import { IconLoader2, IconX } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { authorizeGoogleSheets } from "@/lib/api/connectors";

export function GoogleSheetsConnectionModal({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const popupRef = useRef<Window | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (
        event.origin !== window.location.origin ||
        event.data?.type !== "google-sheets-connected"
      ) {
        return;
      }
      onSaved();
      onClose();
    };
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
      if (pollRef.current) clearInterval(pollRef.current);
      if (popupRef.current && !popupRef.current.closed) popupRef.current.close();
    };
  }, [onClose, onSaved]);

  const startAuth = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authorizeGoogleSheets();
      setAuthUrl(res.authorizationUrl);
      const width = 480;
      const height = 640;
      const left = window.screenX + (window.outerWidth - width) / 2;
      const top = window.screenY + (window.outerHeight - height) / 2;
      const popup = window.open(
        res.authorizationUrl,
        "google-sheets-auth",
        `width=${width},height=${height},left=${left},top=${top},noopener=noreferrer`,
      );
      if (!popup) {
        setError("Popup blocked. Please allow popups for this site.");
        setLoading(false);
        return;
      }
      popupRef.current = popup;
      pollRef.current = setInterval(() => {
        if (popup.closed) {
          if (pollRef.current) clearInterval(pollRef.current);
          onSaved();
          onClose();
        }
      }, 500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start Google authorization.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl bg-bg-primary p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-h2 text-ink-primary">Connect Google Drive</h2>
            <p className="text-small text-ink-tertiary">
              Authorize Tablescope to read your Google Sheets and Drive files.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-7 w-7 items-center justify-center rounded text-ink-tertiary hover:bg-bg-secondary"
          >
            <IconX size={16} />
          </button>
        </div>

        <div className="space-y-3">
          <p className="text-body text-ink-secondary">
            Tablescope needs read-only access to Google Drive and Google Sheets. You will be
            prompted to sign in and grant permission.
          </p>

          {authUrl && (
            <p className="text-small text-ink-tertiary">
              A Google sign-in popup has opened. If you don&apos;t see it, check your popup
              blocker.
            </p>
          )}

          {error && (
            <div className="rounded-md border border-danger/40 bg-danger-bg/40 px-3 py-2 text-[12px] text-danger">
              {error}
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={startAuth}
              disabled={loading || Boolean(authUrl)}
            >
              {loading && <IconLoader2 size={14} className="mr-1 animate-spin" />}
              Authorize Google Drive
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
