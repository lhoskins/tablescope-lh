"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconAlertCircle,
  IconCalendarDue,
  IconCheck,
  IconCircleCheck,
  IconPlus,
  IconSparkles,
  IconX,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { getHomeActionSummary, type HomeActionItem } from "@/lib/api/home-actions";
import {
  getPreferences,
  updatePreferences,
} from "@/lib/api/home-intelligence";

const DEFAULT_FOCUS = ["Revenue vs backlog", "ITSM SLA risk", "Actions due this week"];

function dueLabel(value: string | null): { text: string; overdue: boolean } {
  if (!value) return { text: "No due date", overdue: false };
  const due = new Date(value);
  const today = new Date();
  const days = Math.ceil((due.getTime() - today.getTime()) / 86_400_000);
  if (days < 0) return { text: `${Math.abs(days)}d overdue`, overdue: true };
  if (days === 0) return { text: "Due today", overdue: false };
  if (days === 1) return { text: "Due tomorrow", overdue: false };
  return { text: `Due ${due.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`, overdue: false };
}

function actionUpdateLabel(action: HomeActionItem): string {
  if (action.status === "completed") return "Action completed";
  if (action.status === "blocked") return "Action needs attention";
  if (action.status === "in_progress") return "Action is in progress";
  return "Action updated";
}

