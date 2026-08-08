"use client";

import { cn } from "@/lib/cn";
import {
  IconCloudUpload,
  IconLink,
  IconDatabase,
  IconFolderShare,
} from "@tabler/icons-react";

export type SourceTab = "upload" | "url" | "database" | "network";

type TabDef = {
  key: SourceTab;
  label: string;
  subtitle: string;
  icon: typeof IconCloudUpload;
};

const TABS: TabDef[] = [
  { key: "upload", label: "Upload File", subtitle: "From this computer", icon: IconCloudUpload },
  { key: "url", label: "File URL", subtitle: "Secure https link", icon: IconLink },
  { key: "database", label: "Database Connectors", subtitle: "Database or SaaS", icon: IconDatabase },
  { key: "network", label: "Network File Connections", subtitle: "UNC/SMB share", icon: IconFolderShare },
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
      className="flex gap-3 overflow-x-auto pb-1"
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
              "flex min-w-[10rem] shrink-0 items-start gap-3 rounded-xl border p-3.5 text-left transition",
              active
                ? "border-brand bg-brand-50/50 text-brand-700"
                : "border-line-tertiary bg-bg-primary text-ink-secondary hover:bg-bg-secondary",
            )}
          >
            <span
              className={cn(
                "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
                active ? "bg-brand text-white" : "bg-bg-tertiary text-ink-tertiary",
              )}
            >
              <Icon size={18} />
            </span>
            <span className="min-w-0">
              <span className="block text-[13px] font-semibold text-current">
                {tab.label}
              </span>
              <span className="block text-caption text-current/70">
                {tab.subtitle}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
