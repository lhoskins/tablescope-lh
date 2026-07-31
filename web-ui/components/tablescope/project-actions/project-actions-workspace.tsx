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
} from "@/lib/api/project-actions";
import {
  IconPlus,
  IconSearch,
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

const PRIORITY_TEXT_COLORS: Record<ProjectActionPriority, string> = {
  low: "text-success",
  medium: "text-brand-600",
  high: "text-warning",
  critical: "text-danger",
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

const DUE_STATE_ORDER: Record<string, number> = {
  overdue: 0,
  due_today: 1,
  due_this_week: 2,
  upcoming: 3,
  no_due: 4,
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

const GROUP_BY_OPTIONS: { value: ProjectActionGroupBy; label: string }[] = [
  { value: "status", label: "Status" },
  { value: "priority", label: "Priority" },
  { value: "owner", label: "Owner" },
  { value: "due_state", label: "Due date" },
  { value: "source_type", label: "Source" },
  { value: "none", label: "None" },
];

const SUBTASK_GRID = "24px minmax(160px, 1fr) 140px 120px 100px 70px 44px 44px";

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

function groupBorderClass(tone: ReturnType<typeof groupTone>): string {
  switch (tone) {
    case "danger":
      return "border-l-red-500";
    case "warning":
      return "border-l-amber-500";
    case "success":
      return "border-l-emerald-500";
    case "brand":
      return "border-l-brand-500";
    default:
      return "border-l-gray-400";
  }
}

function groupTextClass(tone: ReturnType<typeof groupTone>): string {
  switch (tone) {
    case "danger":
      return "text-red-600";
    case "warning":
      return "text-amber-600";
    case "success":
      return "text-emerald-600";
    case "brand":
      return "text-brand-600";
    default:
      return "text-ink-primary";
  }
}

function groupLabel(
  group: string,
  groupBy: ProjectActionGroupBy,
  members: { user_id: number; display_name: string | null; email: string }[],
): string {
  if (groupBy === "owner") {
    if (group === "unassigned") return "Unassigned";
    const m = members.find((m) => String(m.user_id) === group);
    return m?.display_name || m?.email || group;
  }
  if (groupBy === "due_state") {
    return DUE_STATE_ORDER[group] !== undefined ? GROUP_LABELS[group] || group : group;
  }
  if (groupBy === "source_type") return SOURCE_TYPE_LABELS[group] || group;
  return GROUP_LABELS[group] || group;
}

function useGridTemplate() {
  return useMemo(() => {
    const widths = ["40px", "minmax(220px, 1fr)"];
    for (const col of COLUMNS) widths.push(col.width);
    widths.push("44px");
    return widths.join(" ");
  }, []);
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

  const gridTemplate = useGridTemplate();

  const viewItems = useMemo(() => {
    if (prefs.view === "archived") return items.filter((i) => i.archived_at);
    if (prefs.view === "my-actions") return items.filter((i) => !i.archived_at && i.owner_user_id === currentUserId);
    if (prefs.view === "timeline") {
      return [...items]
        .filter((i) => !i.archived_at)
        .sort((a, b) => {
          const da = a.due_date ? new Date(a.due_date).getTime() : Number.MAX_SAFE_INTEGER;
          const db = b.due_date ? new Date(b.due_date).getTime() : Number.MAX_SAFE_INTEGER;
          return da - db;
        });
    }
    return items.filter((i) => !i.archived_at);
  }, [items, prefs.view, currentUserId]);

  const viewSummary = useMemo(() => {
    const active = viewItems.filter(
      (i) => !i.archived_at && !["completed", "cancelled"].includes(i.status),
    ).length;
    const overdue = viewItems.filter(
      (i) =>
        !i.archived_at && !["completed", "cancelled"].includes(i.status) && isOverdue(i),
    ).length;
    const avgItems = viewItems.filter(
      (i) => !i.archived_at && !["completed", "cancelled"].includes(i.status),
    );
    const avg_progress = avgItems.length
      ? Math.round(avgItems.reduce((s, i) => s + i.percent_complete, 0) / avgItems.length)
      : 0;
    const risk_mitigations_completed = viewItems.filter(
      (i) =>
        i.status === "completed" &&
        !i.archived_at &&
        ((i.source_insight_type || "").toLowerCase() === "risk" ||
          (i.source_insight_snapshot?.insight_type as string) === "risk"),
    ).length;
    return { active, overdue, avg_progress, risk_mitigations_completed };
  }, [viewItems]);

  const groupByForView = prefs.groupBy;

  const grouped = useMemo(() => {
    const byKey: Record<string, ProjectActionListItem[]> = {};
    for (const item of viewItems) {
      let key: string = item.status;
      if (groupByForView === "priority") key = item.priority;
      if (groupByForView === "owner") key = item.owner_user_id == null ? "unassigned" : String(item.owner_user_id);
      if (groupByForView === "due_state") key = item.due_date ? (isOverdue(item) ? "overdue" : "upcoming") : "no_due";
      if (groupByForView === "source_type") key = item.source_type || "none";
      if (groupByForView === "none") key = "all";
      byKey[key] = byKey[key] ?? [];
      byKey[key].push(item);
    }
    return byKey;
  }, [viewItems, groupByForView]);

  const groupMeta = useMemo(() => {
    const keys = new Set(Object.keys(grouped));
    if (addingGroup) keys.add(addingGroup);
    const order = Array.from(keys).sort((a, b) => {
      if (groupByForView === "status") {
        const ai = STATUS_ORDER.indexOf(a as ProjectActionStatus);
        const bi = STATUS_ORDER.indexOf(b as ProjectActionStatus);
        if (ai !== -1 && bi !== -1) return ai - bi;
        if (ai !== -1) return -1;
        if (bi !== -1) return 1;
      }
      if (groupByForView === "priority") {
        const orderP = ["critical", "high", "medium", "low"];
        const ai = orderP.indexOf(a);
        const bi = orderP.indexOf(b);
        if (ai !== -1 && bi !== -1) return ai - bi;
      }
      if (groupByForView === "due_state") {
        const ai = DUE_STATE_ORDER[a] ?? 99;
        const bi = DUE_STATE_ORDER[b] ?? 99;
        if (ai !== bi) return ai - bi;
      }
      if (groupByForView === "owner") {
        const an = Number(a);
        const bn = Number(b);
        if (!Number.isNaN(an) && !Number.isNaN(bn)) return an - bn;
      }
      return a.localeCompare(b);
    });

    return order.map((key) => {
      const groupItems = grouped[key] ?? [];
      const overdue_count = groupItems.filter(
        (i) => !i.archived_at && !["completed", "cancelled"].includes(i.status) && isOverdue(i),
      ).length;
      const activeItems = groupItems.filter(
        (i) => !i.archived_at && !["completed", "cancelled"].includes(i.status),
      );
      const avg_progress = activeItems.length
        ? Math.round(activeItems.reduce((s, i) => s + i.percent_complete, 0) / activeItems.length)
        : 0;
      return {
        group: key,
        label: groupLabel(key, groupByForView, members),
        count: groupItems.length,
        overdue_count,
        avg_progress,
        items: groupItems,
      };
    });
  }, [grouped, addingGroup, groupByForView, members]);

  const toggleExpand = useCallback(
    async (id: number) => {
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
    },
    [fetchDetail, detailMap],
  );

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

  const handleArchive = (id: number, version: number) => {
    archiveAction.mutate({ actionId: id, expected_version: version });
  };

  const handleRestore = (id: number) => restoreAction.mutate(id);

  const handleSubtaskStatusChange = (
    actionId: number,
    subtaskId: number,
    status: ProjectActionStatus,
  ) => {
    const action = detailMap[actionId];
    const sub = action?.subtasks.find((s) => s.id === subtaskId);
    if (!sub) return;
    updateSubtask.mutate(
      { actionId, subtaskId, payload: { status, expected_version: sub.lock_version } },
      {
        onSuccess: () =>
          fetchDetail(actionId).then((a) => setDetailMap((m) => ({ ...m, [actionId]: a }))),
      },
    );
  };

  const handleSubtaskFieldChange = (
    actionId: number,
    subtaskId: number,
    payload: Partial<{
      title: string;
      owner_user_id: number | null;
      due_date: string | null;
      effort_points: number | null;
    }>,
  ) => {
    const action = detailMap[actionId];
    const sub = action?.subtasks.find((s) => s.id === subtaskId);
    if (!sub) return;
    updateSubtask.mutate(
      { actionId, subtaskId, payload: { ...payload, expected_version: sub.lock_version } },
      {
        onSuccess: () =>
          fetchDetail(actionId).then((a) => setDetailMap((m) => ({ ...m, [actionId]: a }))),
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
        onSuccess: () =>
          fetchDetail(actionId).then((a) => setDetailMap((m) => ({ ...m, [actionId]: a }))),
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

  const startAdding = (group?: string) => {
    const target = group ?? (groupByForView === "status" ? "not_started" : "all");
    setAddingGroup(target);
    setNewActionTitle("");
    if (prefs.collapsedGroups.includes(target)) {
      savePrefs({
        collapsedGroups: prefs.collapsedGroups.filter((g) => g !== target),
      });
    }
  };

  const submitNewAction = (group: string, title: string) => {
    if (!title.trim()) return;
    const isStatusGroup = groupByForView === "status" && STATUS_ORDER.includes(group as ProjectActionStatus);
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

  const handleBulkStatus = (status: ProjectActionStatus) => {
    const expected: Record<number, number> = {};
    for (const id of selected) {
      const item = viewItems.find((i) => i.id === id);
      if (item) expected[id] = item.lock_version;
    }
    bulkUpdate.mutate({ action_ids: Array.from(selected), expected_versions: expected, status });
    setSelected(new Set());
  };

  const handleBulkArchive = () => {
    for (const id of selected) {
      const item = viewItems.find((i) => i.id === id);
      if (item) archiveAction.mutate({ actionId: id, expected_version: item.lock_version });
    }
    setSelected(new Set());
  };

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-actions"
      breadcrumbLabel="Project Actions"
    >
      <div className="flex flex-col gap-5 p-4" aria-label="Project actions board">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold text-ink-primary">Project Actions</h1>
            <p className="text-[13px] text-ink-secondary">
              Manage actions created from insights and track mitigation progress.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <SummaryCard value={viewSummary.active} label="Active" icon={IconClipboardList} tone="brand" />
            <SummaryCard value={viewSummary.overdue} label="Overdue" icon={IconClock} tone="danger" />
            <SummaryCard value={`${viewSummary.avg_progress}%`} label="Avg progress" icon={IconTrendingUp} tone="brand" />
            <SummaryCard
              value={viewSummary.risk_mitigations_completed}
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
          canManage={canManage}
          onNewAction={() => startAdding()}
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
            Loading actions…
          </div>
        ) : viewItems.length === 0 ? (
          <div className="flex h-48 flex-col items-center justify-center rounded-lg border border-dashed border-line-tertiary text-ink-secondary">
            <IconClipboardList size={32} stroke={1.2} />
            <p className="mt-2 text-[13px]">No actions match the current filters.</p>
          </div>
        ) : prefs.view === "timeline" ? (
          <TimelineView
            projectId={projectId}
            items={viewItems}
            gridTemplate={gridTemplate}
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
          />
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

function ColumnHeader({ gridTemplate }: { gridTemplate: string }) {
  return (
    <div
      className="grid items-center gap-2 border-b border-line-tertiary bg-bg-secondary/50 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-tertiary"
      style={{ gridTemplateColumns: gridTemplate }}
    >
      <div />
      <div>Action</div>
      {COLUMNS.map((col) => (
        <div key={col.key}>{col.label}</div>
      ))}
      <div />
    </div>
  );
}

function TimelineView({
  projectId,
  items,
  gridTemplate,
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
}: {
  projectId: string;
  items: ProjectActionListItem[];
  gridTemplate: string;
  selected: Set<number>;
  onSelect: (id: number) => void;
  onExpand: (id: number) => void;
  expandedRows: Set<number>;
  detailMap: Record<number, ProjectAction>;
  canManage: boolean;
  onStatusChange: (id: number, status: ProjectActionStatus, version: number) => void;
  onPriorityChange: (id: number, priority: ProjectActionPriority, version: number) => void;
  onOwnerChange: (id: number, owner_user_id: number | null, version: number) => void;
  onDueChange: (id: number, due_date: string | null, version: number) => void;
  onArchive: (id: number, version: number) => void;
  onRestore: (id: number) => void;
  onSubtaskStatusChange: (actionId: number, subtaskId: number, status: ProjectActionStatus) => void;
  onSubtaskFieldChange: (
    actionId: number,
    subtaskId: number,
    payload: Partial<{
      title: string;
      owner_user_id: number | null;
      due_date: string | null;
      effort_points: number | null;
    }>,
  ) => void;
  onSubtaskArchive: (actionId: number, subtaskId: number) => void;
  onAddSubtask: (actionId: number, title: string) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
}) {
  const sections = useMemo(() => {
    const groups: Record<string, { label: string; sort: number; items: ProjectActionListItem[] }> = {};
    for (const item of items) {
      let key: string;
      let label: string;
      let sort: number;
      if (!item.due_date) {
        key = "no-due";
        label = "No due date";
        sort = Number.MAX_SAFE_INTEGER;
      } else {
        const d = new Date(item.due_date);
        key = `${d.getFullYear()}-${d.getMonth()}`;
        label = d.toLocaleDateString("en-US", { month: "long", year: "numeric" });
        sort = d.getFullYear() * 12 + d.getMonth();
      }
      if (!groups[key]) groups[key] = { label, sort, items: [] };
      groups[key].items.push(item);
    }
    return Object.values(groups).sort((a, b) => a.sort - b.sort);
  }, [items]);

  return (
    <div className="flex flex-col gap-4">
      {sections.map((section) => (
        <div key={section.label} className="rounded-lg border border-line-tertiary bg-bg-primary p-4">
          <h3 className="mb-3 text-[13px] font-semibold text-ink-primary">{section.label}</h3>
          <div className="overflow-x-auto">
            <ColumnHeader gridTemplate={gridTemplate} />
            {section.items.map((item) => (
              <ActionRow
                key={item.id}
                projectId={projectId}
                item={item}
                gridTemplate={gridTemplate}
                selected={selected.has(item.id)}
                onSelect={() => onSelect(item.id)}
                onExpand={() => onExpand(item.id)}
                expanded={expandedRows.has(item.id)}
                detail={detailMap[item.id]}
                canManage={canManage}
                onStatusChange={onStatusChange}
                onPriorityChange={onPriorityChange}
                onOwnerChange={onOwnerChange}
                onDueChange={onDueChange}
                onArchive={() => onArchive(item.id, item.lock_version)}
                onRestore={() => onRestore(item.id)}
                onSubtaskStatusChange={onSubtaskStatusChange}
                onSubtaskFieldChange={onSubtaskFieldChange}
                onSubtaskArchive={onSubtaskArchive}
                onAddSubtask={onAddSubtask}
                members={members}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
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
  icon: React.ComponentType<{ size?: number; className?: string; stroke?: number }>;
  tone: "brand" | "danger" | "success";
}) {
  const toneClass =
    tone === "brand" ? "text-brand-600" : tone === "danger" ? "text-danger" : "text-success";
  return (
    <div className="flex flex-col rounded-lg border border-line-tertiary bg-bg-primary p-4">
      <Icon size={20} className={cn("mb-2", toneClass)} stroke={1.5} />
      <div className="text-2xl font-semibold text-ink-primary">{value}</div>
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
  canManage,
  onNewAction,
}: {
  search: string;
  setSearch: (v: string) => void;
  filters: ProjectActionFilters;
  setFilters: React.Dispatch<React.SetStateAction<ProjectActionFilters>>;
  prefs: { groupBy: ProjectActionGroupBy; sortBy: ProjectActionSortBy; sortDirection: "asc" | "desc" };
  savePrefs: (next: { groupBy?: ProjectActionGroupBy; sortBy?: ProjectActionSortBy; sortDirection?: "asc" | "desc" }) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
  canManage: boolean;
  onNewAction: () => void;
}) {
  const ownerValue = filters.owner_user_id != null ? String(filters.owner_user_id) : "";
  const statusValue = filters.status ?? "";
  const priorityValue = filters.priority ?? "";
  const overdueChecked = filters.overdue === true;
  const sortValue = `${prefs.sortBy}:${prefs.sortDirection}`;

  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <IconSearch
            size={14}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-tertiary"
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search actions"
            className="h-8 w-48 rounded-md border border-line-tertiary bg-bg-primary pl-8 pr-2 text-[13px] text-ink-primary outline-none focus:border-brand-500"
          />
        </div>
        <select
          value={ownerValue}
          onChange={(e) => {
            const v = e.target.value;
            setFilters((prev) => ({ ...prev, owner_user_id: v ? Number(v) : undefined }));
          }}
          className="h-8 rounded-md border border-line-tertiary bg-bg-primary px-2 text-[13px] text-ink-primary outline-none focus:border-brand-500"
        >
          <option value="">All owners</option>
          {members.map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.display_name || m.email}
            </option>
          ))}
        </select>
        <select
          value={statusValue}
          onChange={(e) =>
            setFilters((prev) => ({ ...prev, status: (e.target.value as ProjectActionStatus) || undefined }))
          }
          className="h-8 rounded-md border border-line-tertiary bg-bg-primary px-2 text-[13px] text-ink-primary outline-none focus:border-brand-500"
        >
          <option value="">All statuses</option>
          {Object.entries(STATUS_BADGE_LABELS).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        <select
          value={priorityValue}
          onChange={(e) =>
            setFilters((prev) => ({ ...prev, priority: (e.target.value as ProjectActionPriority) || undefined }))
          }
          className="h-8 rounded-md border border-line-tertiary bg-bg-primary px-2 text-[13px] text-ink-primary outline-none focus:border-brand-500"
        >
          <option value="">All priorities</option>
          {Object.entries(PRIORITY_LABELS).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        <label className="inline-flex items-center gap-1.5 text-[13px] text-ink-secondary">
          <input
            type="checkbox"
            checked={overdueChecked}
            onChange={(e) =>
              setFilters((prev) => ({ ...prev, overdue: e.target.checked || undefined }))
            }
            className="rounded border-line-tertiary"
          />
          Overdue only
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1 text-[13px] text-ink-secondary">
          <span className="text-ink-tertiary">Group by</span>
          <select
            value={prefs.groupBy}
            onChange={(e) => savePrefs({ groupBy: e.target.value as ProjectActionGroupBy })}
            className="h-8 rounded-md border border-line-tertiary bg-bg-primary px-2 text-[13px] text-ink-primary outline-none focus:border-brand-500"
          >
            {GROUP_BY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-1 text-[13px] text-ink-secondary">
          <span className="text-ink-tertiary">Sort by</span>
          <select
            value={sortValue}
            onChange={(e) => {
              const [sortBy, sortDirection] = e.target.value.split(":");
              savePrefs({ sortBy: sortBy as ProjectActionSortBy, sortDirection: sortDirection as "asc" | "desc" });
            }}
            className="h-8 rounded-md border border-line-tertiary bg-bg-primary px-2 text-[13px] text-ink-primary outline-none focus:border-brand-500"
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <Button variant="primary" size="sm" onClick={onNewAction} disabled={!canManage}>
          <IconPlus size={14} /> New action
        </Button>
      </div>
    </div>
  );
}

function GroupSection({
  projectId,
  group,
  expanded,
  onToggle,
  gridTemplate,
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
  group: { group: string; label: string; count: number; overdue_count: number; avg_progress: number; items: ProjectActionListItem[] };
  expanded: boolean;
  onToggle: () => void;
  gridTemplate: string;
  selected: Set<number>;
  onSelect: (id: number) => void;
  onExpand: (id: number) => void;
  expandedRows: Set<number>;
  detailMap: Record<number, ProjectAction>;
  canManage: boolean;
  onStatusChange: (id: number, status: ProjectActionStatus, version: number) => void;
  onPriorityChange: (id: number, priority: ProjectActionPriority, version: number) => void;
  onOwnerChange: (id: number, owner_user_id: number | null, version: number) => void;
  onDueChange: (id: number, due_date: string | null, version: number) => void;
  onArchive: (id: number, version: number) => void;
  onRestore: (id: number) => void;
  onSubtaskStatusChange: (actionId: number, subtaskId: number, status: ProjectActionStatus) => void;
  onSubtaskFieldChange: (
    actionId: number,
    subtaskId: number,
    payload: Partial<{ title: string; owner_user_id: number | null; due_date: string | null; effort_points: number | null }>,
  ) => void;
  onSubtaskArchive: (actionId: number, subtaskId: number) => void;
  onAddSubtask: (actionId: number, title: string) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
  adding: boolean;
  newActionTitle: string;
  setNewActionTitle: (v: string) => void;
  onAddAction: () => void;
  onSubmitNewAction: (group: string, title: string) => void;
  onCancelAdd: () => void;
}) {
  const tone = groupTone(group.group);
  return (
    <div
      className={cn(
        "rounded-lg border border-line-tertiary bg-bg-primary overflow-hidden border-l-4",
        groupBorderClass(tone),
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between px-4 py-3 hover:bg-bg-secondary"
      >
        <div className="flex items-center gap-2">
          <IconChevronDown
            size={16}
            className={cn("text-ink-tertiary transition-transform", !expanded && "-rotate-90")}
          />
          <span className={cn("text-[13px] font-semibold", groupTextClass(tone))}>{group.label}</span>
          <span className="rounded-full bg-bg-tertiary px-2 py-0.5 text-[11px] font-medium text-ink-secondary">
            {group.count}
          </span>
          {group.overdue_count > 0 && (
            <span className="text-[11px] text-danger">{group.overdue_count} overdue</span>
          )}
        </div>
        <span className="text-[12px] text-ink-tertiary">Avg progress {group.avg_progress}%</span>
      </button>

      {expanded && (
        <div className="overflow-x-auto">
          <ColumnHeader gridTemplate={gridTemplate} />
          {group.items.map((item) => (
            <ActionRow
              key={item.id}
              projectId={projectId}
              item={item}
              gridTemplate={gridTemplate}
              selected={selected.has(item.id)}
              onSelect={() => onSelect(item.id)}
              onExpand={() => onExpand(item.id)}
              expanded={expandedRows.has(item.id)}
              detail={detailMap[item.id]}
              canManage={canManage}
              onStatusChange={onStatusChange}
              onPriorityChange={onPriorityChange}
              onOwnerChange={onOwnerChange}
              onDueChange={onDueChange}
              onArchive={() => onArchive(item.id, item.lock_version)}
              onRestore={() => onRestore(item.id)}
              onSubtaskStatusChange={onSubtaskStatusChange}
              onSubtaskFieldChange={onSubtaskFieldChange}
              onSubtaskArchive={onSubtaskArchive}
              onAddSubtask={onAddSubtask}
              members={members}
            />
          ))}

          {adding && (
            <div
              className="grid items-center gap-2 border-b border-line-tertiary bg-bg-secondary/30 px-3 py-2"
              style={{ gridTemplateColumns: gridTemplate }}
            >
              <div />
              <div className="flex min-w-0 items-center gap-2">
                <IconPlus size={14} className="text-ink-tertiary" />
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
                  className="min-w-0 flex-1 rounded border border-line-tertiary bg-bg-primary px-2 py-1 text-[13px] text-ink-primary outline-none focus:border-brand-500"
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

function ActionRow({
  projectId,
  item,
  gridTemplate,
  selected,
  onSelect,
  onExpand,
  expanded,
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
  selected: boolean;
  onSelect: () => void;
  onExpand: () => void;
  expanded: boolean;
  detail: ProjectAction | undefined;
  canManage: boolean;
  onStatusChange: (id: number, status: ProjectActionStatus, version: number) => void;
  onPriorityChange: (id: number, priority: ProjectActionPriority, version: number) => void;
  onOwnerChange: (id: number, owner_user_id: number | null, version: number) => void;
  onDueChange: (id: number, due_date: string | null, version: number) => void;
  onArchive: () => void;
  onRestore: () => void;
  onSubtaskStatusChange: (actionId: number, subtaskId: number, status: ProjectActionStatus) => void;
  onSubtaskFieldChange: (
    actionId: number,
    subtaskId: number,
    payload: Partial<{ title: string; owner_user_id: number | null; due_date: string | null; effort_points: number | null }>,
  ) => void;
  onSubtaskArchive: (actionId: number, subtaskId: number) => void;
  onAddSubtask: (actionId: number, title: string) => void;
  members: { user_id: number; display_name: string | null; email: string }[];
}) {
  const progress = item.percent_complete ?? 0;
  const overdue = isOverdue(item);
  const activeSubtasks = detail?.subtasks.filter((s) => !s.archived_at) ?? [];

  return (
    <div className="border-b border-line-tertiary last:border-b-0">
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
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onExpand();
              }}
              className="shrink-0"
              aria-label={expanded ? "Collapse subtasks" : "Expand subtasks"}
            >
              <IconChevronRight
                size={14}
                className={cn("text-ink-tertiary transition-transform", expanded && "rotate-90")}
              />
            </button>
            <Link
              href={`/projects/${projectId}/actions/${item.id}`}
              onClick={(e) => e.stopPropagation()}
              className="truncate text-[13px] font-semibold text-ink-primary hover:text-brand-600 hover:underline"
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
        <ProgressCell
          percent={progress}
          completed={item.completed_required_subtasks}
          total={item.required_subtasks}
          status={item.status}
        />
        <DueCell
          value={item.due_date}
          overdue={overdue}
          canManage={canManage}
          onChange={(v) => onDueChange(item.id, v, item.lock_version)}
        />
        <RiskCell impact={item.risk_impact} />
        <SourceCell item={item} />
        <div className="truncate text-[12px] text-ink-tertiary">{timeAgo(item.updated_at)}</div>
        <RowMenu projectId={projectId} item={item} canManage={canManage} onArchive={onArchive} onRestore={onRestore} />
      </div>

      {expanded && (
        <div className="border-t border-line-tertiary bg-bg-secondary/50 px-8 py-4">
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
    payload: Partial<{ title: string; owner_user_id: number | null; due_date: string | null; effort_points: number | null }>,
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
        <div
          className="grid items-center gap-2 border-b border-line-tertiary bg-bg-secondary/50 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-ink-tertiary"
          style={{ gridTemplateColumns: SUBTASK_GRID }}
        >
          <div />
          <div>Subitem</div>
          <div>Owner</div>
          <div>Status</div>
          <div>Due date</div>
          <div>Effort</div>
          <div className="text-center">Completed</div>
          <div className="text-right">Actions</div>
        </div>

        {subtasks.map((sub) => (
          <SubtaskRow
            key={sub.id}
            actionId={actionId}
            subtask={sub}
            canManage={canManage}
            onStatusChange={onStatusChange}
            onFieldChange={onFieldChange}
            onArchive={() => onArchive(actionId, sub.id)}
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
    payload: Partial<{ title: string; owner_user_id: number | null; due_date: string | null; effort_points: number | null }>,
  ) => void;
  onArchive: () => void;
  members: { user_id: number; display_name: string | null; email: string }[];
}) {
  const completed = subtask.status === "completed";
  const [title, setTitle] = useState(subtask.title);

  useEffect(() => {
    setTitle(subtask.title);
  }, [subtask.title]);

  return (
    <div
      className="grid items-center gap-2 rounded-md border border-line-tertiary px-2 py-1.5"
      style={{ gridTemplateColumns: SUBTASK_GRID }}
    >
      <div />
      {canManage ? (
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => title !== subtask.title && onFieldChange(actionId, subtask.id, { title })}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              title !== subtask.title && onFieldChange(actionId, subtask.id, { title });
              (e.target as HTMLInputElement).blur();
            }
          }}
          className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-[13px] text-ink-primary outline-none focus:border-brand-500"
        />
      ) : (
        <span className="text-[13px] text-ink-primary">{subtask.title}</span>
      )}

      <OwnerCell
        value={subtask.owner_user_id}
        members={members}
        canManage={canManage}
        onChange={(v) => onFieldChange(actionId, subtask.id, { owner_user_id: v })}
      />
      <StatusCell
        value={subtask.status}
        canManage={canManage}
        onChange={(v) => onStatusChange(actionId, subtask.id, v)}
      />
      <InlineDate
        value={subtask.due_date}
        canManage={canManage}
        onChange={(v) => onFieldChange(actionId, subtask.id, { due_date: v })}
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
        className="w-full rounded border border-line-tertiary bg-bg-primary px-1 py-0.5 text-center text-[12px] text-ink-primary outline-none focus:border-brand-500 disabled:bg-bg-secondary"
      />
      <div className="flex items-center justify-center">
        <input
          type="checkbox"
          checked={completed}
          disabled={!canManage}
          onChange={(e) =>
            onStatusChange(actionId, subtask.id, e.target.checked ? "completed" : "not_started")
          }
          aria-label={`Mark ${subtask.title} complete`}
        />
      </div>
      {canManage && (
        <div className="flex items-center justify-end">
          <button
            type="button"
            onClick={onArchive}
            className="text-ink-tertiary hover:text-danger"
            aria-label={`Archive ${subtask.title}`}
          >
            <IconTrash size={14} />
          </button>
        </div>
      )}
    </div>
  );
}

function ProgressCell({
  percent,
  completed,
  total,
  status,
}: {
  percent: number;
  completed: number;
  total: number;
  status: ProjectActionStatus;
}) {
  const segments = Math.max(total || 1, 1);
  const completedColor =
    status === "completed"
      ? "bg-emerald-500"
      : status === "in_progress"
        ? "bg-amber-500"
        : status === "blocked"
          ? "bg-red-500"
          : "bg-brand-500";
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex items-center gap-2">
        <div className="flex flex-1 gap-0.5">
          {Array.from({ length: segments }).map((_, i) => (
            <div
              key={i}
              className={cn(
                "h-2 flex-1 rounded-sm",
                i < (completed || 0) ? completedColor : "bg-bg-tertiary",
              )}
            />
          ))}
        </div>
        <span className="w-8 text-right text-[12px] font-semibold text-ink-primary">{percent}%</span>
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
  const [editing, setEditing] = useState(false);
  const display = formatDateShort(value) || "mm/dd/yyyy";
  return (
    <div className="flex items-center gap-1">
      <IconCalendar
        size={12}
        className={cn("shrink-0", overdue ? "text-danger" : "text-ink-tertiary")}
      />
      {canManage && editing ? (
        <input
          type="date"
          value={value ? value.split("T")[0] : ""}
          onChange={(e) => onChange(e.target.value || null)}
          onClick={(e) => e.stopPropagation()}
          onBlur={() => setEditing(false)}
          onKeyDown={(e) => e.key === "Enter" && setEditing(false)}
          autoFocus
          className={cn(
            "min-w-0 flex-1 rounded border bg-transparent px-1 py-0.5 text-[12px] outline-none",
            overdue ? "border-danger text-danger" : "border-line-tertiary text-ink-primary",
          )}
        />
      ) : (
        <button
          type="button"
          disabled={!canManage}
          onClick={(e) => {
            e.stopPropagation();
            setEditing(true);
          }}
          className={cn(
            "truncate text-left text-[12px] disabled:cursor-default hover:bg-bg-secondary",
            overdue ? "text-danger" : "text-ink-secondary",
          )}
        >
          {display}
        </button>
      )}
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
  const color = PRIORITY_TEXT_COLORS[value];
  if (!canManage) {
    return <span className={cn("text-[12px] font-medium", color)}>{PRIORITY_LABELS[value]}</span>;
  }
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as ProjectActionPriority)}
        onClick={(e) => e.stopPropagation()}
        className={cn(
          "w-full appearance-none border-0 bg-transparent py-1 pr-6 text-[12px] font-medium outline-none",
          color,
        )}
      >
        {Object.entries(PRIORITY_LABELS).map(([k, label]) => (
          <option key={k} value={k}>
            {label}
          </option>
        ))}
      </select>
      <IconChevronDown
        size={12}
        className={cn("pointer-events-none absolute right-0 top-1/2 -translate-y-1/2 opacity-70", color)}
      />
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
      <IconChevronDown
        size={12}
        className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-current opacity-70"
      />
    </div>
  );
}

function RiskCell({ impact }: { impact: string | null }) {
  if (!impact) return <span className="text-[12px] text-ink-tertiary">-</span>;
  return <Badge tone={riskImpactTone(impact)} size="sm">{riskImpactLabel(impact)}</Badge>;
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

function InlineDate({
  value,
  canManage,
  onChange,
}: {
  value: string | null;
  canManage: boolean;
  onChange: (v: string | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const display = formatDateShort(value) || "mm/dd/yyyy";
  if (canManage && editing) {
    return (
      <input
        type="date"
        value={value ? value.split("T")[0] : ""}
        onChange={(e) => onChange(e.target.value || null)}
        onClick={(e) => e.stopPropagation()}
        onBlur={() => setEditing(false)}
        onKeyDown={(e) => e.key === "Enter" && setEditing(false)}
        autoFocus
        className="rounded border border-line-tertiary bg-bg-primary px-1 py-0.5 text-[12px] text-ink-primary outline-none focus:border-brand-500"
      />
    );
  }
  return (
    <button
      type="button"
      disabled={!canManage}
      onClick={(e) => {
        e.stopPropagation();
        setEditing(true);
      }}
      className="truncate rounded px-1 py-0.5 text-left text-[12px] text-ink-secondary disabled:cursor-default disabled:hover:bg-transparent hover:bg-bg-secondary"
    >
      {display}
    </button>
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
