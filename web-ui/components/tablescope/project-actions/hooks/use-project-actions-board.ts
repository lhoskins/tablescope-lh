"use client";

import { useCallback, useMemo, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { projectActionsApi, type ProjectActionFilters, type ProjectActionListItem, type ProjectActionListResponse, type ProjectActionStatus, type ProjectActionPriority, type ProjectActionSortBy, type ProjectActionGroupBy, type ProjectActionView, type ProjectActionSubtask, type ProjectAction } from "@/lib/api/project-actions";
import { useCurrentUser } from "@/lib/ui/use-shell-data";

export interface BoardPreferences {
  view: ProjectActionView;
  groupBy: ProjectActionGroupBy;
  sortBy: ProjectActionSortBy;
  sortDirection: "asc" | "desc";
  visibleColumns: string[];
  collapsedGroups: string[];
}

const DEFAULT_PREFERENCES: BoardPreferences = {
  view: "board",
  groupBy: "status",
  sortBy: "updated",
  sortDirection: "desc",
  visibleColumns: ["owner", "status", "priority", "progress", "due", "risk", "source", "updated"],
  collapsedGroups: [],
};

function prefsKey(projectId: string, tenant: string, userId?: number) {
  return `tablescope:project-actions-prefs:${tenant}:${projectId}:${userId ?? "anon"}`;
}

export function useProjectActionsBoard(
  projectId: string,
  tenantSlug: string,
  userId?: number,
) {
  const queryClient = useQueryClient();
  const { data: user } = useCurrentUser();

  const [prefs, setPrefs] = useState<BoardPreferences>(() => {
    if (typeof window === "undefined") return DEFAULT_PREFERENCES;
    try {
      const raw = window.localStorage.getItem(prefsKey(projectId, tenantSlug, userId));
      if (raw) return { ...DEFAULT_PREFERENCES, ...JSON.parse(raw) };
    } catch {}
    return DEFAULT_PREFERENCES;
  });

  const savePrefs = useCallback(
    (next: Partial<BoardPreferences>) => {
      setPrefs((prev) => {
        const updated = { ...prev, ...next };
        try {
          window.localStorage.setItem(
            prefsKey(projectId, tenantSlug, userId),
            JSON.stringify(updated),
          );
        } catch {}
        return updated;
      });
    },
    [projectId, tenantSlug, userId],
  );

  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<ProjectActionFilters>({});

  const currentUserId = user?.user.id;

  const boardFilters = useMemo<ProjectActionFilters>(() => {
    const base: ProjectActionFilters = {
      group_by: prefs.groupBy,
      sort_by: prefs.sortBy,
      sort_direction: prefs.sortDirection,
      q: search || undefined,
      ...filters,
    };
    if (prefs.view === "my-actions") {
      base.owner_user_id = currentUserId;
    }
    if (prefs.view === "archived") {
      base.include_archived = true;
    }
    return base;
  }, [prefs, search, filters, currentUserId]);

  const boardQuery = useQuery({
    queryKey: ["project", projectId, "actions", "board", boardFilters],
    queryFn: () => projectActionsApi.board(projectId, boardFilters),
  });

  const detailCache = useMemo(
    () => new Map<number, ProjectAction>(),
    [],
  );

  const fetchDetail = useCallback(
    async (actionId: number) => {
      const cached = detailCache.get(actionId);
      if (cached) return cached;
      const data = await projectActionsApi.get(projectId, actionId);
      detailCache.set(actionId, data);
      return data;
    },
    [projectId, detailCache],
  );

  const invalidateBoard = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: ["project", projectId, "actions"],
    });
  }, [queryClient, projectId]);

  const updateAction = useMutation({
    mutationFn: ({
      actionId,
      payload,
    }: {
      actionId: number;
      payload: Parameters<typeof projectActionsApi.update>[2];
    }) => projectActionsApi.update(projectId, actionId, payload),
    onSuccess: () => invalidateBoard(),
  });

  const archiveAction = useMutation({
    mutationFn: (actionId: number) => projectActionsApi.archive(projectId, actionId),
    onSuccess: () => invalidateBoard(),
  });

  const restoreAction = useMutation({
    mutationFn: (actionId: number) => projectActionsApi.restore(projectId, actionId),
    onSuccess: () => invalidateBoard(),
  });

  const createSubtask = useMutation({
    mutationFn: ({
      actionId,
      payload,
    }: {
      actionId: number;
      payload: Parameters<typeof projectActionsApi.createSubtask>[2];
    }) => projectActionsApi.createSubtask(projectId, actionId, payload),
    onSuccess: () => invalidateBoard(),
  });

  const updateSubtask = useMutation({
    mutationFn: ({
      actionId,
      subtaskId,
      payload,
    }: {
      actionId: number;
      subtaskId: number;
      payload: Parameters<typeof projectActionsApi.updateSubtask>[3];
    }) => projectActionsApi.updateSubtask(projectId, actionId, subtaskId, payload),
    onSuccess: () => invalidateBoard(),
  });

  const archiveSubtask = useMutation({
    mutationFn: ({
      actionId,
      subtaskId,
    }: {
      actionId: number;
      subtaskId: number;
    }) => projectActionsApi.archiveSubtask(projectId, actionId, subtaskId),
    onSuccess: () => invalidateBoard(),
  });

  const bulkUpdate = useMutation({
    mutationFn: (payload: Parameters<typeof projectActionsApi.bulkUpdate>[1]) =>
      projectActionsApi.bulkUpdate(projectId, payload),
    onSuccess: () => invalidateBoard(),
  });

  return {
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
  };
}

export type { ProjectActionListItem, ProjectActionListResponse, ProjectActionSubtask, ProjectAction };
