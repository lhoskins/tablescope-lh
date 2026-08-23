"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  closeWorkspaceTab,
  loadWorkspaceTabs,
  saveWorkspaceTabs,
  upsertWorkspaceTab,
  type WorkspaceTab,
} from "./workspace-tabs-storage";

/** Persists the project's open-tab strip and derives which tab (if any) the
 *  current page represents. Reading `activeItem` from the page's own already-
 *  fetched data (rather than fetching resource lists here) keeps this hook
 *  from adding network requests for tabs the user isn't currently viewing. */
export function useWorkspaceTabs(projectId: string, activeItem: WorkspaceTab | null) {
  const router = useRouter();
  const [tabs, setTabs] = useState<WorkspaceTab[]>([]);

  useEffect(() => {
    setTabs(loadWorkspaceTabs(projectId));
  }, [projectId]);

  useEffect(() => {
    if (!activeItem) return;
    setTabs((prev) => {
      const next = upsertWorkspaceTab(prev, activeItem);
      saveWorkspaceTabs(projectId, next);
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    projectId,
    activeItem?.type,
    activeItem?.id,
    activeItem?.label,
    activeItem?.href,
    activeItem?.numericId,
  ]);

  const activeKey = activeItem ? `${activeItem.type}:${activeItem.id}` : null;

  function activate(tab: WorkspaceTab) {
    router.push(tab.href);
  }

  function closeTab(tab: WorkspaceTab) {
    const key = `${tab.type}:${tab.id}`;
    const wasActive = activeKey === key;
    setTabs((prev) => {
      const next = closeWorkspaceTab(prev, tab.type, tab.id);
      saveWorkspaceTabs(projectId, next);
      if (wasActive) {
        const fallback = next[next.length - 1];
        router.push(fallback ? fallback.href : `/projects/${projectId}`);
      }
      return next;
    });
  }

  return { tabs, activeKey, activate, closeTab };
}
