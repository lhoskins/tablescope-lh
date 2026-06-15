import { Fragment, type ReactNode } from "react";
import Link from "next/link";
import { cn } from "@/lib/cn";

export function TopBar({
  left,
  right,
  className,
}: {
  left?: ReactNode;
  right?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex h-topbar shrink-0 items-center justify-between gap-4 border-b border-line-tertiary bg-bg-primary px-5",
        className,
      )}
    >
      <div className="flex min-w-0 items-center gap-2">{left}</div>
      <div className="flex shrink-0 items-center gap-2">{right}</div>
    </header>
  );
}

export interface Crumb {
  label: string;
  href?: string;
}

export function Breadcrumb({ items }: { items: Crumb[] }) {
  return (
    <nav className="flex min-w-0 items-center gap-1.5 text-[13px]">
      {items.map((c, i) => {
        const last = i === items.length - 1;
        return (
          <Fragment key={`${c.label}-${i}`}>
            {c.href && !last ? (
              <Link
                href={c.href}
                className="truncate text-ink-tertiary hover:text-ink-primary"
              >
                {c.label}
              </Link>
            ) : (
              <span
                className={cn(
                  "truncate",
                  last ? "font-medium text-ink-primary" : "text-ink-tertiary",
                )}
              >
                {c.label}
              </span>
            )}
            {!last && <span className="text-ink-tertiary">›</span>}
          </Fragment>
        );
      })}
    </nav>
  );
}
