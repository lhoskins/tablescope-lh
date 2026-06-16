import {
  IconHome,
  IconFolders,
  IconSparkles,
  IconActivity,
  IconFileText,
  IconLayoutDashboard,
  IconTopologyStar3,
  IconPuzzle,
  IconHistory,
  IconSettings,
  IconLayoutGrid,
  IconDatabase,
  IconCode,
  IconBook2,
  type Icon,
} from "@tabler/icons-react";
import type { NavKey } from "@/lib/ui/types";

export interface NavItem {
  key: NavKey;
  label: string;
  href: string;
  icon: Icon;
  /** Optional numeric badge (e.g. project count, query count). */
  countKey?: "projects" | "queries" | "documents";
}

export interface NavGroup {
  heading?: string;
  items: NavItem[];
}

export function homeNavGroups(): NavGroup[] {
  return [
    {
      items: [
        { key: "home", label: "Home", href: "/", icon: IconHome },
        {
          key: "projects",
          label: "Projects",
          href: "/projects",
          icon: IconFolders,
          countKey: "projects",
        },
        {
          key: "ai-assistant",
          label: "AI Assistant",
          href: "/ai",
          icon: IconSparkles,
        },
        {
          key: "activity",
          label: "Activity",
          href: "/activity",
          icon: IconActivity,
        },
      ],
    },
    {
      heading: "Tools",
      items: [
        {
          key: "documents",
          label: "Documents",
          href: "/documents",
          icon: IconFileText,
        },
        {
          key: "dashboards",
          label: "Dashboards",
          href: "/dashboards",
          icon: IconLayoutDashboard,
        },
      ],
    },
    {
      heading: "System",
      items: [
        {
          key: "integrations",
          label: "Integrations",
          href: "/integrations",
          icon: IconPuzzle,
        },
        {
          key: "audit-log",
          label: "Audit Log",
          href: "/audit-log",
          icon: IconHistory,
        },
        {
          key: "settings",
          label: "Settings",
          href: "/settings",
          icon: IconSettings,
        },
      ],
    },
  ];
}

export function projectNavGroups(projectId: string): NavGroup[] {
  const base = `/projects/${projectId}`;
  return [
    {
      heading: "Project",
      items: [
        {
          key: "overview",
          label: "Overview",
          href: base,
          icon: IconLayoutGrid,
        },
        {
          key: "project-data-sources",
          label: "Data Sources",
          href: `${base}/data-sources`,
          icon: IconDatabase,
        },
        {
          key: "project-queries",
          label: "Queries",
          href: `${base}/queries`,
          icon: IconCode,
          countKey: "queries",
        },
        {
          key: "project-dashboards",
          label: "Dashboards",
          href: `${base}/dashboards`,
          icon: IconLayoutDashboard,
        },
        {
          key: "project-documents",
          label: "Documents",
          href: `${base}/documents`,
          icon: IconFileText,
          countKey: "documents",
        },
      ],
    },
    {
      heading: "Intelligence",
      items: [
        {
          key: "project-ai-assistant",
          label: "AI Assistant",
          href: `${base}/ai`,
          icon: IconSparkles,
        },
        {
          key: "project-relationship-map",
          label: "Relationship Map",
          href: `${base}/relationship-map`,
          icon: IconTopologyStar3,
        },
        {
          key: "project-metadata-catalog",
          label: "Metadata Catalog",
          href: `${base}/metadata-catalog`,
          icon: IconBook2,
        },
        {
          key: "project-audit-log",
          label: "Audit Log",
          href: `${base}/audit-log`,
          icon: IconHistory,
        },
      ],
    },
  ];
}
