"use client";

import { type ReactNode, useState } from "react";
import { IconArrowUp } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { StatusDot } from "./status-dot";

export function ContextPanel({
  title = "AI Context",
  aiOnline = true,
  askPlaceholder = "Ask about this…",
  onAsk,
  children,
}: {
  title?: string;
  aiOnline?: boolean;
  askPlaceholder?: string;
  onAsk?: (value: string) => void;
  children: ReactNode;
}) {
  const [value, setValue] = useState("");
  const submit = () => {
    const v = value.trim();
    if (!v) return;
    onAsk?.(v);
    setValue("");
  };

  return (
    <aside className="flex w-rail shrink-0 flex-col border-l border-line-tertiary bg-bg-tertiary">
      <div className="flex items-center justify-between px-4 py-3.5">
        <span className="text-h2 text-ink-primary">{title}</span>
        <StatusDot tone={aiOnline ? "online" : "offline"} />
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
              if (e.key === "Enter") submit();
            }}
            placeholder={askPlaceholder}
            className="min-w-0 flex-1 bg-transparent text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:outline-none"
          />
          <button
            type="button"
            onClick={submit}
            aria-label="Ask"
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-brand text-brand-fg hover:bg-brand-700"
          >
            <IconArrowUp size={14} />
          </button>
        </div>
      </div>
    </aside>
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
