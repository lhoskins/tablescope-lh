import {
  IconHome,
  IconFolders,
  IconSparkles,
  IconBulb,
  IconFileText,
  IconLayoutDashboard,
  IconTopologyStar3,
  IconHistory,
  IconLayoutGrid,
  IconDatabase,
  IconDatabasePlus,
  IconCode,
  IconBinaryTree,
  IconBook2,
  IconLibrary,
  IconBuildingBank,
  IconMessage,
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
          key: "business-insight",
          label: "Business Insight",
          href: "/business-insight",
          icon: IconBulb,
        },
        {
          key: "projects",
          label: "Projects",
          href: "/projects",
          icon: IconFolders,
          countKey: "projects",
        },
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
        {
          key: "ai-assistant",
          label: "AI Assistant",
          href: "/ai",
          icon: IconSparkles,
        },
      ],
    },
    {
      heading: "Tools",
      items: [
        {
          key: "data-source-builder",
          label: "Data Source Builder",
          href: "/data-source-builder",
          icon: IconDatabasePlus,
        },
        {
          key: "database-connectors",
          label: "Database Connectors",
          href: "/database-connectors",
          icon: IconDatabase,
        },
        {
          key: "reference-library",
          label: "Reference Library",
          href: "/reference-library",
          icon: IconLibrary,
        },
        {
          key: "company-reference-library",
          label: "Company Library",
          href: "/reference-library/company",
          icon: IconBuildingBank,
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
          key: "project-insights",
          label: "Project Insights",
          href: `${base}/insight`,
          icon: IconSparkles,
        },
        {
          key: "project-data-sources",
          label: "Data Sources",
          href: `${base}/data-sources`,
          icon: IconDatabase,
        },
        {
          key: "project-queries",
          label: "Tables",
          href: `${base}/queries`,
          icon: IconCode,
          countKey: "queries",
        },
        {
          key: "project-scopes",
          label: "Scopes",
          href: `${base}/scopes`,
          icon: IconBinaryTree,
        },
        {
          key: "project-documents",
          label: "Documents",
          href: `${base}/documents`,
          icon: IconFileText,
          countKey: "documents",
        },
        {
          key: "project-business-context",
          label: "Business Context",
          href: `${base}/business-context`,
          icon: IconBuildingBank,
        },
      ],
    },
    {
      heading: "Intelligence",
      items: [
        {
          key: "project-ask-tablescope",
          label: "Ask TableScope",
          href: `${base}/ai`,
          icon: IconMessage,
        },
        {
          key: "project-knowledge-graph",
          label: "Graph Lifecycle",
          href: `${base}/knowledge-graph`,
          icon: IconHistory,
        },
        {
          key: "project-metadata-catalog",
          label: "Metadata Catalog",
          href: `${base}/metadata-catalog`,
          icon: IconBook2,
        },
        {
          key: "project-reference-library",
          label: "Reference Library",
          href: `${base}/reference-library`,
          icon: IconLibrary,
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
