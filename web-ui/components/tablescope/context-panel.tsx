"use client";

import { type ReactNode, useEffect, useState } from "react";
import {
  IconArrowUp,
  IconChevronLeft,
  IconChevronRight,
  IconX,
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { StatusDot } from "./status-dot";

const COLLAPSED_KEY = "tablescope:ai-context-collapsed";
const MOBILE_BREAKPOINT = 1024;

export function ContextPanel({
  title = "AI Context",
  aiOnline = true,
  askPlaceholder = "Ask about this…",
  onAsk,
  collapsible = false,
  children,
}: {
  title?: string;
  aiOnline?: boolean;
  askPlaceholder?: string;
  onAsk?: (value: string) => void | Promise<void>;
  collapsible?: boolean;
  children: ReactNode;
}) {
  const [isMobile, setIsMobile] = useState(false);
  const [expanded, setExpanded] = useState(true);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const mobile = window.innerWidth < MOBILE_BREAKPOINT;
    setIsMobile(mobile);

    try {
      const saved = window.localStorage.getItem(COLLAPSED_KEY);
      if (saved === null) {
        setExpanded(!mobile);
      } else {
        setExpanded(saved !== "true");
      }
    } catch {
      setExpanded(!mobile);
    }

    function onResize() {
      setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const toggle = () => {
    setExpanded((v) => {
      const next = !v;
      try {
        window.localStorage.setItem(COLLAPSED_KEY, String(!next));
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  const submitAsk = (value: string) => {
    const v = value.trim();
    if (!v) return;
    onAsk?.(v);
  };

  if (!mounted) {
    return (
      <aside className="flex w-rail shrink-0 flex-col border-l border-line-tertiary bg-bg-tertiary" />
    );
  }

  if (collapsible && isMobile) {
    return (
      <>
        {!expanded && (
          <button
            type="button"
            onClick={toggle}
            aria-label={`Open ${title}`}
            aria-expanded={false}
            className="fixed right-0 top-1/2 z-30 flex -translate-y-1/2 items-center gap-1 rounded-l-md border border-line-tertiary border-r-0 bg-bg-primary px-2 py-3 text-[12px] font-medium text-ink-secondary shadow-sm hover:bg-bg-secondary"
          >
            <StatusDot tone={aiOnline ? "online" : "offline"} />
            <span className="[writing-mode:vertical-lr] rotate-180">{title}</span>
          </button>
        )}
        {expanded && (
          <>
            <div
              className="fixed inset-0 z-20 bg-black/20"
              onClick={() => setExpanded(false)}
              aria-hidden="true"
            />
            <aside className="fixed right-0 top-0 z-30 flex h-dvh w-rail flex-col border-l border-line-tertiary bg-bg-tertiary shadow-xl">
              <ExpandedPanel
                title={title}
                aiOnline={aiOnline}
                askPlaceholder={askPlaceholder}
                onAsk={submitAsk}
                onCollapse={toggle}
                collapsible
                isMobile
              >
                {children}
              </ExpandedPanel>
            </aside>
          </>
        )}
      </>
    );
  }

  return (
    <aside
      className={cn(
        "flex shrink-0 flex-col border-l border-line-tertiary bg-bg-tertiary transition-[width] duration-200",
        collapsible && !expanded ? "w-14" : "w-rail",
      )}
    >
      {collapsible && !expanded ? (
        <div className="flex flex-col items-center gap-3 border-b border-line-tertiary px-2 py-3">
          <button
            type="button"
            onClick={toggle}
            aria-label={`Expand ${title}`}
            aria-expanded={false}
            title={`Expand ${title}`}
            className="flex h-9 w-9 items-center justify-center rounded-md text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
          >
            <IconChevronLeft size={18} />
          </button>
          <StatusDot tone={aiOnline ? "online" : "offline"} />
          <span
            className="text-[11px] font-medium text-ink-tertiary [writing-mode:vertical-lr] rotate-180"
            aria-hidden
          >
            {title}
          </span>
        </div>
      ) : (
        <ExpandedPanel
          title={title}
          aiOnline={aiOnline}
          askPlaceholder={askPlaceholder}
          onAsk={submitAsk}
          onCollapse={collapsible ? toggle : undefined}
          collapsible={collapsible}
        >
          {children}
        </ExpandedPanel>
      )}
    </aside>
  );
}

function ExpandedPanel({
  title,
  aiOnline,
  askPlaceholder,
  onAsk,
  onCollapse,
  collapsible,
  isMobile,
  children,
}: {
  title: string;
  aiOnline: boolean;
  askPlaceholder: string;
  onAsk: (value: string) => void | Promise<void>;
  onCollapse?: () => void;
  collapsible: boolean;
  isMobile?: boolean;
  children: ReactNode;
}) {
  const [value, setValue] = useState("");

  return (
    <>
      <div className="flex items-center justify-between px-4 py-3.5">
        <span className="text-h2 text-ink-primary">{title}</span>
        <div className="flex items-center gap-1">
          <StatusDot tone={aiOnline ? "online" : "offline"} />
          {collapsible && (
            <button
              type="button"
              onClick={onCollapse}
              aria-label={`Collapse ${title}`}
              aria-expanded={true}
              title={`Collapse ${title}`}
              className="flex h-7 w-7 items-center justify-center rounded-md text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
            >
              {isMobile ? <IconX size={16} /> : <IconChevronRight size={18} />}
            </button>
          )}
        </div>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto px-4 pb-4">
        {children}
      </div>
      <div className="border-t border-line-tertiary p-3">
        <div className="flex items-center gap-1.5 rounded-md border border-line-secondary bg-bg-primary px-2.5 py-1.5">
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                onAsk(value);
                setValue("");
              }
            }}
            placeholder={askPlaceholder}
            className="min-w-0 flex-1 bg-transparent text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:outline-none"
          />
          <button
            type="button"
            onClick={() => {
              onAsk(value);
              setValue("");
            }}
            aria-label="Ask"
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-brand text-brand-fg hover:bg-brand-700"
          >
            <IconArrowUp size={14} />
          </button>
        </div>
      </div>
    </>
  );
}

export function ContextSection({
  title,
  action,
  className,
  children,
}: {
  title: string;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section
      className={cn(
        "rounded-lg border border-line-tertiary bg-bg-primary p-3",
        className,
      )}
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-caption uppercase tracking-wide text-ink-tertiary">
          {title}
        </span>
        {action}
      </div>
      {children}
    </section>
  );
}

export function IsolationCard({
  tenant,
  project,
  user,
}: {
  tenant: string;
  project: string;
  user: string;
}) {
  return (
    <ContextSection title="Active Isolation">
      <dl className="space-y-1 text-[13px]">
        <div className="flex justify-between gap-2">
          <dt className="text-ink-tertiary">Tenant</dt>
          <dd className="truncate text-ink-primary">{tenant}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-ink-tertiary">Project</dt>
          <dd className="truncate text-ink-primary">{project}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-ink-tertiary">User</dt>
          <dd className="truncate text-ink-primary">{user}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-ink-tertiary">Cross-project</dt>
          <dd className="text-ink-tertiary">disabled</dd>
        </div>
      </dl>
    </ContextSection>
  );
}
