"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/cn";
import { initials, timeAgo } from "@/lib/ui/format";
import { useProjectActionsBoard } from "./hooks/use-project-actions-board";
import { useProjectMembers } from "@/lib/ui/use-project-data";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { useToasts } from "@/components/ui/toast";
import {
  type ProjectActionListItem,
  type ProjectActionSubtask,
  type ProjectActionStatus,
  type ProjectActionPriority,
  type ProjectActionGroupBy,
  type ProjectActionSortBy,
  type ProjectActionView,
  type ProjectAction,
  type ProjectActionFilters,
  type ProjectActionGroupSummary,
} from "@/lib/api/project-actions";
import {
  IconPlus,
  IconSearch,
  IconUserCircle,
  IconFilter,
  IconArrowsSort,
  IconChevronDown,
  IconChevronRight,
  IconMessage,
  IconDotsVertical,
  IconLoader2,
  IconClipboardList,
  IconClock,
  IconTrendingUp,
  IconShieldCheck,
  IconSparkles,
  IconTable,
  IconCheck,
  IconCalendar,
  IconTrash,
} from "@tabler/icons-react";

const STATUS_ORDER: ProjectActionStatus[] = [
  "blocked",
  "in_progress",
  "not_started",
  "completed",
  "cancelled",
];

const STATUS_BADGE_LABELS: Record<ProjectActionStatus, string> = {
  not_started: "Not started",
  in_progress: "Working on it",
  blocked: "Blocked",
  completed: "Done",
  cancelled: "Cancelled",
};

const STATUS_COLORS: Record<ProjectActionStatus, string> = {
  not_started: "bg-bg-tertiary text-ink-secondary",
  in_progress: "bg-warning-bg text-warning",
  blocked: "bg-danger-bg text-danger",
  completed: "bg-success-bg text-success",
  cancelled: "bg-bg-tertiary text-ink-tertiary",
};

const STATUS_DOT_COLORS: Record<ProjectActionStatus, string> = {
  not_started: "bg-neutral-400",
  in_progress: "bg-amber-500",
  blocked: "bg-orange-500",
  completed: "bg-emerald-500",
  cancelled: "bg-gray-400",
};

const PRIORITY_LABELS: Record<ProjectActionPriority, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

const PRIORITY_COLORS: Record<ProjectActionPriority, string> = {
  low: "bg-success-bg text-success",
  medium: "bg-brand-50 text-brand-700",
  high: "bg-warning-bg text-warning",
  critical: "bg-danger-bg text-danger",
};

const SOURCE_TYPE_LABELS: Record<string, string> = {
  insight: "Insight",
  manual: "Manual",
  risk: "Risk",
};

const GROUP_LABELS: Record<string, string> = {
  blocked: "Blocked",
  in_progress: "In progress",
  not_started: "Not started",
  completed: "Completed",
  cancelled: "Cancelled",
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  overdue: "Overdue",
  due_today: "Due today",
  due_this_week: "Due this week",
  upcoming: "Upcoming",
  no_due: "No due date",
  insight: "Insight",
  manual: "Manual",
  risk: "Risk",
  unassigned: "Unassigned",
  none: "None",
  all: "All actions",
};

const SORT_OPTIONS: {
  key: string;
  label: string;
  sortBy: ProjectActionSortBy;
  sortDirection: "asc" | "desc";
}[] = [
  { key: "updated:desc", label: "Updated (newest)", sortBy: "updated", sortDirection: "desc" },
  { key: "updated:asc", label: "Updated (oldest)", sortBy: "updated", sortDirection: "asc" },
  { key: "created:desc", label: "Created (newest)", sortBy: "created", sortDirection: "desc" },
  { key: "due_date:asc", label: "Due date (soonest)", sortBy: "due_date", sortDirection: "asc" },
  { key: "priority:asc", label: "Priority (high first)", sortBy: "priority", sortDirection: "asc" },
  { key: "progress:desc", label: "Progress (most complete)", sortBy: "progress", sortDirection: "desc" },
  { key: "title:asc", label: "Title (A–Z)", sortBy: "title", sortDirection: "asc" },
];

const COLUMNS: { key: string; label: string; width: string }[] = [
  { key: "owner", label: "Owner", width: "140px" },
  { key: "status", label: "Status", width: "120px" },
  { key: "priority", label: "Priority", width: "100px" },
  { key: "progress", label: "Progress", width: "130px" },
  { key: "due", label: "Due date", width: "110px" },
  { key: "risk", label: "Risk impact", width: "120px" },
  { key: "source", label: "Source insight", width: "170px" },
  { key: "updated", label: "Updated", width: "90px" },
];

const RISK_IMPACT_OPTIONS = [
  { value: "", label: "All risk impacts" },
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
  { value: "watch", label: "Watch" },
  { value: "warning", label: "Warning" },
];

const SOURCE_TYPE_OPTIONS = [
  { value: "", label: "All sources" },
  { value: "insight", label: "Insight" },
  { value: "manual", label: "Manual" },
  { value: "risk", label: "Risk" },
];

