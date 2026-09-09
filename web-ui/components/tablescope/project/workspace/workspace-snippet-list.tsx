"use client";

import { useCallback, useRef, useState } from "react";
import { IconX } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { SNIPPET_CLAMP_CHARS, type WorkspaceSnippet } from "./workspace-snippet-storage";

/** Where the list starts before the user drags it to a preferred height. */
const DEFAULT_PINNED_HEIGHT = 176;
const MIN_PINNED_HEIGHT = 96;
/** Whatever room the drag has to give -- the transcript and composer below
 *  it in Chat, the rest of the pane in Notes -- leave at least this much of
 *  it visible; the handle can't drag the list into swallowing everything. */
const MIN_REMAINDER = 64;

function pinnedHeightKey(storageKey: string): string {
  return `tablescope-pinned-height-${storageKey}`;
}

function readStoredHeight(storageKey: string): number | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(pinnedHeightKey(storageKey));
    const n = raw ? Number(raw) : NaN;
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch {
    return null;
  }
}

/**
 * Pinned excerpts, shown above the composer.
 *
 * Visible rather than hidden behind a counter on purpose: after a long
 * conversation the useful question is "what is this anchored to?", and the
 * answer should be readable without opening anything. Long passages clamp to a
 * few lines and expand on click, so five snippets don't bury the chat.
 *
 * Height is user-adjustable via the handle at the bottom -- same drag
 * mechanics and the same look as the pane info/chat drawer divider
 * (`startDrawerResize` in use-pane-layout.ts), so the workspace has one
 * consistent way to resize things rather than two.
 */
export function WorkspaceSnippetList({
  snippets,
  onRemove,
  onClear,
  storageKey,
}: {
  snippets: WorkspaceSnippet[];
  onRemove: (id: number) => void;
  onClear?: () => void;
  /** Persists the user's preferred height for this list (e.g. "chat" or
   *  "notes") across visits. A layout preference, not workspace data, so it
   *  isn't scoped to a project or workspace -- it holds however you last
   *  left it, wherever you go next. */
  storageKey?: string;
}) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const [height, setHeight] = useState(() =>
    (storageKey && readStoredHeight(storageKey)) || DEFAULT_PINNED_HEIGHT,
  );
  const listRef = useRef<HTMLUListElement>(null);

  const startResize = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const list = listRef.current;
      // The flex column the list's wrapper sits in -- the chat column, or
      // the Notes pane body -- is what actually has spare room to give; the
      // wrapper itself just hugs the list's own height.
      const room = list?.parentElement?.parentElement;
      if (!list) return;

      event.preventDefault();
      const handle = event.currentTarget;
      handle.setPointerCapture(event.pointerId);
      document.body.classList.add("workspace-resizing");

      const startY = event.clientY;
      const startHeight = list.getBoundingClientRect().height;
      const roomHeight = room?.getBoundingClientRect().height ?? Infinity;
      const maxHeight = Math.max(MIN_PINNED_HEIGHT, roomHeight - MIN_REMAINDER);

      let frame = 0;
      let latest = startHeight;

      const apply = () => {
        frame = 0;
        list.style.height = `${latest}px`;
      };

      const onMove = (moveEvent: PointerEvent) => {
        latest = Math.min(
          Math.max(MIN_PINNED_HEIGHT, startHeight + (moveEvent.clientY - startY)),
          maxHeight,
        );
        if (!frame) frame = requestAnimationFrame(apply);
      };

      const onUp = () => {
        if (frame) cancelAnimationFrame(frame);
        apply();
        handle.releasePointerCapture(event.pointerId);
        handle.removeEventListener("pointermove", onMove);
        handle.removeEventListener("pointerup", onUp);
        handle.removeEventListener("pointercancel", onUp);
        document.body.classList.remove("workspace-resizing");
        setHeight(latest);
        if (storageKey) {
          try {
            window.localStorage.setItem(pinnedHeightKey(storageKey), String(Math.round(latest)));
          } catch {
            // Storage unavailable -- the size still holds for this session.
          }
        }
      };

      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", onUp);
      handle.addEventListener("pointercancel", onUp);
    },
    [storageKey],
  );

  if (snippets.length === 0) return null;

  return (
    <div className="shrink-0 border-b border-line-tertiary bg-bg-secondary/40 px-2 py-1.5">
      <div className="flex shrink-0 items-center gap-2 px-1 pb-1">
        <span className="flex-1 text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
          Pinned context · {snippets.length}
        </span>
        {onClear && (
          <button
            type="button"
            onClick={onClear}
            className="rounded px-1 text-[11px] font-medium text-ink-tertiary hover:text-danger"
          >
            Clear
          </button>
        )}
      </div>
      <ul ref={listRef} style={{ height }} className="space-y-1 overflow-y-auto">
        {snippets.map((snippet) => {
          const isLong = snippet.text.length > SNIPPET_CLAMP_CHARS;
          const open = expanded === snippet.id;
          return (
            <li
              key={snippet.id}
              className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5"
            >
              <div className="flex items-start gap-1">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-caption font-semibold uppercase tracking-wide text-brand-500">
                    {snippet.label}
                  </p>
                  {snippet.image ? (
                    // eslint-disable-next-line @next/next/no-img-element -- a
                    // pasted screenshot held as a data URL, not a managed asset.
                    <img
                      src={snippet.image}
                      alt={snippet.label}
                      className="mt-1 max-h-24 rounded border border-line-tertiary"
                    />
                  ) : (
                    <p
                      className={cn(
                        "text-[12px] leading-snug text-ink-secondary",
                        !open && isLong && "line-clamp-3",
                      )}
                    >
                      {snippet.text}
                    </p>
                  )}
                  {isLong && (
                    <button
                      type="button"
                      onClick={() => setExpanded(open ? null : snippet.id)}
                      aria-expanded={open}
                      className="mt-0.5 text-[11px] font-medium text-brand-500 hover:text-brand-700"
                    >
                      {open ? "Less" : "More"}
                    </button>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => onRemove(snippet.id)}
                  aria-label={`Remove pinned excerpt from ${snippet.label}`}
                  className="shrink-0 rounded p-0.5 text-ink-tertiary hover:text-danger"
                >
                  <IconX size={12} />
                </button>
              </div>
            </li>
          );
        })}
      </ul>

      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- a
          drag handle, not an interactive control; matches the pane drawer
          divider's own accessibility treatment. */}
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize pinned context"
        onPointerDown={startResize}
        className="group relative -mx-2 mt-1 h-3 shrink-0 cursor-row-resize touch-none"
      >
        <span className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-line-tertiary transition-colors group-hover:bg-brand-500" />
      </div>
    </div>
  );
}
