"use client";

import { useEffect, useState } from "react";
import { IconMenu2, IconX } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { Sidebar } from "./sidebar";
import { SidebarProps } from "./sidebar/sidebar-props";

export function MobileNav(props: SidebarProps) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open navigation menu"
        aria-expanded={open}
        aria-controls="mobile-navigation-drawer"
        className="flex h-10 w-10 min-h-touch min-w-touch items-center justify-center rounded-md text-ink-secondary hover:bg-bg-secondary lg:hidden"
      >
        <IconMenu2 size={20} />
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/40 lg:hidden"
            aria-hidden="true"
            onClick={() => setOpen(false)}
          />
          <div
            id="mobile-navigation-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="fixed inset-y-0 left-0 z-50 w-3/4 max-w-[280px] bg-bg-primary shadow-xl lg:hidden"
          >
            <div className="flex h-full flex-col">
              <div className="flex h-topbar shrink-0 items-center justify-end border-b border-line-tertiary px-3">
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  aria-label="Close navigation menu"
                  className="flex h-10 w-10 min-h-touch min-w-touch items-center justify-center rounded-md text-ink-secondary hover:bg-bg-secondary"
                >
                  <IconX size={20} />
                </button>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto">
                <Sidebar {...props} className="w-full border-0" />
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
