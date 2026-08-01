"use client";

import { useRouter } from "next/navigation";
import {
  IconChevronRight,
  IconCode,
  IconDatabase,
  IconFileText,
  IconLayoutDashboard,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConnectorsMenu } from "@/components/datasource/ConnectorsMenu";
import { cn } from "@/lib/cn";

export function QuickActionsCard({
  projectId,
  canEdit,
  onSourceCreated,
  className,
}: {
  projectId: string;
  canEdit: boolean;
  onSourceCreated: () => void;
  className?: string;
}) {
  const router = useRouter();
  const actions = [
    {
      label: "Add data source",
      icon: IconDatabase,
      onClick: undefined as (() => void) | undefined,
      content: (
        <ConnectorsMenu
          projectId={Number(projectId)}
          onCreated={onSourceCreated}
          label="Add data source"
        />
      ),
    },
    {
      label: "Create table",
      icon: IconCode,
      onClick: () => router.push(`/projects/${projectId}/queries`),
    },
    {
      label: "Upload file",
      icon: IconFileText,
      onClick: () => router.push(`/projects/${projectId}/documents`),
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
              {action.content ? (
                <div className="[&>div]:w-full [&_button]:min-h-[44px] [&_button]:w-full [&_button]:justify-start">
                  {action.content}
                </div>
              ) : (
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
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
