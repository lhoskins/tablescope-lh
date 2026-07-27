"use client";

import { type ReactNode, useEffect, useState } from "react";
import { IconMinus, IconPlus } from "@tabler/icons-react";
import { cn } from "@/lib/cn";

export function InsightPanel({
  title,
  icon,
  children,
  headerRight,
  collapsible = false,
  defaultOpen = true,
  forceOpen = false,
  count,
}: {
  title: string;
  icon?: ReactNode;
  children: ReactNode;
  headerRight?: ReactNode;
  collapsible?: boolean;
  defaultOpen?: boolean;
  /**
   * Open the panel from outside, after mount. `defaultOpen` only seeds the
   * initial state, so it cannot reveal a panel once the hash it depends on is
   * read (the hash is unavailable during SSR). The user can still collapse it.
   */
  forceOpen?: boolean;
  count?: number;
}) {
  const [open, setOpen] = useState(!collapsible || defaultOpen);

  useEffect(() => {
    if (forceOpen) setOpen(true);
  }, [forceOpen]);
  const badge = collapsible && count != null && count > 0 && (
    <span className="rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-medium text-brand-700">
      {count}
    </span>
  );
  const toggle = collapsible ? () => setOpen((v) => !v) : undefined;

  return (
    <section className="rounded-lg border border-line-tertiary bg-bg-primary">
      <div
        className={cn(
          "flex items-center justify-between gap-2 px-4 py-3",
          open && "border-b border-line-tertiary",
          collapsible && "cursor-pointer select-none",
        )}
        {...(collapsible
          ? {
              role: "button" as const,
              tabIndex: 0,
              "aria-expanded": open,
              onClick: toggle,
              onKeyDown: (e: React.KeyboardEvent) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  toggle?.();
                }
              },
            }
          : {})}
      >
        <div className="flex items-center gap-2">
          {icon}
          <h3 className="text-h3 text-ink-primary">{title}</h3>
        </div>
        <div className="flex items-center gap-2">
          {headerRight}
          {badge}
          {collapsible &&
            (open ? (
              <IconMinus size={16} className="text-ink-tertiary" />
            ) : (
              <IconPlus size={16} className="text-ink-tertiary" />
            ))}
        </div>
      </div>
      {open && <div className="p-4">{children}</div>}
    </section>
  );
}

export function PanelEmpty({ text }: { text: string }) {
  return <p className="py-2 text-[13px] text-ink-tertiary">{text}</p>;
}
