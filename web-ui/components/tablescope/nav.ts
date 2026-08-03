import {
  IconHome,
  IconFolders,
  IconSparkles,
  IconBulb,
  IconDatabaseShare,

  IconTopologyStar3,
  IconHistory,
  IconDatabase,
  IconDatabasePlus,
  IconBinaryTree,
  IconBook2,
  IconLibrary,
  IconBuildingBank,
  IconClipboardList,
  type Icon,
} from "@tabler/icons-react";
import type { CurrentUser, NavKey } from "@/lib/ui/types";

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

function canManageAdminTools(user?: CurrentUser): boolean {
  if (!user) return false;
  const adminRoles = ["admin", "tenant_admin", "root_admin"];
  return adminRoles.includes(user.rawRole ?? "") || Boolean(user.isSuperAdmin);
}

export function homeNavGroups(user?: CurrentUser): NavGroup[] {
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
        ...(canManageAdminTools(user)
          ? [
              {
                key: "admin-data-source-assignments" as NavKey,
                label: "Data Source Assignments",
                href: "/admin/data-source-assignments",
                icon: IconDatabaseShare,
              },
            ]
          : []),
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
          label: "Project Home",
          href: base,
          icon: IconHome,
        },
        {
          key: "project-insights",
          label: "Project Insights",
          href: `${base}/insight`,
          icon: IconSparkles,
        },
        {
          key: "project-actions",
          label: "Project Actions",
          href: `${base}/actions`,
          icon: IconClipboardList,
        },
        {
          key: "project-business-context",
          label: "Goals",
          href: `${base}/business-context`,
          icon: IconBuildingBank,
        },
        {
          key: "project-scopes",
          label: "Scopes",
          href: `${base}/scopes`,
          icon: IconBinaryTree,
        },
        {
          key: "project-relationship-map",
          label: "Knowledge Graph",
          href: `${base}/relationship-map`,
          icon: IconTopologyStar3,
        },
      ],
    },
    {
      heading: "Intelligence",
      items: [
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
