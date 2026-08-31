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
  IconLayoutGrid,
  IconTable,
  IconFileText,
  IconLayoutDashboard,
  IconMessage2,
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
  _tenant?: TenantSummary,
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
          key: "workspace",
          label: "Workspace",
          href: `${base}/workspace`,
          icon: IconLayoutGrid,
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

  return groups;
}

/**
 * The project nav grid — one row of buttons at the top of every project
 * page (see `docs/ux-workspace-redesign-gap-analysis.md` §3). This
 * consolidates the old sidebar's "Project" group and the old
 * `ProjectResourceTabs` strip into a single persistent row, which is what
 * frees the sidebar to stay locked to the project asset tree instead of
 * switching its link set per page. All twelve routes already exist; this
 * is link relocation, not new pages, with the single exception of
 * `project-ai-assistant` ("Chats"), which is new.
 */
export function projectGridItems(projectId: string): NavItem[] {
  const base = `/projects/${projectId}`;
  return [
    { key: "overview", label: "Overview", href: base, icon: IconHome },
    {
      key: "project-data-sources",
      label: "Data Sources",
      href: `${base}/data-sources`,
      icon: IconDatabase,
    },
    {
      key: "workspace",
      label: "Workspace",
      href: `${base}/workspace`,
      icon: IconLayoutGrid,
    },
    {
      key: "project-queries",
      label: "Tables",
      href: `${base}/queries`,
      icon: IconTable,
    },
    {
      key: "project-documents",
      label: "Documents",
      href: `${base}/documents`,
      icon: IconFileText,
    },
    {
      key: "project-dashboards",
      label: "Dashboards",
      href: `${base}/dashboards`,
      icon: IconLayoutDashboard,
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
      // "Reference" is Goals, renamed -- confirmed by elimination in the gap
      // analysis (§3): it's the only old-sidebar item left unplaced once the
      // other eleven cards are accounted for.
      key: "project-business-context",
      label: "Reference",
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
    {
      key: "project-ai-assistant",
      label: "Chats",
      href: `${base}/chats`,
      icon: IconMessage2,
    },
  ];
}

export const projectIntelligenceNavItems = (projectId: string): NavItem[] => [
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