export function PersonalizedHome({
  projectCount,
  onPersonalize,
}: {
  projectCount: number;
  onPersonalize?: (handler: () => void) => void;
}) {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [draftFocus, setDraftFocus] = useState("");
  const { data: actionSummary, isLoading: actionsLoading } = useQuery({
    queryKey: ["home-action-summary"],
    queryFn: getHomeActionSummary,
  });
  const { data: preferences } = useQuery({
    queryKey: ["user-preferences"],
    queryFn: getPreferences,
  });
  const focusItems = preferences
    ? preferences.intelligence.home_focus
    : DEFAULT_FOCUS;

  const saveFocus = useMutation({
    mutationFn: (items: string[]) => updatePreferences({ home_focus: items }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["user-preferences"] }),
  });

  const personalize = () => inputRef.current?.focus();
  useEffect(() => onPersonalize?.(personalize), [onPersonalize]);

  function addFocus() {
    const value = draftFocus.trim();
    if (!value || focusItems.some((item) => item.toLowerCase() === value.toLowerCase())) return;
    saveFocus.mutate([...focusItems, value]);
    setDraftFocus("");
  }

  function removeFocus(item: string) {
    saveFocus.mutate(focusItems.filter((candidate) => candidate !== item));
  }

  const highlights = actionSummary?.highlights ?? {
    needs_attention: 0,
    due_this_week: 0,
    recently_completed: 0,
  };

  return (
    <div className="space-y-6">
      <section className="grid gap-5 rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-sm xl:grid-cols-[minmax(0,1fr)_260px] xl:items-center">
        <div>
          <div className="mb-2 flex items-center gap-2 text-caption font-medium uppercase tracking-wide text-ink-tertiary">
            <IconSparkles size={14} className="text-brand-500" />
            My focus · AI monitored
          </div>
          <h2 className="text-h2 text-ink-primary">What would you like Tablescope to watch for?</h2>
          <p className="mt-1 max-w-3xl text-body text-ink-secondary">
            Define the decisions, risks, KPIs, or business questions that matter to you. Tablescope uses these interests to prioritize Home.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            {focusItems.map((item) => (
              <span key={item} className="inline-flex h-8 items-center gap-1.5 rounded-full bg-bg-secondary px-3 text-small text-ink-primary">
                {item}
                <button type="button" aria-label={`Remove ${item}`} onClick={() => removeFocus(item)} className="text-ink-tertiary hover:text-ink-primary">
                  <IconX size={13} />
                </button>
              </span>
            ))}
            <div className="flex items-center gap-1">
              <input
                ref={inputRef}
                value={draftFocus}
                onChange={(event) => setDraftFocus(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") addFocus();
                }}
                placeholder="Add a focus"
                aria-label="Add a Home focus"
                className="h-8 w-36 rounded-md border border-line-tertiary bg-bg-primary px-2 text-small outline-none transition focus:w-56 focus:border-brand-500"
              />
              <Button variant="secondary" size="sm" onClick={addFocus} disabled={!draftFocus.trim() || saveFocus.isPending}>
                <IconPlus size={14} />
                Add
              </Button>
            </div>
          </div>
        </div>
        <dl className="space-y-3 border-t border-line-tertiary pt-4 xl:border-l xl:border-t-0 xl:pl-5 xl:pt-0">
          <div className="flex items-baseline justify-between gap-4"><dt className="text-small text-ink-tertiary">Projects monitored</dt><dd className="text-h3 text-ink-primary">{projectCount}</dd></div>
          <div className="flex items-baseline justify-between gap-4"><dt className="text-small text-ink-tertiary">Action updates</dt><dd className="text-h3 text-ink-primary">{actionSummary?.updates.length ?? 0}</dd></div>
          <div className="flex items-baseline justify-between gap-4"><dt className="text-small text-ink-tertiary">Focus topics</dt><dd className="text-h3 text-ink-primary">{focusItems.length}</dd></div>
        </dl>
      </section>

      <section>
        <div className="mb-3 flex items-end justify-between gap-4">
          <div><h2 className="text-h3 text-ink-primary">Action highlights</h2><p className="mt-0.5 text-small text-ink-tertiary">Signals derived from project actions—not a separate task board.</p></div>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          {[
            { label: "Needs attention", value: highlights.needs_attention, icon: IconAlertCircle, tone: "text-danger", copy: "Blocked or overdue work across your visible projects." },
            { label: "Due in 7 days", value: highlights.due_this_week, icon: IconCalendarDue, tone: "text-amber-600", copy: "Active actions that need an owner response this week." },
            { label: "Recently completed", value: highlights.recently_completed, icon: IconCircleCheck, tone: "text-emerald-600", copy: "Actions completed during the last seven days." },
          ].map((item) => (
            <article key={item.label} className="min-h-32 rounded-xl border border-line-tertiary bg-bg-primary p-4 shadow-sm">
              <div className="flex items-center justify-between gap-3"><div className="flex items-center gap-2 text-[13px] font-medium text-ink-primary"><item.icon size={16} className={item.tone} />{item.label}</div><span className="text-h1 text-ink-primary">{actionsLoading ? "—" : item.value}</span></div>
              <p className="mt-3 text-small leading-relaxed text-ink-tertiary">{item.copy}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(300px,.65fr)]">
        <div>
          <div className="mb-3 flex items-end justify-between gap-3"><div><h2 className="text-h3 text-ink-primary">Assigned to me</h2><p className="mt-0.5 text-small text-ink-tertiary">A concise list of work requiring your response.</p></div></div>
          <div className="overflow-hidden rounded-xl border border-line-tertiary bg-bg-primary shadow-sm">
            {actionSummary?.assigned.length ? actionSummary.assigned.map((action) => {
              const due = dueLabel(action.due_date);
              return (
                <Link key={action.id} href={`/projects/${action.project_id}/actions`} className="grid grid-cols-[24px_minmax(0,1fr)_auto] items-center gap-3 border-b border-line-tertiary px-4 py-3 last:border-b-0 hover:bg-bg-secondary">
                  <span className="flex h-[18px] w-[18px] items-center justify-center rounded-full border border-line-secondary text-transparent"><IconCheck size={11} /></span>
                  <span className="min-w-0"><span className="block truncate text-[13px] font-medium text-ink-primary">{action.title}</span><span className="mt-0.5 block text-caption text-ink-tertiary">{action.project_name} · Priority: {action.priority}</span></span>
                  <span className={`text-caption ${due.overdue ? "font-medium text-danger" : "text-ink-tertiary"}`}>{due.text}</span>
                </Link>
              );
            }) : <p className="px-4 py-8 text-center text-small text-ink-tertiary">No active actions are assigned to you.</p>}
          </div>
        </div>
        <div>
          <div className="mb-3"><h2 className="text-h3 text-ink-primary">Updates for you</h2><p className="mt-0.5 text-small text-ink-tertiary">Recent changes across your project actions.</p></div>
          <div className="overflow-hidden rounded-xl border border-line-tertiary bg-bg-primary px-4 shadow-sm">
            {actionSummary?.updates.length ? actionSummary.updates.slice(0, 4).map((action) => (
              <Link key={action.id} href={`/projects/${action.project_id}/actions`} className="flex gap-3 border-b border-line-tertiary py-3 last:border-b-0">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-bg-secondary text-brand-500"><IconSparkles size={14} /></span>
                <span className="min-w-0"><strong className="block truncate text-small font-medium text-ink-primary">{actionUpdateLabel(action)}: {action.title}</strong><span className="mt-0.5 block text-caption text-ink-tertiary">{action.project_name}</span></span>
              </Link>
            )) : <p className="py-8 text-center text-small text-ink-tertiary">No project action updates yet.</p>}
          </div>
        </div>
      </section>
    </div>
  );
}
