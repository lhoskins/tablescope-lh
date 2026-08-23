"use client";

import {
  IconDatabase,
  IconFileText,
  IconLayoutDashboard,
  IconTable,
  IconX,
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { useWorkspaceTabs } from "./use-workspace-tabs";
import type { WorkspaceTab } from "./workspace-tabs-storage";

const TYPE_ICON: Record<WorkspaceTab["type"], typeof IconTable> = {
  table: IconTable,
  dashboard: IconLayoutDashboard,
  document: IconFileText,
  data_source: IconDatabase,
};

export function WorkspaceTabsBar({
  projectId,
  activeItem,
}: {
  projectId: string;
  activeItem: WorkspaceTab | null;
}) {
  const { tabs, activeKey, activate, closeTab } = useWorkspaceTabs(projectId, activeItem);

  if (tabs.length === 0) return null;

  return (
    <nav
      aria-label="Open workspace items"
      className="flex items-center gap-1 overflow-x-auto border-t border-line-tertiary px-5 py-1.5"
    >
      {tabs.map((tab) => {
        const key = `${tab.type}:${tab.id}`;
        const active = key === activeKey;
        const Icon = TYPE_ICON[tab.type];
        return (
          <span
            key={key}
            className={cn(
              "group flex shrink-0 items-center gap-1.5 rounded-md py-1 pl-2 pr-1 text-[12px] font-medium transition-colors",
              active
                ? "bg-brand-50 text-brand-700"
                : "text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary",
            )}
          >
            <button
              type="button"
              onClick={() => activate(tab)}
              aria-current={active ? "page" : undefined}
              className="flex items-center gap-1.5"
            >
              <Icon size={13} />
              <span className="max-w-[10rem] truncate">{tab.label}</span>
            </button>
            <button
              type="button"
              onClick={() => closeTab(tab)}
              aria-label={`Close ${tab.label}`}
              className="rounded p-0.5 hover:bg-bg-tertiary"
            >
              <IconX size={11} />
            </button>
          </span>
        );
      })}
    </nav>
  );
}
