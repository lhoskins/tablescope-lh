"use client";

import { useCallback, useState } from "react";
import {
  IconCheck,
  IconAlertTriangle,
  IconInfoCircle,
  IconX,
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";

export type ToastTone = "success" | "error" | "info";

export interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
}

/**
 * Lightweight, self-contained toast hook. Each page instantiates its own
 * viewport — no global provider needed. Toasts auto-dismiss after 4s.
 */
export function useToasts() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  const push = useCallback(
    (message: string, tone: ToastTone = "info") => {
      const id = Date.now() + Math.random();
      setToasts((t) => [...t, { id, message, tone }]);
      setTimeout(() => dismiss(id), 4000);
    },
    [dismiss],
  );

  return { toasts, push, dismiss };
}

const TONE_STYLES: Record<ToastTone, string> = {
  success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  error: "border-red-200 bg-red-50 text-red-800",
  info: "border-line-secondary bg-bg-primary text-ink-primary",
};

function ToneIcon({ tone }: { tone: ToastTone }) {
  if (tone === "success") return <IconCheck size={16} className="shrink-0" />;
  if (tone === "error")
    return <IconAlertTriangle size={16} className="shrink-0" />;
  return <IconInfoCircle size={16} className="shrink-0" />;
}

export function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: ToastItem[];
  onDismiss: (id: number) => void;
}) {
  if (toasts.length === 0) return null;
  return (
    <div className="fixed bottom-4 right-4 z-[60] flex max-w-sm flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className={cn(
            "flex items-start gap-2 rounded-md border px-3 py-2.5 text-[13px] shadow-md",
            TONE_STYLES[t.tone],
          )}
        >
          <ToneIcon tone={t.tone} />
          <span className="flex-1">{t.message}</span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => onDismiss(t.id)}
            className="shrink-0 opacity-60 hover:opacity-100"
          >
            <IconX size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
