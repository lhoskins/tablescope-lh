"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/cn";
import { useProjectActionsBoard } from "./hooks/use-project-actions-board";
import { useProjectMembers } from "@/lib/ui/use-project-data";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import { Button } from "@/components/ui/button";
import { ProjectShell } from "@/components/tablescope/project-shell";
import {
  projectActionsApi,
  type ProjectActionListItem,
  type ProjectActionSubtask,
  type ProjectActionStatus,
  type ProjectActionPriority,
  type ProjectActionGroupBy,
  type ProjectActionSortBy,
  type ProjectActionView,
  type ProjectAction,
  type ProjectActionFilters,
} from "@/lib/api/project-actions";
import {
  IconArrowsSort,
  IconCalendar,
  IconCheck,
  IconChevronDown,
  IconClipboardList,
  IconDotsVertical,
  IconLoader2,
  IconPlus,
  IconSearch,
  IconTrash,
} from "@tabler/icons-react";

const STATUS_LABELS: Record<ProjectActionStatus, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  blocked: "Blocked",
  completed: "Completed",
  cancelled: "Cancelled",
};

const STATUS_COLORS: Record<ProjectActionStatus, string> = {
  not_started: "bg-neutral-100 text-neutral-700",
  in_progress: "bg-blue-100 text-blue-700",
  blocked: "bg-orange-100 text-orange-700",
  completed: "bg-green-100 text-green-700",
  cancelled: "bg-gray-100 text-gray-500",
};

const PRIORITY_LABELS: Record<ProjectActionPriority, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

const PRIORITY_COLORS: Record<ProjectActionPriority, string> = {
  low: "bg-success-bg text-success",
  medium: "bg-bg-tertiary text-ink-secondary",
  high: "bg-warning-bg text-warning",
  critical: "bg-danger-bg text-danger",
};

const DUE_STATE_LABELS: Record<string, string> = {
  overdue: "Overdue",
  due_today: "Due today",
  due_this_week: "Due this week",
  upcoming: "Upcoming",
  no_due: "No due date",
};

const SOURCE_LABELS: Record<string, string> = {
  insight: "Insight",
  manual: "Manual",
  risk: "Risk",
};

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return "";
  }
}

function isOverdue(item: {
  due_date: string | null;
  status: string;
  archived_at?: string | null;
}): boolean {
  if (!item.due_date || item.archived_at) return false;
  if (["completed", "cancelled"].includes(item.status)) return false;
  return new Date(item.due_date) < new Date();
}

function useManageActionsPermission(role?: string, isSuperAdmin?: boolean) {
  if (isSuperAdmin) return true;
  const allowed = ["editor", "admin", "tenant_admin", "root_admin"];
  return Boolean(role && allowed.includes(role.toLowerCase()));
}

