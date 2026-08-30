"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * The action center: one full-bleed strip sitting flush under the project nav
 * grid, holding everything you can *do* on the screen you're looking at --
 * create actions, search, filters. It replaced the per-screen stat bubbles,
 * which duplicated counts the nav grid and lists already show.
 *
 * Negative gutters cancel the page's own padding so the strip reaches the
 * sidebar on one side and the AI Assistant panel on the other, reading as a
 * continuation of the nav chrome above rather than a floating card. It
 * therefore has to be the first thing a screen renders.
 */
export function ActionCenter({
  label,
  subBar,
  subBarLabel,
  children,
}: {
  label: string;
  /** Optional second tier for screens with more controls than one row can
   *  hold (Project Actions): filters, grouping and sorting sit here, under
   *  the primary actions, inside the same strip. */
  subBar?: ReactNode;
  subBarLabel?: string;
  children: ReactNode;
}) {
  return (
    <div className="-mx-5 -mt-5 mb-5 border-b border-line-tertiary bg-bg-primary">
      <section
        aria-label={label}
        className={cn(
          "flex flex-wrap items-center gap-2 px-5 py-4",
          subBar && "border-b border-line-tertiary",
        )}
      >
        {children}
      </section>
      {subBar && (
        <section
          aria-label={subBarLabel ?? `${label} filters`}
          className="flex flex-wrap items-center gap-2 bg-bg-secondary/40 px-5 py-2.5"
        >
          {subBar}
        </section>
      )}
    </div>
  );
}

/** A read-only count in the action center (Active / Overdue / …). Same box as
 *  an `ActionCard` so the row stays level, but not a button. */
export function ActionStat({
  value,
  label,
  tone = "default",
}: {
  value: number | string;
  label: string;
  tone?: "default" | "danger" | "success";
}) {
  return (
    <div
      className={cn(
        "flex h-[38px] min-w-[68px] shrink-0 flex-col items-center justify-center rounded-lg border border-line-secondary bg-bg-primary px-2.5 text-center leading-tight",
        tone === "danger" && "border-danger/30",
        tone === "success" && "border-success/30",
      )}
    >
      <span
        className={cn(
          "text-[13px] font-semibold",
          tone === "danger"
            ? "text-danger"
            : tone === "success"
              ? "text-success"
              : "text-ink-primary",
        )}
      >
        {value}
      </span>
      <span className="text-[10px] font-medium text-ink-tertiary">{label}</span>
    </div>
  );
}

/** Shared height for everything in the strip, so cards, search boxes and
 *  filter pills line up. */
export const ACTION_ROW_HEIGHT = "h-[38px]";

const CARD_BASE =
  "flex h-[38px] min-w-[68px] shrink-0 flex-col items-center justify-center rounded-lg border px-2.5 text-center text-[11px] font-medium leading-tight transition-colors disabled:opacity-50";

/**
 * An action-center button: same bordered card as the nav grid above, no icon,
 * and a label split over exactly two lines -- which is what keeps every card
 * in the row the same height regardless of how long its words are.
 */
export function ActionCard({
  lines,
  onClick,
  active,
  disabled,
  title,
}: {
  /** Label, one entry per line -- at most two. The card's height is fixed
   *  either way, so a one-line label still lines up with a two-line one. */
  lines: [string] | [string, string];
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      // Explicit label: the two lines are separate elements, so the text
      // content alone would run them together.
      aria-label={lines.join(" ")}
      className={cn(
        CARD_BASE,
        active
          ? "border-brand-500 bg-brand-50 text-brand-700"
          : "border-line-secondary bg-bg-primary text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary",
      )}
    >
      {lines.map((line) => (
        <span key={line}>{line}</span>
      ))}
    </button>
  );
}
