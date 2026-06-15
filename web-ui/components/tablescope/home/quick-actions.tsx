import Link from "next/link";
import {
  IconFolderPlus,
  IconDatabasePlus,
  IconFileUpload,
  IconChartHistogram,
  type Icon,
} from "@tabler/icons-react";

interface QuickAction {
  title: string;
  subtitle: string;
  href: string;
  icon: Icon;
  iconBg: string;
  iconColor: string;
}

const ACTIONS: QuickAction[] = [
  {
    title: "New project",
    subtitle: "Set up a project workspace",
    href: "/projects/new",
    icon: IconFolderPlus,
    iconBg: "bg-brand-50",
    iconColor: "text-brand-500",
  },
  {
    title: "Connect data",
    subtitle: "Add a database or data source",
    href: "/data-connections",
    icon: IconDatabasePlus,
    iconBg: "bg-success-bg",
    iconColor: "text-success",
  },
  {
    title: "Upload documents",
    subtitle: "Index files for AI search",
    href: "/documents",
    icon: IconFileUpload,
    iconBg: "bg-ai-bg",
    iconColor: "text-ai",
  },
  {
    title: "Generate dashboard",
    subtitle: "AI-built from your data",
    href: "/dashboards",
    icon: IconChartHistogram,
    iconBg: "bg-warning-bg",
    iconColor: "text-warning",
  },
];

export function QuickActionGrid() {
  return (
    <section>
      <h2 className="text-h2 text-ink-primary">Quick actions</h2>
      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {ACTIONS.map((a) => {
          const Icon = a.icon;
          return (
            <Link
              key={a.title}
              href={a.href}
              className="rounded-lg border border-line-tertiary bg-bg-primary p-4 transition-colors hover:border-line-secondary hover:bg-bg-tertiary"
            >
              <span
                className={`flex h-10 w-10 items-center justify-center rounded-lg ${a.iconBg}`}
              >
                <Icon size={20} className={a.iconColor} stroke={1.8} />
              </span>
              <div className="mt-8 text-h3 text-ink-primary">{a.title}</div>
              <div className="mt-0.5 text-small text-ink-tertiary">
                {a.subtitle}
              </div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
