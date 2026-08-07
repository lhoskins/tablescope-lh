"use client";

import { useRouter } from "next/navigation";
import {
  IconChevronRight,
  IconCode,
  IconDatabase,
  IconFileText,
  IconLayoutDashboard,
  IconServer,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";

export function QuickActionsCard({
  projectId,
  canEdit,
  className,
}: {
  projectId: string;
  canEdit: boolean;
  className?: string;
}) {
  const router = useRouter();
  const actions = [
    {
      // Always goes through the Data Source Builder so connector selection,
      // file acquisition, and project assignment stay a single governed flow
      // rather than a second, inline creation path.
      label: "Create datasource",
      icon: IconDatabase,
      onClick: () => router.push(`/projects/${projectId}/data-source-builder`),
    },
    {
      // Same Data Source Builder, scoped to the connected-databases section
      // so the intent here is "create a database-backed data source."
      label: "Create Database connection",
      icon: IconServer,
      onClick: () =>
        router.push(`/projects/${projectId}/data-source-builder?intent=database`),
    },
    {
      label: "Create table",
      icon: IconCode,
      onClick: () => router.push(`/projects/${projectId}/queries`),
    },
    {
      // Same Data Source Builder, but scoped to just the upload/AI-scan step
      // (skips connector selection) since the intent here is always "scan
      // this file," not "pick a connector type."
      label: "Upload file",
      icon: IconFileText,
      onClick: () =>
        router.push(`/projects/${projectId}/data-source-builder?intent=upload`),
    },
    {
      label: "New dashboard",
      icon: IconLayoutDashboard,
      onClick: () => router.push(`/projects/${projectId}/dashboards`),
    },
  ];

  return (
    <Card className={cn("flex flex-col", className)}>
      <div className="border-b border-line-tertiary px-4 py-3">
        <span className="text-h3 text-ink-primary">Quick actions</span>
      </div>
      <ul className="flex flex-col gap-2 p-3" data-testid="quick-actions-list">
        {actions.map((action) => {
          const Icon = action.icon;
          const disabled = !canEdit;
          return (
            <li key={action.label}>
              <Button
                variant="secondary"
                size="sm"
                disabled={disabled}
                onClick={action.onClick}
                title={disabled ? "You do not have permission to create project resources" : action.label}
                className="min-h-[44px] w-full justify-start"
              >
                <Icon size={14} />
                <span className="flex-1 text-left">{action.label}</span>
                <IconChevronRight size={14} className="text-ink-tertiary" aria-hidden />
              </Button>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
