"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  IconArrowLeft,
  IconArrowRight,
  IconCheck,
  IconDatabase,
  IconFolderShare,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { NewProjectDialog } from "@/components/tablescope/project/new-project-dialog";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { ConfirmationModal } from "./confirmation-modal";
import { ConnectedDatabases } from "./connected-databases";
import { LeftPanel } from "./left-panel";
import { RightPanel } from "./right-panel";
import { SourceTray } from "./source-tray";
import { SourceTypePickerModal } from "./source-type-picker-modal";
import type { SourceCategory } from "./util";

type Step = 1 | 2;

const STEPS: { n: Step; label: string; icon: typeof IconDatabase }[] = [
  { n: 1, label: "Create Data Sources", icon: IconDatabase },
  { n: 2, label: "Assign Projects", icon: IconFolderShare },
];

function Stepper({ step }: { step: Step }) {
  return (
    <div className="flex items-center gap-3">
      {STEPS.map((s, i) => {
        const active = s.n === step;
        const done = s.n < step;
        const Icon = done ? IconCheck : s.icon;
        return (
          <div key={s.n} className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-full text-[12px] font-semibold",
                  active && "bg-brand text-brand-fg",
                  done && "bg-success text-white",
                  !active && !done && "bg-bg-tertiary text-ink-tertiary",
                )}
              >
                {done ? <Icon size={14} /> : s.n}
              </span>
              <span
                className={cn(
                  "text-[13px] font-medium",
                  active ? "text-ink-primary" : "text-ink-tertiary",
                )}
              >
                {s.label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <span className="h-px w-8 bg-line-secondary" />
            )}
          </div>
        );
      })}
    </div>
  );
}

export function DataSourceBuilderWorkspace({
  tenantName,
}: {
  tenantName: string;
}) {
  const queryClient = useQueryClient();
  const reset = useBuilderStore((s) => s.reset);
  const sources = useBuilderStore((s) => s.sources);

  const [step, setStep] = useState<Step>(1);
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

  const stepHint =
    step === 1
      ? "Step 1 of 2: Create data sources from files or connected databases."
      : "Step 2 of 2: Assign selected data sources to project(s).";

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col gap-3">
      {/* Stepper header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Stepper step={step} />
          <p className="mt-1.5 text-small text-ink-tertiary">{stepHint}</p>
        </div>
        {step === 1 ? (
          <Button
            variant="primary"
            disabled={sources.length === 0}
            onClick={() => setStep(2)}
          >
            Next <IconArrowRight size={15} />
          </Button>
        ) : (
          <Button variant="secondary" onClick={() => setStep(1)}>
            <IconArrowLeft size={15} /> Back
          </Button>
        )}
      </div>

      {step === 1 ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-line-tertiary bg-bg-primary">
          <SourceTray onAddSource={openPicker} />

          {/* Connected databases cards */}
          <div className="border-b border-line-tertiary px-4 py-3">
            <h3 className="mb-2 text-h3 text-ink-primary">
              Connected Databases
            </h3>
            <ConnectedDatabases />
          </div>

          <div className="min-h-0 flex-1 overflow-hidden">
            <LeftPanel className="h-full overflow-hidden" onAddSource={openPicker} />
          </div>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 overflow-hidden rounded-lg border border-line-tertiary bg-bg-primary">
          <RightPanel
            className="min-w-0 flex-1 overflow-hidden"
            tenantName={tenantName}
            onReview={() => setConfirmOpen(true)}
            onNewProject={() => setNewProjectOpen(true)}
          />
        </div>
      )}

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
