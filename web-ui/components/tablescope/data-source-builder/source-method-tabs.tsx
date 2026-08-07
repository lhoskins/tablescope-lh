"use client";

import { cn } from "@/lib/cn";
import {
  IconCloudUpload,
  IconLink,
  IconDatabase,
  IconFolderShare,
} from "@tabler/icons-react";

export type SourceTab = "upload" | "url" | "database" | "network";

const TABS: { key: SourceTab; label: string; icon: typeof IconCloudUpload }[] = [
  { key: "upload", label: "Upload File", icon: IconCloudUpload },
  { key: "url", label: "File URL", icon: IconLink },
  { key: "database", label: "Database Connectors", icon: IconDatabase },
  { key: "network", label: "Network File Connections", icon: IconFolderShare },
];

export function SourceMethodTabs({
  activeTab,
  onChange,
}: {
  activeTab: SourceTab;
  onChange: (tab: SourceTab) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Data source method"
      className="flex items-center gap-1 overflow-x-auto border-b border-line-tertiary"
    >
      {TABS.map((tab) => {
        const Icon = tab.icon;
        const active = activeTab === tab.key;
        return (
          <button
            key={tab.key}
            role="tab"
            aria-selected={active}
            type="button"
            onClick={() => onChange(tab.key)}
            className={cn(
              "flex shrink-0 items-center gap-2 whitespace-nowrap px-4 py-2.5 text-[13px] font-medium transition-colors",
              active
                ? "border-b-2 border-brand text-brand-700"
                : "text-ink-secondary hover:text-ink-primary",
            )}
          >
            <Icon size={16} />
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