export function ProjectActionsWorkspace({ projectId }: { projectId: string }) {
  const { data: identity } = useCurrentUser();
  const { data: members } = useProjectMembers(projectId);
  const router = useRouter();
  const user = identity?.user;
  const tenant = identity?.tenant;
  const canManage = useManageActionsPermission(user?.rawRole, user?.isSuperAdmin);

  const {
    prefs,
    savePrefs,
    search,
    setSearch,
    filters,
    setFilters,
    boardQuery,
    fetchDetail,
    updateAction,
    archiveAction,
    restoreAction,
    createSubtask,
    updateSubtask,
    archiveSubtask,
    bulkUpdate,
    currentUserId,
  } = useProjectActionsBoard(projectId, tenant?.slug ?? "default", user?.id);

  useEffect(() => {
    const t = setTimeout(() => setFilters((f) => ({ ...f, q: search || undefined })), 300);
    return () => clearTimeout(t);
  }, [search, setFilters]);

  const items = useMemo(() => boardQuery.data?.items ?? [], [boardQuery.data?.items]);
  const summary = useMemo(
    () =>
      boardQuery.data?.summary ?? {
        active: 0,
        overdue: 0,
        avg_progress: 0,
        risk_mitigations_completed: 0,
        groups: [],
      },
    [boardQuery.data?.summary],
  );

  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [detailMap, setDetailMap] = useState<Record<number, ProjectAction>>({});
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [addingSubtaskFor, setAddingSubtaskFor] = useState<number | null>(null);
  const [newSubtaskTitle, setNewSubtaskTitle] = useState("");

  const toggleExpand = async (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
    if (!detailMap[id]) {
      const action = await fetchDetail(id);
      setDetailMap((m) => ({ ...m, [id]: action }));
    }
  };

  const handleStatusChange = (
    id: number,
    status: ProjectActionStatus,
    version: number,
  ) => {
    updateAction.mutate({ actionId: id, payload: { status, expected_version: version } });
  };

  const handlePriorityChange = (
    id: number,
    priority: ProjectActionPriority,
    version: number,
  ) => {
    updateAction.mutate({ actionId: id, payload: { priority, expected_version: version } });
  };

  const handleOwnerChange = (
    id: number,
    owner_user_id: number | null,
    version: number,
  ) => {
    updateAction.mutate({ actionId: id, payload: { owner_user_id, expected_version: version } });
  };

  const handleDueChange = (
    id: number,
    due_date: string | null,
    version: number,
  ) => {
    updateAction.mutate({ actionId: id, payload: { due_date, expected_version: version } });
  };

  const handleArchive = (id: number) => {
    archiveAction.mutate(id);
  };

  const handleRestore = (id: number) => {
    restoreAction.mutate(id);
  };

  const handleSubtaskStatusChange = (
    actionId: number,
    subtaskId: number,
    status: ProjectActionStatus,
  ) => {
    const action = detailMap[actionId];
    const sub = action?.subtasks.find((s) => s.id === subtaskId);
    if (!sub) return;
    updateSubtask.mutate({
      actionId,
      subtaskId,
      payload: { status, expected_version: sub.lock_version },
    }, {
      onSuccess: () => fetchDetail(actionId).then((a) => setDetailMap((m) => ({ ...m, [actionId]: a }))),
    });
  };

  const handleSubtaskArchive = (actionId: number, subtaskId: number) => {
    archiveSubtask.mutate(
      { actionId, subtaskId },
      {
        onSuccess: () => fetchDetail(actionId).then((a) => setDetailMap((m) => ({ ...m, [actionId]: a }))),
      },
    );
  };

  const submitSubtask = (actionId: number) => {
    if (!newSubtaskTitle.trim()) return;
    createSubtask.mutate(
      {
        actionId,
        payload: { title: newSubtaskTitle.trim(), is_required: true, status: "not_started" },
      },
      {
        onSuccess: () => {
          setNewSubtaskTitle("");
          setAddingSubtaskFor(null);
          fetchDetail(actionId).then((a) => setDetailMap((m) => ({ ...m, [actionId]: a })));
        },
      },
    );
  };

  const grouped = useMemo(() => {
    const byKey: Record<string, ProjectActionListItem[]> = {};
    for (const item of items) {
      let key: string = item.status;
      if (prefs.groupBy === "priority") key = item.priority;
      if (prefs.groupBy === "owner") key = item.owner_user_id == null ? "unassigned" : String(item.owner_user_id);
      if (prefs.groupBy === "due_state") key = item.due_date ? (isOverdue(item) ? "overdue" : "upcoming") : "no_due";
      if (prefs.groupBy === "source_type") key = item.source_type || "none";
      if (prefs.groupBy === "none") key = "all";
      byKey[key] = byKey[key] ?? [];
      byKey[key].push(item);
    }
    return byKey;
  }, [items, prefs.groupBy]);

  const groupMeta = useMemo(() => {
    if (prefs.groupBy === "none") {
      return [{ group: "all", label: "All actions", count: items.length, overdue_count: 0, avg_progress: 0 }];
    }
    return summary.groups.map((g) => ({
      ...g,
      items: grouped[g.group] ?? [],
    })).filter((g) => g.items.length > 0 || g.count > 0);
  }, [summary.groups, grouped, items.length, prefs.groupBy]);

  const toggleGroup = (group: string) => {
    savePrefs({
      collapsedGroups: prefs.collapsedGroups.includes(group)
        ? prefs.collapsedGroups.filter((g) => g !== group)
        : [...prefs.collapsedGroups, group],
    });
  };

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-actions"
      breadcrumbLabel="Project Actions"
      actions={
        canManage ? (
          <Button
            size="sm"
            onClick={() => router.push(`/projects/${projectId}/actions/new`)}
          >
            <IconPlus size={16} className="mr-1" />
            New action
          </Button>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-4 p-4" role="treegrid" aria-label="Project actions board">
        <div className="flex flex-col gap-1">
          <h1 className="text-h1 text-ink-primary">Project Actions</h1>
          <p className="text-small text-ink-secondary">
            Manage actions created from insights and track mitigation progress.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard label="Active" value={summary.active} icon={IconClipboardList} />
          <SummaryCard label="Overdue" value={summary.overdue} icon={IconCalendar} tone="danger" />
          <SummaryCard label="Avg progress" value={`${summary.avg_progress}%`} icon={IconArrowsSort} />
          <SummaryCard
            label="Risk mitigations completed"
            value={summary.risk_mitigations_completed}
            icon={IconCheck}
            tone="success"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 border-b border-line-tertiary pb-2">
          {(["board", "my-actions", "timeline", "archived"] as ProjectActionView[]).map((view) => (
            <button
              key={view}
              type="button"
              onClick={() => savePrefs({ view })}
              className={cn(
                "rounded-md px-3 py-1.5 text-small font-medium transition-colors",
                prefs.view === view
                  ? "bg-brand-50 text-brand-700"
                  : "text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary",
              )}
            >
              {view === "board" && "Board"}
              {view === "my-actions" && "My actions"}
              {view === "timeline" && "Timeline"}
              {view === "archived" && "Archived"}
            </button>
          ))}
        </div>

        <Toolbar
          search={search}
          setSearch={setSearch}
          filters={filters}
          setFilters={setFilters}
          prefs={prefs}
          savePrefs={savePrefs}
          members={members ?? []}
          currentUserId={currentUserId}
          selected={selected}
          onBulkStatus={(status) => {
            const expected: Record<number, number> = {};
            for (const id of selected) {
              const item = items.find((i) => i.id === id);
              if (item) expected[id] = item.lock_version;
            }
            bulkUpdate.mutate({ action_ids: Array.from(selected), expected_versions: expected, status });
            setSelected(new Set());
          }}
          onArchive={() => {
            for (const id of selected) archiveAction.mutate(id);
            setSelected(new Set());
          }}
          canManage={canManage}
        />

        {boardQuery.isLoading ? (
          <div className="flex h-48 items-center justify-center text-ink-secondary">
            <IconLoader2 className="mr-2 animate-spin" size={20} />
            Loading actions...
          </div>
        ) : items.length === 0 ? (
          <div className="flex h-48 flex-col items-center justify-center rounded-md border border-dashed border-line-tertiary text-ink-secondary">
            <IconClipboardList size={32} stroke={1.2} />
            <p className="mt-2">No actions match the current filters.</p>
          </div>
        ) : (
          <div className="flex flex-col gap-3" role="rowgroup">
            {groupMeta.map((group) => (
              <GroupSection
                key={group.group}
                projectId={projectId}
                group={group}
                expanded={!prefs.collapsedGroups.includes(group.group)}
                onToggle={() => toggleGroup(group.group)}
                selected={selected}
                onSelect={toggleSelect}
                onExpand={toggleExpand}
                expandedRows={expanded}
                detailMap={detailMap}
                canManage={canManage}
                onStatusChange={handleStatusChange}
                onPriorityChange={handlePriorityChange}
                onOwnerChange={handleOwnerChange}
                onDueChange={handleDueChange}
                onArchive={handleArchive}
                onRestore={handleRestore}
                onSubtaskStatusChange={handleSubtaskStatusChange}
                onSubtaskArchive={handleSubtaskArchive}
                addingSubtaskFor={addingSubtaskFor}
                setAddingSubtaskFor={setAddingSubtaskFor}
                newSubtaskTitle={newSubtaskTitle}
                setNewSubtaskTitle={setNewSubtaskTitle}
                submitSubtask={submitSubtask}
                members={members ?? []}
                view={prefs.view}
                groupBy={prefs.groupBy}
              />
            ))}
          </div>
        )}
      </div>
    </ProjectShell>
  );
}

function SummaryCard({
  label,
  value,
  icon: Icon,
  tone,
}: {
  label: string;
  value: string | number;
  icon: typeof IconClipboardList;
  tone?: "danger" | "success";
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-line-tertiary bg-bg-primary p-3">
      <div
        className={cn(
          "flex h-10 w-10 items-center justify-center rounded-full",
          tone === "danger" && "bg-danger-bg text-danger",
          tone === "success" && "bg-success-bg text-success",
          !tone && "bg-bg-tertiary text-ink-secondary",
        )}
      >
        <Icon size={20} />
      </div>
      <div>
        <div className="text-h2 text-ink-primary">{value}</div>
        <div className="text-caption text-ink-secondary">{label}</div>
      </div>
    </div>
  );
}

function Toolbar({
  search,
  setSearch,
  filters,
  setFilters,
  prefs,
  savePrefs,
  members,
  currentUserId,
  selected,
  onBulkStatus,
  onArchive,
  canManage,
}: {
  search: string;
  setSearch: (s: string) => void;
  filters: ProjectActionFilters;
  setFilters: (f: ProjectActionFilters) => void;
  prefs: { view: ProjectActionView; groupBy: ProjectActionGroupBy; sortBy: ProjectActionSortBy; sortDirection: "asc" | "desc" };
  savePrefs: (p: Partial<typeof prefs>) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
  currentUserId?: number;
  selected: Set<number>;
  onBulkStatus: (status: ProjectActionStatus) => void;
  onArchive: () => void;
  canManage: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex items-center gap-1 rounded-md border border-line-tertiary bg-bg-primary px-2 py-1">
        <IconSearch size={14} className="text-ink-tertiary" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search actions"
          className="bg-transparent text-[13px] text-ink-primary outline-none"
          aria-label="Search actions"
        />
      </div>

      <select
        value={String(filters.owner_user_id ?? "")}
        onChange={(e) =>
          setFilters({
            ...filters,
            owner_user_id: e.target.value === "unassigned"
              ? undefined
              : e.target.value
                ? Number(e.target.value)
                : undefined,
          })
        }
        className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-[13px] text-ink-primary"
      >
        <option value="">All owners</option>
        <option value={currentUserId ?? ""}>Me</option>
        <option value="unassigned">Unassigned</option>
        {members.map((m) => (
          <option key={m.user_id} value={m.user_id}>
            {m.display_name || m.email}
          </option>
        ))}
      </select>

      <select
        value={String(filters.status ?? "")}
        onChange={(e) =>
          setFilters({ ...filters, status: (e.target.value || undefined) as ProjectActionStatus | undefined })
        }
        className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-[13px] text-ink-primary"
      >
        <option value="">All statuses</option>
        {Object.entries(STATUS_LABELS).map(([k, label]) => (
          <option key={k} value={k}>
            {label}
          </option>
        ))}
      </select>

      <select
        value={String(filters.priority ?? "")}
        onChange={(e) =>
          setFilters({ ...filters, priority: (e.target.value || undefined) as ProjectActionPriority | undefined })
        }
        className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-[13px] text-ink-primary"
      >
        <option value="">All priorities</option>
        {Object.entries(PRIORITY_LABELS).map(([k, label]) => (
          <option key={k} value={k}>
            {label}
          </option>
        ))}
      </select>

      <label className="flex items-center gap-1 text-[13px] text-ink-secondary">
        <input
          type="checkbox"
          checked={Boolean(filters.overdue)}
          onChange={(e) => setFilters({ ...filters, overdue: e.target.checked || undefined })}
        />
        Overdue only
      </label>

      <div className="ml-auto flex flex-wrap items-center gap-2">
        {selected.size > 0 && canManage && (
          <div className="flex items-center gap-2 rounded-md border border-line-tertiary bg-bg-primary px-2 py-1">
            <span className="text-small text-ink-secondary">{selected.size} selected</span>
            <select
              value=""
              onChange={(e) => e.target.value && onBulkStatus(e.target.value as ProjectActionStatus)}
              className="bg-transparent text-[13px] text-ink-primary outline-none"
            >
              <option value="">Change status</option>
              {Object.entries(STATUS_LABELS).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={onArchive}
              className="text-small text-danger hover:text-danger-700"
            >
              Archive
            </button>
          </div>
        )}

        <select
          value={prefs.groupBy}
          onChange={(e) => savePrefs({ groupBy: e.target.value as ProjectActionGroupBy })}
          className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-[13px] text-ink-primary"
        >
          <option value="status">Group by status</option>
          <option value="priority">Group by priority</option>
          <option value="owner">Group by owner</option>
          <option value="due_state">Group by due date</option>
          <option value="source_type">Group by source</option>
          <option value="none">No grouping</option>
        </select>

        <select
          value={`${prefs.sortBy}:${prefs.sortDirection}`}
          onChange={(e) => {
            const [sortBy, sortDirection] = e.target.value.split(":") as [ProjectActionSortBy, "asc" | "desc"];
            savePrefs({ sortBy, sortDirection });
          }}
          className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-[13px] text-ink-primary"
        >
          <option value="updated:desc">Sort by updated</option>
          <option value="created:desc">Sort by created</option>
          <option value="due_date:asc">Sort by due date</option>
          <option value="priority:asc">Sort by priority</option>
          <option value="progress:desc">Sort by progress</option>
          <option value="title:asc">Sort by title</option>
        </select>
      </div>
    </div>
  );
}

function GroupSection({
  projectId,
  group,
  expanded,
  onToggle,
  selected,
  onSelect,
  onExpand,
  expandedRows,
  detailMap,
  canManage,
  onStatusChange,
  onPriorityChange,
  onOwnerChange,
  onDueChange,
  onArchive,
  onRestore,
  onSubtaskStatusChange,
  onSubtaskArchive,
  addingSubtaskFor,
  setAddingSubtaskFor,
  newSubtaskTitle,
  setNewSubtaskTitle,
  submitSubtask,
  members,
  view,
  groupBy,
}: {
  projectId: string;
  group: {
    group: string;
    label: string;
    count: number;
    overdue_count: number;
    avg_progress: number;
    items?: ProjectActionListItem[];
  };
  expanded: boolean;
  onToggle: () => void;
  selected: Set<number>;
  onSelect: (id: number) => void;
  onExpand: (id: number) => void;
  expandedRows: Set<number>;
  detailMap: Record<number, ProjectAction>;
  canManage: boolean;
  onStatusChange: (id: number, status: ProjectActionStatus, version: number) => void;
  onPriorityChange: (id: number, priority: ProjectActionPriority, version: number) => void;
  onOwnerChange: (id: number, owner: number | null, version: number) => void;
  onDueChange: (id: number, due: string | null, version: number) => void;
  onArchive: (id: number) => void;
  onRestore: (id: number) => void;
  onSubtaskStatusChange: (actionId: number, subtaskId: number, status: ProjectActionStatus) => void;
  onSubtaskArchive: (actionId: number, subtaskId: number) => void;
  addingSubtaskFor: number | null;
  setAddingSubtaskFor: (id: number | null) => void;
  newSubtaskTitle: string;
  setNewSubtaskTitle: (s: string) => void;
  submitSubtask: (actionId: number) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
  view: ProjectActionView;
  groupBy: ProjectActionGroupBy;
}) {
  const allSelected = group.items && group.items.length > 0 && group.items.every((i) => selected.has(i.id));
  return (
    <div className="rounded-lg border border-line-tertiary bg-bg-primary" role="rowgroup" aria-label={group.label}>
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-bg-secondary"
        aria-expanded={expanded}
      >
        <div className="flex items-center gap-2">
          <IconChevronDown
            size={16}
            className={cn("text-ink-tertiary transition-transform", !expanded && "-rotate-90")}
          />
          <span className="text-small font-semibold text-ink-primary">{group.label}</span>
          <span className="rounded-full bg-bg-tertiary px-2 text-[11px] text-ink-secondary">{group.count}</span>
          {group.overdue_count > 0 && (
            <span className="text-[11px] text-danger">{group.overdue_count} overdue</span>
          )}
        </div>
        <div className="text-[12px] text-ink-secondary">
          Avg progress {group.avg_progress}%
        </div>
      </button>

      {expanded && (
        <div className="border-t border-line-tertiary">
          {group.items?.map((item) => (
            <ActionRow
              key={item.id}
              projectId={projectId}
              item={item}
              selected={selected.has(item.id)}
              onSelect={() => onSelect(item.id)}
              expanded={expandedRows.has(item.id)}
              onExpand={() => onExpand(item.id)}
              detail={detailMap[item.id]}
              canManage={canManage}
              onStatusChange={onStatusChange}
              onPriorityChange={onPriorityChange}
              onOwnerChange={onOwnerChange}
              onDueChange={onDueChange}
              onArchive={onArchive}
              onRestore={onRestore}
              onSubtaskStatusChange={onSubtaskStatusChange}
              onSubtaskArchive={onSubtaskArchive}
              addingSubtaskFor={addingSubtaskFor}
              setAddingSubtaskFor={setAddingSubtaskFor}
              newSubtaskTitle={newSubtaskTitle}
              setNewSubtaskTitle={setNewSubtaskTitle}
              submitSubtask={submitSubtask}
              members={members}
              view={view}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ActionRow({
  projectId,
  item,
  selected,
  onSelect,
  expanded,
  onExpand,
  detail,
  canManage,
  onStatusChange,
  onPriorityChange,
  onOwnerChange,
  onDueChange,
  onArchive,
  onRestore,
  onSubtaskStatusChange,
  onSubtaskArchive,
  addingSubtaskFor,
  setAddingSubtaskFor,
  newSubtaskTitle,
  setNewSubtaskTitle,
  submitSubtask,
  members,
  view,
}: {
  projectId: string;
  item: ProjectActionListItem;
  selected: boolean;
  onSelect: () => void;
  expanded: boolean;
  onExpand: () => void;
  detail?: ProjectAction;
  canManage: boolean;
  onStatusChange: (id: number, status: ProjectActionStatus, version: number) => void;
  onPriorityChange: (id: number, priority: ProjectActionPriority, version: number) => void;
  onOwnerChange: (id: number, owner: number | null, version: number) => void;
  onDueChange: (id: number, due: string | null, version: number) => void;
  onArchive: (id: number) => void;
  onRestore: (id: number) => void;
  onSubtaskStatusChange: (actionId: number, subtaskId: number, status: ProjectActionStatus) => void;
  onSubtaskArchive: (actionId: number, subtaskId: number) => void;
  addingSubtaskFor: number | null;
  setAddingSubtaskFor: (id: number | null) => void;
  newSubtaskTitle: string;
  setNewSubtaskTitle: (s: string) => void;
  submitSubtask: (actionId: number) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
  view: ProjectActionView;
}) {
  const progress = item.percent_complete ?? 0;
  const overdue = isOverdue(item);
  const activeSubtasks = detail?.subtasks.filter((s) => !s.archived_at) ?? [];

  return (
    <div className="border-b border-line-tertiary last:border-b-0" role="row" aria-expanded={expanded}>
      <div
        className={cn(
          "grid cursor-pointer items-center gap-2 px-3 py-2 transition-colors hover:bg-bg-secondary",
          "grid-cols-[28px_24px_1fr_120px_120px_100px_110px_80px_120px_100px_32px]",
        )}
        onClick={(e) => {
          if ((e.target as HTMLElement).closest("button, select, input, a")) return;
          onExpand();
        }}
      >
        <input
          type="checkbox"
          checked={selected}
          onChange={onSelect}
          onClick={(e) => e.stopPropagation()}
          aria-label={`Select ${item.title}`}
        />
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onExpand();
          }}
          aria-label={expanded ? "Collapse subtasks" : "Expand subtasks"}
        >
          {activeSubtasks.length > 0 ? (
            <IconChevronDown
              size={16}
              className={cn("text-ink-tertiary transition-transform", !expanded && "-rotate-90")}
            />
          ) : (
            <span className="inline-block w-4" />
          )}
        </button>

        <div className="flex min-w-0 flex-col">
          <Link
            href={`/projects/${projectId}/actions/${item.id}`}
            className="truncate text-[13px] font-medium text-ink-primary hover:text-brand-600 hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            {item.title}
          </Link>
          {item.description && (
            <span className="truncate text-[12px] text-ink-tertiary">{item.description}</span>
          )}
        </div>

        <OwnerCell
          value={item.owner_user_id}
          members={members}
          canManage={canManage}
          onChange={(v) => onOwnerChange(item.id, v, item.lock_version)}
        />

        <StatusCell
          value={item.status}
          canManage={canManage}
          onChange={(v) => onStatusChange(item.id, v, item.lock_version)}
        />

        <PriorityCell
          value={item.priority}
          canManage={canManage}
          onChange={(v) => onPriorityChange(item.id, v, item.lock_version)}
        />

        <div className="flex items-center gap-2 text-[12px] text-ink-secondary">
          <div className="h-2 w-16 overflow-hidden rounded-full bg-bg-tertiary">
            <div
              className="h-full bg-brand-500"
              style={{ width: `${progress}%` }}
            />
          </div>
          {progress}%
        </div>

        <input
          type="date"
          value={item.due_date ? item.due_date.split("T")[0] : ""}
          onChange={(e) => onDueChange(item.id, e.target.value || null, item.lock_version)}
          disabled={!canManage}
          className={cn(
            "rounded border px-1 py-0.5 text-[12px]",
            overdue ? "border-danger text-danger" : "border-line-tertiary text-ink-secondary",
            !canManage && "bg-bg-secondary opacity-60",
          )}
        />

        <div className="text-[12px] text-ink-secondary">
          {item.risk_impact ? `Risk ${item.risk_impact}` : SOURCE_LABELS[item.source_type] ?? item.source_type}
        </div>

        <div className="text-[12px] text-ink-tertiary">
          {formatDate(item.updated_at)}
        </div>

        <RowMenu
          projectId={projectId}
          item={item}
          canManage={canManage}
          onArchive={() => onArchive(item.id)}
          onRestore={() => onRestore(item.id)}
        />
      </div>

      {expanded && (
        <div className="bg-bg-secondary px-12 py-3">
          <SubtaskPanel
            actionId={item.id}
            subtasks={activeSubtasks}
            detail={detail}
            canManage={canManage}
            onStatusChange={onSubtaskStatusChange}
            onArchive={onSubtaskArchive}
            addingSubtaskFor={addingSubtaskFor}
            setAddingSubtaskFor={setAddingSubtaskFor}
            newSubtaskTitle={newSubtaskTitle}
            setNewSubtaskTitle={setNewSubtaskTitle}
            submitSubtask={submitSubtask}
            members={members}
          />
        </div>
      )}
    </div>
  );
}

function OwnerCell({
  value,
  members,
  canManage,
  onChange,
}: {
  value: number | null;
  members: { user_id: number; display_name: string | null; email: string }[];
  canManage: boolean;
  onChange: (v: number | null) => void;
}) {
  const selected = members.find((m) => m.user_id === value);
  if (!canManage) {
    return <span className="truncate text-[12px] text-ink-secondary">{selected ? selected.display_name || selected.email : "Unassigned"}</span>;
  }
  return (
    <select
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      className="w-full rounded border border-line-tertiary bg-bg-primary px-1 py-0.5 text-[12px] text-ink-primary"
    >
      <option value="">Unassigned</option>
      {members.map((m) => (
        <option key={m.user_id} value={m.user_id}>
          {m.display_name || m.email}
        </option>
      ))}
    </select>
  );
}

function StatusCell({
  value,
  canManage,
  onChange,
}: {
  value: ProjectActionStatus;
  canManage: boolean;
  onChange: (v: ProjectActionStatus) => void;
}) {
  if (!canManage) {
    return <span className={cn("rounded px-2 py-0.5 text-[11px] font-medium", STATUS_COLORS[value])}>{STATUS_LABELS[value]}</span>;
  }
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as ProjectActionStatus)}
      className={cn(
        "rounded px-2 py-0.5 text-[11px] font-medium outline-none",
        STATUS_COLORS[value],
      )}
    >
      {Object.entries(STATUS_LABELS).map(([k, label]) => (
        <option key={k} value={k}>
          {label}
        </option>
      ))}
    </select>
  );
}

function PriorityCell({
  value,
  canManage,
  onChange,
}: {
  value: ProjectActionPriority;
  canManage: boolean;
  onChange: (v: ProjectActionPriority) => void;
}) {
  if (!canManage) {
    return <span className={cn("rounded px-2 py-0.5 text-[11px] font-medium", PRIORITY_COLORS[value])}>{PRIORITY_LABELS[value]}</span>;
  }
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as ProjectActionPriority)}
      className={cn("rounded px-2 py-0.5 text-[11px] font-medium outline-none", PRIORITY_COLORS[value])}
    >
      {Object.entries(PRIORITY_LABELS).map(([k, label]) => (
        <option key={k} value={k}>
          {label}
        </option>
      ))}
    </select>
  );
}

function RowMenu({
  projectId,
  item,
  canManage,
  onArchive,
  onRestore,
}: {
  projectId: string;
  item: ProjectActionListItem;
  canManage: boolean;
  onArchive: () => void;
  onRestore: () => void;
}) {
  const [open, setOpen] = useState(false);
  if (!canManage) return <span className="w-8" />;
  return (
    <div className="relative">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(!open);
        }}
        aria-label="Action menu"
      >
        <IconDotsVertical size={16} className="text-ink-tertiary" />
      </button>
      {open && (
        <div className="absolute right-0 top-6 z-10 w-40 rounded-md border border-line-tertiary bg-bg-primary py-1 shadow-md">
          <Link
            href={`/projects/${projectId}/actions/${item.id}`}
            className="block px-3 py-1.5 text-[12px] text-ink-primary hover:bg-bg-secondary"
            onClick={() => setOpen(false)}
          >
            Open details
          </Link>
          {item.archived_at ? (
            <button
              type="button"
              onClick={() => {
                onRestore();
                setOpen(false);
              }}
              className="block w-full px-3 py-1.5 text-left text-[12px] text-ink-primary hover:bg-bg-secondary"
            >
              Restore
            </button>
          ) : (
            <button
              type="button"
              onClick={() => {
                onArchive();
                setOpen(false);
              }}
              className="block w-full px-3 py-1.5 text-left text-[12px] text-danger hover:bg-bg-secondary"
            >
              Archive
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function SubtaskPanel({
  actionId,
  subtasks,
  detail,
  canManage,
  onStatusChange,
  onArchive,
  addingSubtaskFor,
  setAddingSubtaskFor,
  newSubtaskTitle,
  setNewSubtaskTitle,
  submitSubtask,
  members,
}: {
  actionId: number;
  subtasks: ProjectActionSubtask[];
  detail?: ProjectAction;
  canManage: boolean;
  onStatusChange: (actionId: number, subtaskId: number, status: ProjectActionStatus) => void;
  onArchive: (actionId: number, subtaskId: number) => void;
  addingSubtaskFor: number | null;
  setAddingSubtaskFor: (id: number | null) => void;
  newSubtaskTitle: string;
  setNewSubtaskTitle: (s: string) => void;
  submitSubtask: (actionId: number) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
}) {
  return (
    <div className="rounded-md border border-line-tertiary bg-bg-primary">
      <div className="grid grid-cols-[28px_1fr_120px_110px_110px_80px_32px] gap-2 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-tertiary">
        <span />
        <span>Subtask</span>
        <span>Owner</span>
        <span>Status</span>
        <span>Due</span>
        <span>Effort</span>
        <span />
      </div>
      {subtasks.map((sub) => (
        <div
          key={sub.id}
          className="grid grid-cols-[28px_1fr_120px_110px_110px_80px_32px] items-center gap-2 border-t border-line-tertiary px-3 py-1.5"
        >
          <input
            type="checkbox"
            checked={sub.status === "completed"}
            disabled={!canManage}
            onChange={(e) =>
              onStatusChange(actionId, sub.id, e.target.checked ? "completed" : "not_started")
            }
            aria-label={`Mark ${sub.title} complete`}
          />
          <span className="truncate text-[12px] text-ink-primary">{sub.title}</span>
          <span className="truncate text-[12px] text-ink-secondary">
            {members.find((m) => m.user_id === sub.owner_user_id)?.display_name ??
              members.find((m) => m.user_id === sub.owner_user_id)?.email ??
              "Unassigned"}
          </span>
          <StatusCell
            value={sub.status}
            canManage={canManage}
            onChange={(v) => onStatusChange(actionId, sub.id, v)}
          />
          <span className="text-[12px] text-ink-secondary">{formatDate(sub.due_date)}</span>
          <span className="text-[12px] text-ink-secondary">{sub.effort_points ?? "-"}</span>
          {canManage && (
            <button
              type="button"
              onClick={() => onArchive(actionId, sub.id)}
              aria-label={`Archive ${sub.title}`}
            >
              <IconTrash size={14} className="text-ink-tertiary hover:text-danger" />
            </button>
          )}
        </div>
      ))}

      {canManage && (
        <div className="border-t border-line-tertiary px-3 py-2">
          {addingSubtaskFor === actionId ? (
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={newSubtaskTitle}
                onChange={(e) => setNewSubtaskTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") submitSubtask(actionId);
                  if (e.key === "Escape") setAddingSubtaskFor(null);
                }}
                placeholder="Subtask title"
                className="flex-1 rounded border border-line-tertiary bg-bg-primary px-2 py-1 text-[13px]"
                autoFocus
              />
              <button
                type="button"
                onClick={() => submitSubtask(actionId)}
                className="text-[13px] text-brand-600 hover:text-brand-700"
              >
                Add
              </button>
              <button
                type="button"
                onClick={() => setAddingSubtaskFor(null)}
                className="text-[13px] text-ink-secondary hover:text-ink-primary"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setAddingSubtaskFor(actionId)}
              className="flex items-center gap-1 text-[13px] text-brand-600 hover:text-brand-700"
            >
              <IconPlus size={14} /> Add subitem
            </button>
          )}
        </div>
      )}
    </div>
  );
}
