import {
  IconHome,
  IconFolders,
  IconSparkles,
  IconBulb,
  IconDatabase,
  IconDatabasePlus,
  IconTopologyStar3,
  IconHistory,
  IconBook2,
  IconLibrary,
  IconBuildingBank,
  IconClipboardList,
  IconBinaryTree,
  IconChartBar,
  type Icon,
} from "@tabler/icons-react";
import type { CurrentUser, NavKey, TenantSummary } from "@/lib/ui/types";
import {
  canManageDataSourceAssignments,
  canViewSettings,
} from "@/lib/ui/permissions";

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
  ];
}

export function projectNavGroups(
  projectId: string,
  user?: CurrentUser,
  tenant?: TenantSummary,
): NavGroup[] {
  const base = `/projects/${projectId}`;
  const groups: NavGroup[] = [
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
          key: "project-itsm-dashboards",
          label: "ITSM Dashboards",
          href: `${base}/itsm-dashboards`,
          icon: IconChartBar,
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
      heading: "Tools",
      items: [
        {
          key: "project-data-source-builder",
          label: "Data Source Builder",
          href: `${base}/data-source-builder`,
          icon: IconDatabasePlus,
        },
      ],
    },
  ];

  if (!tenant?.servicenowItsmDashboardsV2Enabled) {
    const projectGroup = groups[0];
    if (projectGroup) {
      projectGroup.items = projectGroup.items.filter(
        (i) => i.key !== "project-itsm-dashboards",
      );
    }
  }

  return groups;
}

export const projectIntelligenceNavItems = (
  projectId: string,
): NavItem[] => [
  {
    key: "project-knowledge-graph",
    label: "Graph Lifecycle",
    href: `/admin/settings/project-intelligence/${projectId}/graph-lifecycle`,
    icon: IconHistory,
  },
  {
    key: "project-metadata-catalog",
    label: "Metadata Catalog",
    href: `/admin/settings/project-intelligence/${projectId}/metadata-catalog`,
    icon: IconBook2,
  },
  {
    key: "project-reference-library",
    label: "Project Reference Library",
    href: `/admin/settings/project-intelligence/${projectId}/reference-library`,
    icon: IconLibrary,
  },
  {
    key: "project-audit-log",
    label: "Audit Log",
    href: `/admin/settings/project-intelligence/${projectId}/audit-log`,
    icon: IconHistory,
  },
];

export { canViewSettings, canManageDataSourceAssignments };
