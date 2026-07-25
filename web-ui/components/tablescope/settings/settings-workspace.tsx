"use client";

import { useCurrentUser } from "@/lib/ui/use-shell-data";
import { SettingsNav } from "./settings-nav";

export interface SettingsWorkspaceProps {
  children: React.ReactNode;
}

export function SettingsWorkspace({ children }: SettingsWorkspaceProps) {
  const { data: identity } = useCurrentUser();

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-ink-primary">Settings</h1>
        <p className="mt-1 text-sm text-ink-tertiary">
          Manage your organization, security, knowledge sources, integrations,
          and intelligence controls.
        </p>
      </header>

      <div className="flex flex-col gap-6 md:flex-row md:items-start">
        <div className="md:w-60 md:shrink-0 md:sticky md:top-0 md:self-start">
          <SettingsNav user={identity?.user} />
        </div>
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}
