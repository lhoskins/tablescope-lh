"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  IconClipboardList,
  IconPlus,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { AutosizeTextarea } from "@/components/ui/autosize-textarea";
import { cn } from "@/lib/cn";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import { useProjectMembers } from "@/lib/ui/use-project-data";
import { useToasts } from "@/components/ui/toast";
import {
  projectActionsApi,
  type CreateProjectActionSubtaskPayload,
} from "@/lib/api/project-actions";

export interface ActionableInsight {
  insightId?: string | null;
  insightType: string;
  title: string;
  summary: string;
  severity?: string;
  projectId: string;
  projectName: string;
  recommendedAction?: string | null;
  sources?: { tables?: string[]; documents?: string[] };
  supportingSources?: string[];
  explanation?: Record<string, unknown> | null;
}

interface CreateActionFromInsightDialogProps {
  open: boolean;
  onClose: () => void;
  insight: ActionableInsight | null;
}

function canManageActions(role?: string, isSuperAdmin?: boolean) {
  if (isSuperAdmin) return true;
  const allowed = [
    "member",
    "editor",
    "db_admin",
    "admin",
    "tenant_admin",
    "root_admin",
  ];
  return Boolean(role && allowed.includes(role.toLowerCase()));
}

function dateToInput(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toISOString().split("T")[0] ?? "";
  } catch {
    return "";
  }
}

function inputToDate(value: string): string | null {
  if (!value) return null;
  try {
    return new Date(value).toISOString();
  } catch {
    return null;
  }
}

function trimText(v: string | null | undefined): string {
  return (v || "").trim();
}

function buildSnapshot(insight: ActionableInsight): Record<string, unknown> {
  const sources = {
    tables: insight.sources?.tables ?? [],
    documents: insight.sources?.documents ?? [],
  };
  return {
    title: insight.title,
    summary: insight.summary,
    severity: insight.severity,
    project_id: insight.projectId,
    project_name: insight.projectName,
    insight_type: insight.insightType,
    recommended_action: insight.recommendedAction,
    sources,
    supporting_sources: insight.supportingSources ?? [],
    explanation: insight.explanation,
  };
}

