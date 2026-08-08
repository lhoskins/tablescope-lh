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
} from "@tabler/icons-react";import { STATUS_ORDER } from "./project-actions-workspace/status-order";
import { STATUS_BADGE_LABELS } from "./project-actions-workspace/status-badge-labels";
import { DUE_STATE_ORDER } from "./project-actions-workspace/due-state-order";
import { isOverdue } from "./project-actions-workspace/is-overdue";
import { canManageActions } from "./project-actions-workspace/can-manage-actions";
import { groupLabel } from "./project-actions-workspace/group-label";
import { useGridTemplate } from "./project-actions-workspace/use-grid-template";
import { TimelineView } from "./project-actions-workspace/timeline-view";
import { SummaryCard } from "./project-actions-workspace/summary-card";
import { Toolbar } from "./project-actions-workspace/toolbar";
import { GroupSection } from "./project-actions-workspace/group-section";



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