function formatDateShort(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
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

function canManageActions(role?: string, isSuperAdmin?: boolean): boolean {
  if (isSuperAdmin) return true;
  const allowed = ["editor", "admin", "tenant_admin", "root_admin"];
  return Boolean(role && allowed.includes(role.toLowerCase()));
}

function riskImpactTone(impact: string | null | undefined): "neutral" | "danger" | "warning" | "brand" | "success" {
  if (!impact) return "neutral";
  const v = impact.toLowerCase();
  if (v.includes("critical")) return "danger";
  if (v.includes("high")) return "danger";
  if (v.includes("warning")) return "warning";
  if (v.includes("medium")) return "warning";
  if (v.includes("watch")) return "brand";
  if (v.includes("low")) return "success";
  return "neutral";
}

function riskImpactLabel(impact: string | null | undefined): string {
  if (!impact) return "";
  const v = impact.toLowerCase();
  if (v === "critical") return "Critical risk";
  if (v === "high") return "High risk";
  if (v === "medium") return "Medium risk";
  if (v === "low") return "Low risk";
  if (v === "watch") return "Watch";
  if (v === "warning") return "Warning";
  return impact.charAt(0).toUpperCase() + impact.slice(1);
}

function groupTone(group: string): "brand" | "warning" | "danger" | "success" | "neutral" {
  const v = group.toLowerCase();
  if (v === "in_progress" || v === "high") return "warning";
  if (v === "blocked" || v === "critical" || v === "overdue") return "danger";
  if (v === "completed" || v === "low") return "success";
  if (v === "not_started" || v === "medium") return "brand";
  return "neutral";
}

function useGridTemplate(visibleColumns: string[]) {
  return useMemo(() => {
    const widths = ["40px"];
    widths.push("minmax(220px, 1fr)");
    for (const col of COLUMNS) {
      if (visibleColumns.includes(col.key)) widths.push(col.width);
    }
    widths.push("44px");
    return widths.join(" ");
  }, [visibleColumns]);
}

export function ProjectActionsWorkspace({ projectId }: { projectId: string }) {
  const { data: identity } = useCurrentUser();
  const { data: members = [] } = useProjectMembers(projectId);
  const { push: pushToast } = useToasts();
  const user = identity?.user;
  const tenant = identity?.tenant;
  const canManage = canManageActions(user?.rawRole, user?.isSuperAdmin);

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
    createAction,
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
  const [addingGroup, setAddingGroup] = useState<string | null>(null);
  const [newActionTitle, setNewActionTitle] = useState("");

  const gridTemplate = useGridTemplate(prefs.visibleColumns);

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

  const handleStatusChange = (id: number, status: ProjectActionStatus, version: number) => {
    updateAction.mutate({ actionId: id, payload: { status, expected_version: version } });
  };

  const handlePriorityChange = (id: number, priority: ProjectActionPriority, version: number) => {
    updateAction.mutate({ actionId: id, payload: { priority, expected_version: version } });
  };

  const handleOwnerChange = (id: number, owner_user_id: number | null, version: number) => {
    updateAction.mutate({ actionId: id, payload: { owner_user_id, expected_version: version } });
  };

  const handleDueChange = (id: number, due_date: string | null, version: number) => {
    updateAction.mutate({ actionId: id, payload: { due_date, expected_version: version } });
  };

  const handleArchive = (id: number) => archiveAction.mutate(id);
  const handleRestore = (id: number) => restoreAction.mutate(id);

  const handleSubtaskStatusChange = (actionId: number, subtaskId: number, status: ProjectActionStatus) => {
    const action = detailMap[actionId];
    const sub = action?.subtasks.find((s) => s.id === subtaskId);
    if (!sub) return;
    updateSubtask.mutate(
      { actionId, subtaskId, payload: { status, expected_version: sub.lock_version } },
      {
        onSuccess: () => fetchDetail(actionId).then((a) => setDetailMap((m) => ({ ...m, [actionId]: a }))),
      },
    );
  };

  const handleSubtaskFieldChange = (
    actionId: number,
    subtaskId: number,
    payload: Partial<{
      owner_user_id: number | null;
      due_date: string | null;
      effort_points: number | null;
      status: ProjectActionStatus;
    }>,
  ) => {
    const action = detailMap[actionId];
    const sub = action?.subtasks.find((s) => s.id === subtaskId);
    if (!sub) return;
    updateSubtask.mutate(
      { actionId, subtaskId, payload: { ...payload, expected_version: sub.lock_version } },
      {
        onSuccess: () => fetchDetail(actionId).then((a) => setDetailMap((m) => ({ ...m, [actionId]: a }))),
      },
    );
  };

  const handleSubtaskArchive = (actionId: number, subtaskId: number) => {
    const action = detailMap[actionId];
    const sub = action?.subtasks.find((s) => s.id === subtaskId);
    if (!sub) return;
    archiveSubtask.mutate(
      { actionId, subtaskId, expected_version: sub.lock_version },
      {
        onSuccess: () => fetchDetail(actionId).then((a) => setDetailMap((m) => ({ ...m, [actionId]: a }))),
      },
    );
  };

  const submitSubtask = (actionId: number, title: string) => {
    if (!title.trim()) return;
    createSubtask.mutate(
      { actionId, payload: { title: title.trim(), is_required: true, status: "not_started" } },
      {
        onSuccess: () => {
          setDetailMap((m) => {
            const copy = { ...m };
            delete copy[actionId];
            return copy;
          });
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
    const keys = new Set<string>();
    for (const g of summary.groups) keys.add(g.group);
    if (addingGroup) keys.add(addingGroup);

    const order = Array.from(keys).sort((a, b) => {
      if (prefs.groupBy === "status") {
        const ai = STATUS_ORDER.indexOf(a as ProjectActionStatus);
        const bi = STATUS_ORDER.indexOf(b as ProjectActionStatus);
        if (ai !== -1 && bi !== -1) return ai - bi;
        if (ai !== -1) return -1;
        if (bi !== -1) return 1;
      }
      if (prefs.groupBy === "priority") {
        const orderP = ["critical", "high", "medium", "low"];
        const ai = orderP.indexOf(a);
        const bi = orderP.indexOf(b);
        if (ai !== -1 && bi !== -1) return ai - bi;
      }
      return a.localeCompare(b);
    });

    return order.map((key) => {
      const found = summary.groups.find((g) => g.group === key);
      return {
        group: key,
        label: found?.label ?? GROUP_LABELS[key] ?? key,
        count: found?.count ?? 0,
        overdue_count: found?.overdue_count ?? 0,
        avg_progress: found?.avg_progress ?? 0,
        items: grouped[key] ?? [],
      };
    });
  }, [summary.groups, grouped, addingGroup, prefs.groupBy]);

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

  const togglePersonFilter = () => {
    setFilters((f) => ({
      ...f,
      owner_user_id: f.owner_user_id === currentUserId ? undefined : currentUserId,
    }));
  };

  const startAdding = (group: string) => {
    setAddingGroup(group);
    setNewActionTitle("");
    if (prefs.collapsedGroups.includes(group)) {
      savePrefs({
        collapsedGroups: prefs.collapsedGroups.filter((g) => g !== group),
      });
    }
  };

  const submitNewAction = (group: string, title: string) => {
    if (!title.trim()) return;
    const isStatusGroup = prefs.groupBy === "status" && STATUS_ORDER.includes(group as ProjectActionStatus);
    createAction.mutate(
      {
        title: title.trim(),
        status: isStatusGroup ? (group as ProjectActionStatus) : "not_started",
        priority: "medium",
        source_type: "manual",
      },
      {
        onSuccess: () => {
          setAddingGroup(null);
          setNewActionTitle("");
        },
        onError: (err: Error) => pushToast(err.message, "error"),
      },
    );
  };

  const toggleColumn = (key: string) => {
    savePrefs({
      visibleColumns: prefs.visibleColumns.includes(key)
        ? prefs.visibleColumns.filter((k) => k !== key)
        : [...prefs.visibleColumns, key],
    });
  };

  const handleBulkStatus = (status: ProjectActionStatus) => {
    const expected: Record<number, number> = {};
    for (const id of selected) {
      const item = items.find((i) => i.id === id);
      if (item) expected[id] = item.lock_version;
    }
    bulkUpdate.mutate({ action_ids: Array.from(selected), expected_versions: expected, status });
    setSelected(new Set());
  };

  const handleBulkArchive = () => {
    for (const id of selected) archiveAction.mutate(id);
    setSelected(new Set());
  };

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-actions"
      breadcrumbLabel="Project Actions"
    >
      <div className="flex flex-col gap-5 p-4" role="treegrid" aria-label="Project actions board">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold text-ink-primary">Project Actions</h1>
            <p className="text-[13px] text-ink-secondary">
              Manage actions created from insights and track mitigation progress.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <SummaryCard value={summary.active} label="Active" icon={IconClipboardList} tone="brand" />
            <SummaryCard value={summary.overdue} label="Overdue" icon={IconClock} tone="danger" />
            <SummaryCard value={`${summary.avg_progress}%`} label="Avg progress" icon={IconTrendingUp} tone="brand" />
            <SummaryCard
              value={summary.risk_mitigations_completed}
              label="Risks mitigated"
              icon={IconShieldCheck}
              tone="success"
            />
          </div>
        </div>

        <div className="flex border-b border-line-tertiary">
          {(["board", "my-actions", "timeline", "archived"] as ProjectActionView[]).map((view) => (
            <button
              key={view}
              type="button"
              onClick={() => savePrefs({ view })}
              className={cn(
                "px-4 py-2 text-[13px] font-medium transition-colors",
                prefs.view === view
                  ? "border-b-2 border-brand-500 text-brand-600"
                  : "text-ink-secondary hover:text-ink-primary",
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
          members={members}
          currentUserId={currentUserId}
          visibleColumns={prefs.visibleColumns}
          toggleColumn={toggleColumn}
          canManage={canManage}
          personActive={filters.owner_user_id === currentUserId && currentUserId !== undefined}
          onTogglePerson={togglePersonFilter}
          onNewAction={() => startAdding("not_started")}
        />

        {selected.size > 0 && canManage && (
          <div className="flex items-center gap-3 rounded-md border border-line-tertiary bg-bg-secondary/60 px-3 py-2 text-[13px]">
            <span className="font-medium text-ink-primary">{selected.size} selected</span>
            <select
              value=""
              onChange={(e) => e.target.value && handleBulkStatus(e.target.value as ProjectActionStatus)}
              className="rounded border border-line-tertiary bg-bg-primary px-2 py-1 text-[12px] text-ink-primary"
            >
              <option value="">Change status</option>
              {Object.entries(STATUS_BADGE_LABELS).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={handleBulkArchive}
              className="text-[12px] text-danger hover:text-danger-700"
            >
              Archive
            </button>
          </div>
        )}

        {boardQuery.isLoading ? (
          <div className="flex h-48 items-center justify-center text-ink-secondary">
            <IconLoader2 className="mr-2 animate-spin" size={20} />
            Loading actions...
          </div>
        ) : items.length === 0 ? (
          <div className="flex h-48 flex-col items-center justify-center rounded-lg border border-dashed border-line-tertiary text-ink-secondary">
            <IconClipboardList size={32} stroke={1.2} />
            <p className="mt-2 text-[13px]">No actions match the current filters.</p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {groupMeta.map((group) => (
              <GroupSection
                key={group.group}
                projectId={projectId}
                group={group}
                expanded={!prefs.collapsedGroups.includes(group.group)}
                onToggle={() => toggleGroup(group.group)}
                gridTemplate={gridTemplate}
                visibleColumns={prefs.visibleColumns}
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
                onSubtaskFieldChange={handleSubtaskFieldChange}
                onSubtaskArchive={handleSubtaskArchive}
                onAddSubtask={submitSubtask}
                members={members}
                adding={addingGroup === group.group}
                newActionTitle={newActionTitle}
                setNewActionTitle={setNewActionTitle}
                onAddAction={() => startAdding(group.group)}
                onSubmitNewAction={submitNewAction}
                onCancelAdd={() => setAddingGroup(null)}
              />
            ))}
          </div>
        )}
      </div>
    </ProjectShell>
  );
}

function SummaryCard({
  value,
  label,
  icon: Icon,
  tone,
}: {
  value: string | number;
  label: string;
  icon: typeof IconClipboardList;
  tone: "brand" | "danger" | "success";
}) {
  const toneClass =
    tone === "brand"
      ? "text-brand-600"
      : tone === "danger"
        ? "text-danger"
        : "text-success";
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-line-tertiary bg-bg-primary p-3 shadow-sm">
      <Icon size={18} className={toneClass} />
      <div className="text-xl font-semibold text-ink-primary">{value}</div>
      <div className="text-[12px] text-ink-secondary">{label}</div>
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
  visibleColumns,
  toggleColumn,
  canManage,
  personActive,
  onTogglePerson,
  onNewAction,
}: {
  search: string;
  setSearch: (s: string) => void;
  filters: ProjectActionFilters;
  setFilters: (f: ProjectActionFilters) => void;
  prefs: {
    view: ProjectActionView;
    groupBy: ProjectActionGroupBy;
    sortBy: ProjectActionSortBy;
    sortDirection: "asc" | "desc";
    visibleColumns: string[];
  };
  savePrefs: (p: Partial<typeof prefs>) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
  currentUserId?: number;
  visibleColumns: string[];
  toggleColumn: (k: string) => void;
  canManage: boolean;
  personActive: boolean;
  onTogglePerson: () => void;
  onNewAction: () => void;
}) {
  const activeSort = SORT_OPTIONS.find(
    (s) => s.sortBy === prefs.sortBy && s.sortDirection === prefs.sortDirection,
  );

  const [filterOpen, setFilterOpen] = useState(false);
  const [sortOpen, setSortOpen] = useState(false);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const filterRef = useRef<HTMLDivElement>(null);
  const sortRef = useRef<HTMLDivElement>(null);
  const columnsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (filterRef.current && !filterRef.current.contains(e.target as Node)) setFilterOpen(false);
      if (sortRef.current && !sortRef.current.contains(e.target as Node)) setSortOpen(false);
      if (columnsRef.current && !columnsRef.current.contains(e.target as Node)) setColumnsOpen(false);
    }
    if (filterOpen || sortOpen || columnsOpen) {
      document.addEventListener("mousedown", handleClick);
      return () => document.removeEventListener("mousedown", handleClick);
    }
  }, [filterOpen, sortOpen, columnsOpen]);

  return (
    <div className="flex flex-wrap items-center gap-2">
      {canManage && (
        <Button size="sm" onClick={onNewAction}>
          <IconPlus size={16} />
          New action
          <IconChevronDown size={14} />
        </Button>
      )}

      <div className="flex items-center gap-1.5 rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5">
        <IconSearch size={14} className="text-ink-tertiary" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search"
          className="bg-transparent text-[13px] text-ink-primary outline-none placeholder:text-ink-tertiary"
          aria-label="Search actions"
        />
      </div>

      <button
        type="button"
        onClick={onTogglePerson}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[13px] font-medium transition-colors",
          personActive
            ? "border-brand-200 bg-brand-50 text-brand-700"
            : "border-line-tertiary bg-bg-primary text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary",
        )}
      >
        <IconUserCircle size={14} />
        Person
      </button>

      <div className="relative" ref={filterRef}>
        <button
          type="button"
          onClick={() => setFilterOpen((v) => !v)}
          className="inline-flex items-center gap-1.5 rounded-md border border-line-tertiary bg-bg-primary px-2.5 py-1.5 text-[13px] font-medium text-ink-secondary transition-colors hover:bg-bg-secondary hover:text-ink-primary"
        >
          <IconFilter size={14} />
          Filter
        </button>
        {filterOpen && (
          <div className="absolute left-0 top-full z-20 mt-1 w-64 rounded-lg border border-line-tertiary bg-bg-primary p-3 shadow-md">
            <FilterPanel filters={filters} setFilters={setFilters} />
          </div>
        )}
      </div>

      <div className="relative" ref={sortRef}>
        <button
          type="button"
          onClick={() => setSortOpen((v) => !v)}
          className="inline-flex items-center gap-1.5 rounded-md border border-line-tertiary bg-bg-primary px-2.5 py-1.5 text-[13px] font-medium text-ink-secondary transition-colors hover:bg-bg-secondary hover:text-ink-primary"
        >
          <IconArrowsSort size={14} />
          Sort
        </button>
        {sortOpen && (
          <div className="absolute left-0 top-full z-20 mt-1 w-56 rounded-lg border border-line-tertiary bg-bg-primary py-1 shadow-md">
            {SORT_OPTIONS.map((opt) => (
              <button
                key={opt.key}
                type="button"
                onClick={() => {
                  savePrefs({ sortBy: opt.sortBy, sortDirection: opt.sortDirection });
                  setSortOpen(false);
                }}
                className={cn(
                  "flex w-full items-center justify-between px-3 py-2 text-left text-[13px] hover:bg-bg-secondary",
                  activeSort?.key === opt.key ? "text-brand-600" : "text-ink-primary",
                )}
              >
                {opt.label}
                {activeSort?.key === opt.key && <IconCheck size={14} />}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="relative inline-flex items-center rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5 text-[13px]">
        <span className="text-ink-tertiary">Group by</span>
        <select
          value={prefs.groupBy}
          onChange={(e) => savePrefs({ groupBy: e.target.value as ProjectActionGroupBy })}
          className="appearance-none bg-transparent pl-1.5 pr-5 text-[13px] font-medium text-ink-primary outline-none"
        >
          <option value="status">Status</option>
          <option value="priority">Priority</option>
          <option value="owner">Owner</option>
          <option value="due_state">Due date</option>
          <option value="source_type">Source</option>
          <option value="none">None</option>
        </select>
        <IconChevronDown size={12} className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-ink-tertiary" />
      </div>

      <div className="relative" ref={columnsRef}>
        <button
          type="button"
          onClick={() => setColumnsOpen((v) => !v)}
          className="inline-flex items-center gap-1.5 rounded-md border border-line-tertiary bg-bg-primary px-2.5 py-1.5 text-[13px] font-medium text-ink-secondary transition-colors hover:bg-bg-secondary hover:text-ink-primary"
        >
          <IconTable size={14} />
          Columns
        </button>
        {columnsOpen && (
          <div className="absolute left-0 top-full z-20 mt-1 w-44 rounded-lg border border-line-tertiary bg-bg-primary py-1 shadow-md">
            <label className="flex cursor-pointer items-center gap-2 px-3 py-2 text-[13px] text-ink-secondary">
              <input type="checkbox" checked disabled className="opacity-50" />
              Action
            </label>
            {COLUMNS.map((col) => (
              <label
                key={col.key}
                className="flex cursor-pointer items-center gap-2 px-3 py-2 text-[13px] text-ink-primary hover:bg-bg-secondary"
              >
                <input
                  type="checkbox"
                  checked={visibleColumns.includes(col.key)}
                  onChange={() => toggleColumn(col.key)}
                />
                {col.label}
              </label>
            ))}
          </div>
        )}
      </div>

      <div className="ml-auto flex flex-wrap items-center gap-2">
        <select
          value={String(filters.status ?? "")}
          onChange={(e) =>
            setFilters({ ...filters, status: (e.target.value || undefined) as ProjectActionStatus | undefined })
          }
          className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5 text-[13px] text-ink-primary"
        >
          <option value="">All statuses</option>
          {Object.entries(STATUS_BADGE_LABELS).map(([k, label]) => (
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
          className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5 text-[13px] text-ink-primary"
        >
          <option value="">All priorities</option>
          {Object.entries(PRIORITY_LABELS).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>

        <label className="flex items-center gap-1.5 text-[13px] text-ink-secondary">
          <input
            type="checkbox"
            checked={Boolean(filters.overdue)}
            onChange={(e) => setFilters({ ...filters, overdue: e.target.checked || undefined })}
          />
          Overdue only
        </label>
      </div>
    </div>
  );
}

function FilterPanel({
  filters,
  setFilters,
}: {
  filters: ProjectActionFilters;
  setFilters: (f: ProjectActionFilters) => void;
}) {
  return (
    <div className="space-y-3">
      <div>
        <label className="text-caption text-ink-secondary">Source</label>
        <select
          value={filters.source_type ?? ""}
          onChange={(e) => setFilters({ ...filters, source_type: e.target.value || undefined })}
          className="mt-1 w-full rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5 text-[13px] text-ink-primary"
        >
          {SOURCE_TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="text-caption text-ink-secondary">Risk impact</label>
        <select
          value={filters.risk_impact ?? ""}
          onChange={(e) => setFilters({ ...filters, risk_impact: e.target.value || undefined })}
          className="mt-1 w-full rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5 text-[13px] text-ink-primary"
        >
          {RISK_IMPACT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-caption text-ink-secondary">Due from</label>
          <input
            type="date"
            value={filters.due_from ?? ""}
            onChange={(e) => setFilters({ ...filters, due_from: e.target.value || undefined })}
            className="mt-1 w-full rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5 text-[13px] text-ink-primary"
          />
        </div>
        <div>
          <label className="text-caption text-ink-secondary">Due to</label>
          <input
            type="date"
            value={filters.due_to ?? ""}
            onChange={(e) => setFilters({ ...filters, due_to: e.target.value || undefined })}
            className="mt-1 w-full rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5 text-[13px] text-ink-primary"
          />
        </div>
      </div>
      <label className="flex items-center gap-2 text-[13px] text-ink-secondary">
        <input
          type="checkbox"
          checked={Boolean(filters.has_incomplete_required_subtasks)}
          onChange={(e) =>
            setFilters({
              ...filters,
              has_incomplete_required_subtasks: e.target.checked || undefined,
            })
          }
        />
        Has incomplete required subtasks
      </label>
      <button
        type="button"
        onClick={() =>
          setFilters({
            status: filters.status,
            priority: filters.priority,
            overdue: filters.overdue,
            owner_user_id: filters.owner_user_id,
            q: filters.q,
          })
        }
        className="text-[12px] text-brand-600 hover:text-brand-700"
      >
        Clear advanced filters
      </button>
    </div>
  );
}

function GroupSection({
  projectId,
  group,
  expanded,
  onToggle,
  gridTemplate,
  visibleColumns,
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
  onSubtaskFieldChange,
  onSubtaskArchive,
  onAddSubtask,
  members,
  adding,
  newActionTitle,
  setNewActionTitle,
  onAddAction,
  onSubmitNewAction,
  onCancelAdd,
}: {
  projectId: string;
  group: ProjectActionGroupSummary & { items: ProjectActionListItem[] };
  expanded: boolean;
  onToggle: () => void;
  gridTemplate: string;
  visibleColumns: string[];
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
  onSubtaskFieldChange: (
    actionId: number,
    subtaskId: number,
    payload: Partial<{ owner_user_id: number | null; due_date: string | null; effort_points: number | null; status: ProjectActionStatus }>,
  ) => void;
  onSubtaskArchive: (actionId: number, subtaskId: number) => void;
  onAddSubtask: (actionId: number, title: string) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
  adding: boolean;
  newActionTitle: string;
  setNewActionTitle: (s: string) => void;
  onAddAction: () => void;
  onSubmitNewAction: (group: string, title: string) => void;
  onCancelAdd: () => void;
}) {
  const allSelected = group.items.length > 0 && group.items.every((i) => selected.has(i.id));
  const tone = groupTone(group.group);
  const dotColor =
    prefsGroupColor(group.group) ??
    (tone === "danger" ? "bg-danger" : tone === "warning" ? "bg-warning" : tone === "success" ? "bg-success" : "bg-brand-500");

  return (
    <div className="rounded-lg border border-line-tertiary bg-bg-primary">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-2 rounded-t-lg px-3 py-2.5 text-left hover:bg-bg-secondary"
        aria-expanded={expanded}
      >
        <div className="flex items-center gap-2">
          <IconChevronDown
            size={16}
            className={cn("text-ink-tertiary transition-transform", !expanded && "-rotate-90")}
          />
          <span className={cn("h-2.5 w-2.5 rounded-full", dotColor)} aria-hidden />
          <span className="text-[13px] font-semibold text-ink-primary">{group.label}</span>
          <span className="rounded-full bg-bg-tertiary px-2 py-0.5 text-[11px] font-medium text-ink-secondary">
            {group.count}
          </span>
          {group.overdue_count > 0 && (
            <span className="text-[11px] text-danger">{group.overdue_count} overdue</span>
          )}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-line-tertiary">
          <div className="overflow-x-auto">
            {group.items.map((item) => (
              <ActionRow
                key={item.id}
                projectId={projectId}
                item={item}
                gridTemplate={gridTemplate}
                visibleColumns={visibleColumns}
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
                onSubtaskFieldChange={onSubtaskFieldChange}
                onSubtaskArchive={onSubtaskArchive}
                onAddSubtask={onAddSubtask}
                members={members}
              />
            ))}

            {adding && (
              <div
                className="grid items-center gap-2 border-t border-line-tertiary px-3 py-2 hover:bg-bg-secondary"
                style={{ gridTemplateColumns: gridTemplate }}
              >
                <div className="flex items-center justify-center">
                  <IconPlus size={14} className="text-ink-tertiary" />
                </div>
                <div className="min-w-0">
                  <input
                    type="text"
                    value={newActionTitle}
                    onChange={(e) => setNewActionTitle(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") onSubmitNewAction(group.group, newActionTitle);
                      if (e.key === "Escape") onCancelAdd();
                    }}
                    placeholder="New action"
                    autoFocus
                    className="w-full rounded border border-line-tertiary bg-bg-primary px-2 py-1 text-[13px] text-ink-primary outline-none focus:border-brand-500"
                  />
                </div>
                <div className="col-span-full mt-1 flex gap-2">
                  <button
                    type="button"
                    onClick={() => onSubmitNewAction(group.group, newActionTitle)}
                    className="rounded bg-brand-500 px-2 py-1 text-[12px] text-white hover:bg-brand-600"
                  >
                    Add
                  </button>
                  <button
                    type="button"
                    onClick={onCancelAdd}
                    className="rounded px-2 py-1 text-[12px] text-ink-secondary hover:bg-bg-secondary"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>

          <div className="flex items-center justify-between border-t border-line-tertiary px-3 py-2">
            {canManage ? (
              <button
                type="button"
                onClick={onAddAction}
                className="inline-flex items-center gap-1 text-[13px] font-medium text-brand-600 hover:text-brand-700"
              >
                <IconPlus size={14} /> Add action
              </button>
            ) : (
              <span />
            )}
            <span className="text-[12px] text-ink-tertiary">
              Avg progress: {group.avg_progress}% · {group.count} {group.count === 1 ? "action" : "actions"}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function prefsGroupColor(group: string): string | null {
  if (STATUS_ORDER.includes(group as ProjectActionStatus)) {
    return STATUS_DOT_COLORS[group as ProjectActionStatus];
  }
  return null;
}

function ActionRow({
  projectId,
  item,
  gridTemplate,
  visibleColumns,
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
  onSubtaskFieldChange,
  onSubtaskArchive,
  onAddSubtask,
  members,
}: {
  projectId: string;
  item: ProjectActionListItem;
  gridTemplate: string;
  visibleColumns: string[];
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
  onSubtaskFieldChange: (
    actionId: number,
    subtaskId: number,
    payload: Partial<{ owner_user_id: number | null; due_date: string | null; effort_points: number | null; status: ProjectActionStatus }>,
  ) => void;
  onSubtaskArchive: (actionId: number, subtaskId: number) => void;
  onAddSubtask: (actionId: number, title: string) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
}) {
  const progress = item.percent_complete ?? 0;
  const overdue = isOverdue(item);
  const activeSubtasks = detail?.subtasks.filter((s) => !s.archived_at) ?? [];
  const hasSubtasks = item.total_subtasks > 0;

  return (
    <div className="border-b border-line-tertiary last:border-b-0" role="row" aria-expanded={expanded}>
      <div
        className="grid cursor-pointer items-center gap-2 px-3 py-2.5 transition-colors hover:bg-bg-secondary"
        style={{ gridTemplateColumns: gridTemplate }}
        onClick={(e) => {
          if ((e.target as HTMLElement).closest("button, select, input, a, textarea")) return;
          onExpand();
        }}
      >
        <div className="flex items-center justify-center">
          <input
            type="checkbox"
            checked={selected}
            onChange={onSelect}
            onClick={(e) => e.stopPropagation()}
            aria-label={`Select ${item.title}`}
          />
        </div>

        <div className="flex min-w-0 flex-col">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onExpand();
              }}
              className="shrink-0"
              aria-label={expanded ? "Collapse subtasks" : "Expand subtasks"}
            >
              {hasSubtasks ? (
                <IconChevronRight
                  size={14}
                  className={cn("text-ink-tertiary transition-transform", expanded && "rotate-90")}
                />
              ) : (
                <span className="inline-block w-3.5" />
              )}
            </button>
            <Link
              href={`/projects/${projectId}/actions/${item.id}`}
              className="truncate text-[13px] font-semibold text-ink-primary hover:text-brand-600 hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              {item.title}
            </Link>
          </div>
          {item.description && (
            <span className="truncate pl-5 text-[12px] text-ink-tertiary">{item.description}</span>
          )}
          <div className="flex items-center gap-3 pl-5 pt-1">
            {item.comment_count > 0 && (
              <span className="inline-flex items-center gap-1 text-[11px] text-ink-tertiary">
                <IconMessage size={12} /> {item.comment_count}
              </span>
            )}
            {item.total_subtasks > 0 && (
              <span className="inline-flex items-center gap-1 text-[11px] text-ink-tertiary">
                <IconClipboardList size={12} /> {item.total_subtasks}
              </span>
            )}
          </div>
        </div>

        {visibleColumns.includes("owner") && (
          <OwnerCell value={item.owner_user_id} members={members} canManage={canManage} onChange={(v) => onOwnerChange(item.id, v, item.lock_version)} />
        )}
        {visibleColumns.includes("status") && (
          <StatusCell value={item.status} canManage={canManage} onChange={(v) => onStatusChange(item.id, v, item.lock_version)} />
        )}
        {visibleColumns.includes("priority") && (
          <PriorityCell value={item.priority} canManage={canManage} onChange={(v) => onPriorityChange(item.id, v, item.lock_version)} />
        )}
        {visibleColumns.includes("progress") && (
          <ProgressCell
            percent={progress}
            completed={item.completed_required_subtasks}
            total={item.required_subtasks}
          />
        )}
        {visibleColumns.includes("due") && (
          <DueCell
            value={item.due_date}
            overdue={overdue}
            canManage={canManage}
            onChange={(v) => onDueChange(item.id, v, item.lock_version)}
          />
        )}
        {visibleColumns.includes("risk") && <RiskCell impact={item.risk_impact} />}
        {visibleColumns.includes("source") && <SourceCell item={item} />}
        {visibleColumns.includes("updated") && (
          <div className="truncate text-[12px] text-ink-tertiary">{timeAgo(item.updated_at)}</div>
        )}

        <RowMenu projectId={projectId} item={item} canManage={canManage} onArchive={() => onArchive(item.id)} onRestore={() => onRestore(item.id)} />
      </div>

      {expanded && (
        <div className="col-span-full border-t border-line-tertiary bg-bg-secondary/50 px-12 py-4">
          <SubtaskPanel
            actionId={item.id}
            subtasks={activeSubtasks}
            canManage={canManage}
            onStatusChange={onSubtaskStatusChange}
            onFieldChange={onSubtaskFieldChange}
            onArchive={onSubtaskArchive}
            onAddSubtask={onAddSubtask}
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
  const name = selected ? selected.display_name || selected.email : "Unassigned";
  if (!canManage) {
    return (
      <div className="flex min-w-0 items-center gap-1.5">
        <Avatar name={name} />
        <span className="truncate text-[12px] text-ink-primary">{name}</span>
      </div>
    );
  }
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <Avatar name={name} />
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
        onClick={(e) => e.stopPropagation()}
        className="min-w-0 flex-1 appearance-none border-0 bg-transparent py-0.5 pr-4 text-[12px] text-ink-primary outline-none"
      >
        <option value="">Unassigned</option>
        {members.map((m) => (
          <option key={m.user_id} value={m.user_id}>
            {m.display_name || m.email}
          </option>
        ))}
      </select>
      <IconChevronDown size={12} className="pointer-events-none -ml-4 text-ink-tertiary" />
    </div>
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
  const color = STATUS_COLORS[value];
  if (!canManage) {
    return (
      <span className={cn("inline-flex rounded-full px-2.5 py-1 text-[11px] font-medium", color)}>
        {STATUS_BADGE_LABELS[value]}
      </span>
    );
  }
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as ProjectActionStatus)}
        onClick={(e) => e.stopPropagation()}
        className={cn(
          "w-full appearance-none rounded-full border-0 py-1 pl-2.5 pr-6 text-[11px] font-medium outline-none",
          color,
        )}
      >
        {Object.entries(STATUS_BADGE_LABELS).map(([k, label]) => (
          <option key={k} value={k}>
            {label}
          </option>
        ))}
      </select>
      <IconChevronDown size={12} className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-current opacity-70" />
    </div>
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
  const color = PRIORITY_COLORS[value];
  if (!canManage) {
    return <span className={cn("inline-flex rounded-full px-2.5 py-1 text-[11px] font-medium", color)}>{PRIORITY_LABELS[value]}</span>;
  }
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as ProjectActionPriority)}
        onClick={(e) => e.stopPropagation()}
        className={cn(
          "w-full appearance-none rounded-full border-0 py-1 pl-2.5 pr-6 text-[11px] font-medium outline-none",
          color,
        )}
      >
        {Object.entries(PRIORITY_LABELS).map(([k, label]) => (
          <option key={k} value={k}>
            {label}
          </option>
        ))}
      </select>
      <IconChevronDown size={12} className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-current opacity-70" />
    </div>
  );
}

function ProgressCell({ percent, completed, total }: { percent: number; completed: number; total: number }) {
  const hasSegments = total > 0;
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex items-center gap-2">
        <div className="flex flex-1 gap-0.5">
          {hasSegments ? (
            Array.from({ length: Math.max(total, 1) }).map((_, i) => (
              <div
                key={i}
                className={cn("h-2 flex-1 rounded-sm", i < completed ? "bg-brand-500" : "bg-bg-tertiary")}
              />
            ))
          ) : (
            <div className="h-2 flex-1 rounded-sm bg-bg-tertiary">
              <div className="h-full rounded-sm bg-brand-500" style={{ width: `${percent}%` }} />
            </div>
          )}
        </div>
        <span className="text-[12px] font-semibold text-ink-primary w-8 text-right">{percent}%</span>
      </div>
      {total > 0 && (
        <span className="text-[11px] text-ink-tertiary">
          {completed} of {total} subtasks
        </span>
      )}
    </div>
  );
}

function DueCell({
  value,
  overdue,
  canManage,
  onChange,
}: {
  value: string | null;
  overdue: boolean;
  canManage: boolean;
  onChange: (v: string | null) => void;
}) {
  const dateValue = value ? value.split("T")[0] : "";
  return (
    <div className="flex items-center gap-1">
      <IconCalendar size={12} className={cn("shrink-0", overdue ? "text-danger" : "text-ink-tertiary")} />
      {canManage ? (
        <input
          type="date"
          value={dateValue}
          onChange={(e) => onChange(e.target.value || null)}
          onClick={(e) => e.stopPropagation()}
          className={cn(
            "min-w-0 flex-1 rounded border bg-transparent px-1 py-0.5 text-[12px] outline-none",
            overdue ? "border-danger text-danger" : "border-line-tertiary text-ink-primary",
          )}
        />
      ) : (
        <span className={cn("truncate text-[12px]", overdue ? "text-danger" : "text-ink-secondary")}>
          {formatDateShort(value) || "-"}
        </span>
      )}
    </div>
  );
}

function RiskCell({ impact }: { impact: string | null }) {
  if (!impact) return <span className="text-[12px] text-ink-tertiary">-</span>;
  return (
    <Badge tone={riskImpactTone(impact)} size="sm">
      {riskImpactLabel(impact)}
    </Badge>
  );
}

function SourceCell({ item }: { item: ProjectActionListItem }) {
  const title = item.source_insight_title;
  if (!title) {
    return (
      <span className="text-[12px] text-ink-tertiary">{SOURCE_TYPE_LABELS[item.source_type] ?? item.source_type}</span>
    );
  }
  const href = item.source_insight_id
    ? `/business-insight/analysis/${encodeURIComponent(item.source_insight_id)}`
    : undefined;
  const content = (
    <span className="inline-flex items-center gap-1 truncate text-[12px]">
      <IconSparkles size={12} className="shrink-0 text-brand-500" />
      <span className="truncate">{title}</span>
    </span>
  );
  if (href) {
    return (
      <Link href={href} className="text-brand-600 hover:underline" onClick={(e) => e.stopPropagation()}>
        {content}
      </Link>
    );
  }
  return <span className="text-ink-secondary">{content}</span>;
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
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function close(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div ref={ref} className="relative flex items-center justify-center">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        aria-label="Action menu"
        className="rounded p-1 text-ink-tertiary hover:bg-bg-secondary"
      >
        <IconDotsVertical size={16} />
      </button>
      {open && (
        <div className="absolute right-0 top-7 z-10 w-40 rounded-md border border-line-tertiary bg-bg-primary py-1 shadow-md">
          <Link
            href={`/projects/${projectId}/actions/${item.id}`}
            className="block px-3 py-1.5 text-[12px] text-ink-primary hover:bg-bg-secondary"
            onClick={() => setOpen(false)}
          >
            Open details
          </Link>
          {canManage && (
            <>
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
            </>
          )}
        </div>
      )}
    </div>
  );
}

function SubtaskPanel({
  actionId,
  subtasks,
  canManage,
  onStatusChange,
  onFieldChange,
  onArchive,
  onAddSubtask,
  members,
}: {
  actionId: number;
  subtasks: ProjectActionSubtask[];
  canManage: boolean;
  onStatusChange: (actionId: number, subtaskId: number, status: ProjectActionStatus) => void;
  onFieldChange: (
    actionId: number,
    subtaskId: number,
    payload: Partial<{ owner_user_id: number | null; due_date: string | null; effort_points: number | null; status: ProjectActionStatus }>,
  ) => void;
  onArchive: (actionId: number, subtaskId: number) => void;
  onAddSubtask: (actionId: number, title: string) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
}) {
  const [newTitle, setNewTitle] = useState("");

  return (
    <div className="rounded-lg border border-line-tertiary bg-bg-primary p-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[13px] font-semibold text-ink-primary">Subitems</h3>
        <span className="text-[12px] text-ink-tertiary">{subtasks.length} subitems</span>
      </div>

      <div className="space-y-1">
        {subtasks.map((sub) => (
          <SubtaskRow
            key={sub.id}
            actionId={actionId}
            subtask={sub}
            canManage={canManage}
            onStatusChange={onStatusChange}
            onFieldChange={onFieldChange}
            onArchive={onArchive}
            members={members}
          />
        ))}

        {canManage && (
          <div className="flex items-center gap-2 pt-2">
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newTitle.trim()) {
                  onAddSubtask(actionId, newTitle.trim());
                  setNewTitle("");
                }
                if (e.key === "Escape") setNewTitle("");
              }}
              placeholder="New subitem"
              className="min-w-0 flex-1 rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5 text-[13px] text-ink-primary outline-none focus:border-brand-500"
            />
            <Button
              size="sm"
              onClick={() => {
                if (newTitle.trim()) {
                  onAddSubtask(actionId, newTitle.trim());
                  setNewTitle("");
                }
              }}
            >
              <IconPlus size={14} /> Add
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function SubtaskRow({
  actionId,
  subtask,
  canManage,
  onStatusChange,
  onFieldChange,
  onArchive,
  members,
}: {
  actionId: number;
  subtask: ProjectActionSubtask;
  canManage: boolean;
  onStatusChange: (actionId: number, subtaskId: number, status: ProjectActionStatus) => void;
  onFieldChange: (
    actionId: number,
    subtaskId: number,
    payload: Partial<{ owner_user_id: number | null; due_date: string | null; effort_points: number | null; status: ProjectActionStatus }>,
  ) => void;
  onArchive: (actionId: number, subtaskId: number) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
}) {
  const completed = subtask.status === "completed";
  const owner = members.find((m) => m.user_id === subtask.owner_user_id);
  const ownerName = owner ? owner.display_name || owner.email : "Unassigned";

  return (
    <div className="grid grid-cols-[28px_1fr_140px_120px_110px_70px_44px_32px] items-center gap-2 rounded-md border border-line-tertiary px-2 py-1.5">
      <input
        type="checkbox"
        checked={completed}
        disabled={!canManage}
        onChange={(e) => onStatusChange(actionId, subtask.id, e.target.checked ? "completed" : "not_started")}
        aria-label={`Mark ${subtask.title} complete`}
      />
      <span className="truncate text-[13px] text-ink-primary">{subtask.title}</span>

      <OwnerCell value={subtask.owner_user_id} members={members} canManage={canManage} onChange={(v) => onFieldChange(actionId, subtask.id, { owner_user_id: v })} />

      <StatusCell value={subtask.status} canManage={canManage} onChange={(v) => onStatusChange(actionId, subtask.id, v)} />

      <input
        type="date"
        value={subtask.due_date ? subtask.due_date.split("T")[0] : ""}
        disabled={!canManage}
        onChange={(e) => onFieldChange(actionId, subtask.id, { due_date: e.target.value || null })}
        className="rounded border border-line-tertiary bg-bg-primary px-1 py-0.5 text-[12px] text-ink-primary disabled:bg-bg-secondary"
      />

      <input
        type="number"
        min={1}
        max={10}
        value={subtask.effort_points ?? ""}
        disabled={!canManage}
        onChange={(e) => {
          const v = e.target.value ? Number(e.target.value) : null;
          onFieldChange(actionId, subtask.id, { effort_points: v });
        }}
        placeholder="-"
        className="w-full rounded border border-line-tertiary bg-bg-primary px-1 py-0.5 text-center text-[12px] text-ink-primary disabled:bg-bg-secondary"
      />

      <div className="flex items-center justify-center">
        <input
          type="checkbox"
          checked={completed}
          disabled={!canManage}
          onChange={(e) => onStatusChange(actionId, subtask.id, e.target.checked ? "completed" : "not_started")}
        />
      </div>

      {canManage && (
        <button
          type="button"
          onClick={() => onArchive(actionId, subtask.id)}
          aria-label={`Archive ${subtask.title}`}
          className="text-ink-tertiary hover:text-danger"
        >
          <IconTrash size={14} />
        </button>
      )}
    </div>
  );
}

function Avatar({ name, size = "sm" }: { name: string; size?: "sm" | "md" }) {
  const sizeClass = size === "sm" ? "h-6 w-6 text-[10px]" : "h-8 w-8 text-[11px]";
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full bg-brand-50 font-semibold text-brand-700",
        sizeClass,
      )}
      aria-hidden
    >
      {initials(name || "?")}
    </div>
  );
}