export function CreateActionFromInsightDialog({
  open,
  onClose,
  insight,
}: CreateActionFromInsightDialogProps) {
  const router = useRouter();
  const { data: identity } = useCurrentUser();
  const { data: members = [] } = useProjectMembers(insight?.projectId ?? "");
  const { push: pushToast } = useToasts();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<"low" | "medium" | "high" | "critical">("medium");
  const [status, setStatus] = useState<"not_started" | "in_progress" | "blocked">("not_started");
  const [ownerUserId, setOwnerUserId] = useState<string>("");
  const [dueDate, setDueDate] = useState("");
  const [subtasks, setSubtasks] = useState<CreateProjectActionSubtaskPayload[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [draftLoading, setDraftLoading] = useState(false);
  const [existingCount, setExistingCount] = useState(0);
  const [existingIds, setExistingIds] = useState<number[]>([]);

  const idempotencyKey = useMemo(() => {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
      return crypto.randomUUID();
    }
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }, []);

  useEffect(() => {
    if (!open || !insight) return;

    const recommended = trimText(insight.recommendedAction);
    const cardTitle = trimText(insight.title);
    const cardSummary = trimText(insight.summary);

    setTitle(recommended || cardTitle || "");
    setDescription(
      recommended
        ? `${cardTitle}\n\nSummary: ${cardSummary}\n\nRecommended action: ${recommended}`
        : `${cardTitle}\n\nSummary: ${cardSummary}`,
    );
    setPriority("medium");
    setStatus("not_started");
    setOwnerUserId(String(identity?.user?.id ?? ""));
    setDueDate("");
    setSubtasks([]);
    setExistingCount(0);
    setExistingIds([]);

    const currentUserId = identity?.user?.id;
    if (currentUserId && members.some((m) => m.user_id === currentUserId)) {
      setOwnerUserId(String(currentUserId));
    }

    let cancelled = false;

    // Fetch a structured AI draft; keep the manual pre-fill as a fallback.
    if (insight.projectId) {
      setDraftLoading(true);
      projectActionsApi
        .draftFromInsight(insight.projectId, {
          insight_type: insight.insightType,
          title: insight.title,
          summary: insight.summary,
          recommended_action: insight.recommendedAction,
          severity: insight.severity,
          sources: {
            tables: insight.sources?.tables ?? [],
            documents: insight.sources?.documents ?? [],
          },
          supporting_sources: insight.supportingSources ?? [],
          explanation: insight.explanation ?? undefined,
        })
        .then((draft) => {
          if (cancelled) return;
          if (draft.title) setTitle(trimText(draft.title));
          if (draft.description) setDescription(trimText(draft.description));
          if (draft.subtasks?.length > 0) {
            setSubtasks(
              draft.subtasks.map((st) => ({
                title: trimText(st.title) || "",
                description: st.description || null,
                status: st.status ?? "not_started",
                percent_complete: st.percent_complete ?? 0,
                owner_user_id: (st.owner_user_id ?? Number(identity?.user?.id ?? "")) || null,
                due_date: st.due_date ?? null,
                is_required: st.is_required ?? true,
              })),
            );
          }
        })
        .catch(() => {
          // leave the manual pre-fill in place
        })
        .finally(() => setDraftLoading(false));
    }

    return () => {
      cancelled = true;
    };
  }, [open, insight, identity, members]);

  useEffect(() => {
    if (!open || !insight?.projectId || !insight.title) return;
    projectActionsApi
      .countForInsight(insight.projectId, {
        source_insight_id: insight.insightId,
        source_insight_type: insight.insightType,
        source_insight_title: insight.title,
        source_insight_snapshot: buildSnapshot(insight as NonNullable<typeof insight>),
      })
      .then((res) => {
        setExistingCount(res.count);
        setExistingIds(res.action_ids);
      })
      .catch(() => {
        setExistingCount(0);
        setExistingIds([]);
      });
  }, [open, insight]);

  if (!open || !insight) return null;

  const allowed = canManageActions(identity?.user?.rawRole, identity?.user?.isSuperAdmin);
  if (!allowed) {
    return null;
  }

  const ownerOptions = [
    { value: "", label: "No owner" },
    ...members.map((m) => ({
      value: String(m.user_id),
      label: m.display_name || m.email,
    })),
  ];

  function updateSubtask(index: number, patch: Partial<CreateProjectActionSubtaskPayload>) {
    setSubtasks((prev) =>
      prev.map((s, i) => (i === index ? { ...s, ...patch } : s)),
    );
  }

  function addSubtask() {
    setSubtasks((prev) => [
      ...prev,
      {
        title: "",
        description: null,
        status: "not_started",
        percent_complete: 0,
        owner_user_id: ownerUserId ? Number(ownerUserId) : null,
        due_date: null,
        is_required: true,
      },
    ]);
  }

  function removeSubtask(index: number) {
    setSubtasks((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const cleanTitle = trimText(title);
    if (!cleanTitle || submitting) return;

    setSubmitting(true);
    try {
      const payload = {
        title: cleanTitle,
        description: trimText(description) || null,
        status,
        priority,
        owner_user_id: ownerUserId ? Number(ownerUserId) : null,
        due_date: inputToDate(dueDate),
        source_type: "insight",
        source_insight_id: insight!.insightId,
        source_insight_type: insight!.insightType,
        source_insight_title: insight!.title,
        source_insight_snapshot: buildSnapshot(insight!),
        initial_subtasks: subtasks
          .map((s) => ({ ...s, title: trimText(s.title) }))
          .filter((s) => s.title.length > 0)
          .map((s) => ({
            ...s,
            owner_user_id: s.owner_user_id ?? null,
            due_date: s.due_date ?? null,
          })),
        idempotency_key: idempotencyKey,
      };

      const action = await projectActionsApi.create(insight!.projectId, payload);
      pushToast(`Action created: ${action.title}`, "success");
      onClose();
      router.push(`/projects/${insight!.projectId}/actions/${action.id}`);
    } catch (err) {
      pushToast(err instanceof Error ? err.message : "Failed to create action", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-hidden rounded-lg border border-line-secondary bg-bg-primary shadow-lg">
        <div className="flex items-center justify-between border-b border-line-tertiary px-5 py-3">
          <div className="flex items-center gap-2">
            <IconClipboardList size={18} className="text-brand-500" />
            <h2 className="text-h4 font-semibold text-ink-primary">Create Project Action</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
            aria-label="Close"
          >
            <IconX size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 overflow-y-auto p-5">
          {existingCount > 0 && (
            <div className="rounded-md border border-brand-200 bg-brand-50 p-3 text-small text-brand-700">
              {existingCount} existing action{existingCount === 1 ? "" : "s"} linked to this insight.
              {existingIds.length > 0 && (
                <>
                  {" "}
                  <button
                    type="button"
                    onClick={() =>
                      router.push(`/projects/${insight.projectId}/actions/${existingIds[0]}`)
                    }
                    className="font-medium underline"
                  >
                    View action{existingIds.length === 1 ? "" : "s"}
                  </button>
                </>
              )}
            </div>
          )}

          <div>
            <label className="mb-1 block text-caption text-ink-secondary">Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary outline-none focus:border-brand-500"
              placeholder="Action title"
              required
            />
          </div>

          <div>
            <label className="mb-1 block text-caption text-ink-secondary">Description</label>
            <AutosizeTextarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              minRows={3}
              className="w-full rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary"
              placeholder="Describe the action and recommended next steps..."
            />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-caption text-ink-secondary">Priority</label>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value as typeof priority)}
                className="w-full rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary"
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-caption text-ink-secondary">Status</label>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value as typeof status)}
                className="w-full rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary"
              >
                <option value="not_started">Not started</option>
                <option value="in_progress">In progress</option>
                <option value="blocked">Blocked</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-caption text-ink-secondary">Owner</label>
              <select
                value={ownerUserId}
                onChange={(e) => setOwnerUserId(e.target.value)}
                className="w-full rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary"
              >
                {ownerOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-caption text-ink-secondary">Due date</label>
              <input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className="w-full rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary"
              />
            </div>
          </div>

          <div className="rounded-md border border-line-tertiary bg-bg-secondary/50 p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-small font-medium text-ink-primary">Initial subtasks</span>
              <Button type="button" variant="secondary" size="sm" onClick={addSubtask}>
                <IconPlus size={14} />
                Add subtask
              </Button>
            </div>

            <div className="space-y-2">
              {subtasks.map((st, i) => (
                <div key={i} className="rounded-md border border-line-tertiary bg-bg-primary p-2">
                  <div className="flex items-start gap-2">
                    <input
                      type="text"
                      value={st.title}
                      onChange={(e) => updateSubtask(i, { title: e.target.value })}
                      placeholder="Subtask title"
                      className="min-w-0 flex-1 rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-[13px] text-ink-primary"
                    />
                    <button
                      type="button"
                      onClick={() => removeSubtask(i)}
                      className="rounded-md p-1 text-ink-tertiary hover:bg-bg-secondary hover:text-danger"
                      aria-label="Remove subtask"
                    >
                      <IconTrash size={14} />
                    </button>
                  </div>
                  <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                    <select
                      value={st.status}
                      onChange={(e) =>
                        updateSubtask(i, { status: e.target.value as typeof st.status })
                      }
                      className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-[13px] text-ink-primary"
                    >
                      <option value="not_started">Not started</option>
                      <option value="in_progress">In progress</option>
                      <option value="blocked">Blocked</option>
                      <option value="completed">Completed</option>
                    </select>
                    <select
                      value={st.owner_user_id ?? ""}
                      onChange={(e) =>
                        updateSubtask(i, {
                          owner_user_id: e.target.value ? Number(e.target.value) : null,
                        })
                      }
                      className="rounded-md border border-line-tertiary bg-bg-primary px-2 py-1 text-[13px] text-ink-primary"
                    >
                      <option value="">No owner</option>
                      {members.map((m) => (
                        <option key={m.user_id} value={m.user_id}>
                          {m.display_name || m.email}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              ))}
              {subtasks.length === 0 && (
                <div className="py-2 text-center text-small text-ink-tertiary">
                  No subtasks yet. Add optional subtasks to track progress.
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 border-t border-line-tertiary pt-4">
            <Button type="button" variant="ghost" onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={!trimText(title) || submitting || draftLoading}>
              {submitting ? "Creating..." : draftLoading ? "Drafting..." : "Create action"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
