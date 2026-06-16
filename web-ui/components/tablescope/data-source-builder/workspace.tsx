"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { NewProjectDialog } from "@/components/tablescope/project/new-project-dialog";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { ConfirmationModal } from "./confirmation-modal";
import { LeftPanel } from "./left-panel";
import { RightPanel } from "./right-panel";
import { SourceTray } from "./source-tray";
import { SourceTypePickerModal } from "./source-type-picker-modal";
import type { SourceCategory } from "./util";

export function DataSourceBuilderWorkspace({
  tenantName,
}: {
  tenantName: string;
}) {
  const queryClient = useQueryClient();
  const reset = useBuilderStore((s) => s.reset);

  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerCategory, setPickerCategory] = useState<
    SourceCategory | undefined
  >(undefined);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [newProjectOpen, setNewProjectOpen] = useState(false);

  // Reset the session when the user leaves the builder.
  useEffect(() => {
    return () => reset();
  }, [reset]);

  // Warn before a full page unload (refresh/close) when changes are pending.
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      const { adding, removing } = useBuilderStore.getState().getPendingChanges();
      if (adding.length > 0 || removing.length > 0) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, []);

  const openPicker = (category?: SourceCategory) => {
    setPickerCategory(category);
    setPickerOpen(true);
  };

  return (
    <div className="flex h-[calc(100vh-8.5rem)] flex-col overflow-hidden rounded-lg border border-line-tertiary bg-bg-primary">
      <SourceTray onAddSource={openPicker} />

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <LeftPanel
          className="w-[500px] flex-shrink-0 overflow-hidden border-r border-line-tertiary"
          onAddSource={openPicker}
        />
        <RightPanel
          className="min-w-0 flex-1 overflow-hidden"
          tenantName={tenantName}
          onReview={() => setConfirmOpen(true)}
          onNewProject={() => setNewProjectOpen(true)}
        />
      </div>

      <SourceTypePickerModal
        open={pickerOpen}
        initialCategory={pickerCategory}
        onClose={() => setPickerOpen(false)}
      />

      <ConfirmationModal
        open={confirmOpen}
        tenantName={tenantName}
        onClose={() => setConfirmOpen(false)}
      />

      <NewProjectDialog
        open={newProjectOpen}
        redirect={false}
        onClose={() => setNewProjectOpen(false)}
        onCreated={() =>
          queryClient.invalidateQueries({
            queryKey: ["projects", "summaries"],
          })
        }
      />
    </div>
  );
}
