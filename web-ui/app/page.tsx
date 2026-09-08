"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  IconHelpCircle,
  IconSparkles,
  IconFolderPlus,
  IconUsersGroup,
  IconUpload,
  IconDatabase,
  type Icon,
} from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { StatusDot } from "@/components/tablescope/status-dot";
import { Button } from "@/components/ui/button";
import { NewProjectDialog } from "@/components/tablescope/project/new-project-dialog";
import { WorkspaceAssistantPanel } from "@/components/tablescope/project/workspace/workspace-assistant-panel";
import {
  homePersonaProfile,
  normalizeHomePersona,
} from "@/components/tablescope/home/home-persona";
import { getPreferences } from "@/lib/api/home-intelligence";
import { getUserMeta } from "@/lib/auth";
import { greeting } from "@/lib/ui/format";
import { useCurrentUser, useProjectSummaries } from "@/lib/ui/use-shell-data";
import type { CurrentUser, TenantSummary } from "@/lib/ui/types";

const FALLBACK_USER: CurrentUser = {
  name: "",
  email: "",
  role: "",
  tenantName: "",
  initials: "··",
};
const FALLBACK_TENANT: TenantSummary = {
  name: "Tablescope",
  slug: "",
  initials: "TS",
};

interface StarterTile {
  key: string;
  label: string;
  description: string;
  icon: Icon;
  /** Tailwind classes for the icon chip (tinted square). */
  chip: string;
  /** Renders with the brand-tinted "primary" treatment. */
  primary?: boolean;
  /** Either a destination href or an in-page action -- exactly one. */
  href?: string;
  onClick?: () => void;
}

function StarterCardInner({ tile }: { tile: StarterTile }) {
  const TileIcon = tile.icon;
  return (
    <>
      <span
        className={`flex h-11 w-11 items-center justify-center rounded-lg ${tile.chip}`}
      >
        <TileIcon size={20} stroke={1.6} />
      </span>
      <span className="mt-6 block text-h2 text-ink-primary">{tile.label}</span>
      <span className="mt-1.5 block text-body leading-relaxed text-ink-tertiary">
        {tile.description}
      </span>
    </>
  );
}

function StarterCard({ tile }: { tile: StarterTile }) {
  const className = [
    "group flex h-full min-h-[212px] flex-col items-start rounded-xl border p-6 text-left transition",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
    tile.primary
      ? "border-brand-500 bg-brand-50 hover:shadow-sm"
      : "border-line-tertiary bg-white hover:border-line-secondary hover:shadow-sm",
  ].join(" ");

  if (tile.href) {
    return (
      <Link
        href={tile.href}
        className={className}
        data-testid={`starter-${tile.key}`}
      >
        <StarterCardInner tile={tile} />
      </Link>
    );
  }
  return (
    <button
      type="button"
      onClick={tile.onClick}
      className={className}
      data-testid={`starter-${tile.key}`}
    >
      <StarterCardInner tile={tile} />
    </button>
  );
}

export default function HomePage() {
  const router = useRouter();
  const { data: identity } = useCurrentUser();
  const { data: allProjects } = useProjectSummaries();
  const { data: preferences } = useQuery({
    queryKey: ["user-preferences"],
    queryFn: getPreferences,
  });
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;
  const profile = homePersonaProfile(
    normalizeHomePersona(preferences?.intelligence.home_persona),
  );

  const tiles: StarterTile[] = [
    {
      key: "new-project",
      label: "New Project",
      description:
        "Create a workspace to organize your tables, documents, and data sources.",
      icon: IconFolderPlus,
      chip: "bg-brand-50 text-brand-700",
      primary: true,
      onClick: () => setShowCreate(true),
    },
    {
      key: "shared-projects",
      label: "Shared Projects",
      description:
        "Access projects your teammates have shared with the organization.",
      icon: IconUsersGroup,
      chip: "bg-emerald-50 text-emerald-700",
      href: "/projects/shared",
    },
    {
      key: "upload-file",
      label: "Upload File",
      description:
        "Import a CSV, Excel, or PDF — AI indexes it and connects it to a project automatically.",
      icon: IconUpload,
      chip: "bg-violet-50 text-violet-700",
      href: "/data-source-builder?intent=upload",
    },
    {
      key: "data-sources",
      label: "Data Sources",
      description:
        "Connect a database, SaaS API, or live data feed using the Source Builder.",
      icon: IconDatabase,
      chip: "bg-amber-50 text-amber-700",
      href: "/data-source-builder?intent=database",
    },
  ];

  return (
    <AppShell
      mode="home"
      activeNav="home"
      tenant={tenant}
      user={user}
      counts={{ projects: allProjects?.length }}
      contextPanel={
        <WorkspaceAssistantPanel
          surface="business_insights"
          contextLabel="Personal Home"
        />
      }
      topBarRight={
        <>
          <StatusDot tone="online" className="ml-1 mr-1" />
          <Button
            variant="secondary"
            size="md"
            onClick={() => router.push("/help")}
          >
            <IconHelpCircle size={15} />
            Help
          </Button>
        </>
      }
    >
      <div className="space-y-8 px-6 pb-8">
        <header>
          <div className="mb-1.5 flex items-center gap-2 text-caption font-medium uppercase tracking-wide text-ink-tertiary">
            <IconSparkles size={14} className="text-brand-500" />
            {profile.label} perspective · Personal business briefing
          </div>
          <h1 className="text-h1 text-ink-primary">
            {user.name ? greeting(user.name) : "Home"}
          </h1>
          <p className="mt-1 max-w-4xl text-body text-ink-tertiary">
            Get started by creating a project, uploading data, or exploring
            shared resources from your team.
          </p>
        </header>

        <section className="mt-3">
          <h2 className="mb-3 text-caption font-medium uppercase tracking-wide text-ink-tertiary">
            What would you like to do?
          </h2>
          <div className="grid gap-5 sm:grid-cols-2 lg:gap-7 xl:grid-cols-4 xl:gap-11">
            {tiles.map((tile) => (
              <StarterCard key={tile.key} tile={tile} />
            ))}
          </div>
        </section>

        <p className="text-small text-ink-tertiary">
          Not sure where to start? Click{" "}
          <Link
            href="/projects"
            className="font-medium text-ink-secondary hover:text-brand-700 hover:underline"
          >
            Projects
          </Link>{" "}
          in the sidebar to browse your organization, or{" "}
          <Link
            href="/ai"
            className="font-medium text-ink-secondary hover:text-brand-700 hover:underline"
          >
            ask the AI Assistant →
          </Link>
        </p>
      </div>

      <NewProjectDialog open={showCreate} onClose={() => setShowCreate(false)} />
    </AppShell>
  );
}
