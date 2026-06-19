"use client";

import { useMemo, useState } from "react";
import { IconTrash, IconUserPlus } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  useAddProjectMember,
  useAddableUsers,
  useProjectMembers,
  useRemoveProjectMember,
  useUpdateProjectMemberRole,
} from "@/lib/ui/use-project-data";

const ROLES = ["admin", "editor", "viewer"] as const;

const ROLE_HINT: Record<string, string> = {
  owner: "Full control of the project",
  admin: "Manage members and edit queries",
  editor: "Create and edit queries",
  viewer: "View only — no editing",
};

function memberName(m: { display_name: string | null; email: string }): string {
  return m.display_name?.trim() || m.email;
}

export function MembersDialog({
  open,
  projectId,
  onClose,
}: {
  open: boolean;
  projectId: string;
  onClose: () => void;
}) {
  const { data: members } = useProjectMembers(projectId);
  const addable = useAddableUsers(projectId, open);
  const addMember = useAddProjectMember(projectId);
  const updateRole = useUpdateProjectMemberRole(projectId);
  const removeMember = useRemoveProjectMember(projectId);

  const [selectedUser, setSelectedUser] = useState("");
  const [newRole, setNewRole] = useState<string>("viewer");
  const [error, setError] = useState<string | null>(null);

  // A successful addable-users fetch means the current user may manage members.
  const canManage = addable.isSuccess;
  const activeMembers = useMemo(
    () => (members ?? []).filter((m) => m.is_active),
    [members],
  );

  if (!open) return null;

  function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!selectedUser) return;
    addMember.mutate(
      { userId: Number(selectedUser), role: newRole },
      {
        onSuccess: () => {
          setSelectedUser("");
          setNewRole("viewer");
        },
        onError: (err: Error) => setError(err.message),
      },
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-xl border border-line-tertiary bg-bg-primary shadow-lg">
        <div className="flex items-center justify-between border-b border-line-tertiary px-5 py-4">
          <h2 className="text-h2 text-ink-primary">Project members</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-small text-ink-tertiary hover:text-ink-primary"
          >
            Close
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {canManage && (
            <form
              onSubmit={handleAdd}
              className="mb-4 rounded-lg border border-line-secondary bg-bg-secondary/40 p-3"
            >
              <label className="mb-1 block text-small font-medium text-ink-secondary">
                Add a user
              </label>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={selectedUser}
                  onChange={(e) => setSelectedUser(e.target.value)}
                  className="h-9 min-w-0 flex-1 rounded-md border border-line-secondary bg-bg-primary px-2 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
                >
                  <option value="">
                    {(addable.data ?? []).length === 0
                      ? "No users available to add"
                      : "Select a user…"}
                  </option>
                  {(addable.data ?? []).map((u) => (
                    <option key={u.user_id} value={u.user_id}>
                      {u.display_name?.trim()
                        ? `${u.display_name} (${u.email})`
                        : u.email}
                    </option>
                  ))}
                </select>
                <select
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value)}
                  className="h-9 rounded-md border border-line-secondary bg-bg-primary px-2 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {r[0].toUpperCase() + r.slice(1)}
                    </option>
                  ))}
                </select>
                <Button
                  variant="primary"
                  type="submit"
                  disabled={!selectedUser || addMember.isPending}
                >
                  <IconUserPlus size={14} />
                  Add
                </Button>
              </div>
              <p className="mt-1.5 text-caption text-ink-tertiary">
                {ROLE_HINT[newRole]}
              </p>
              {error && (
                <p className="mt-1.5 text-small text-red-600">{error}</p>
              )}
            </form>
          )}

          <ul className="divide-y divide-line-tertiary">
            {activeMembers.length === 0 && (
              <li className="py-8 text-center text-small text-ink-tertiary">
                No members yet.
              </li>
            )}
            {activeMembers.map((m) => {
              const isOwner = m.role === "owner";
              return (
                <li
                  key={m.user_id}
                  className="flex items-center gap-3 py-2.5"
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-50 text-[11px] font-semibold text-brand-700">
                    {memberName(m).slice(0, 2).toUpperCase()}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-medium text-ink-primary">
                      {memberName(m)}
                    </div>
                    <div className="truncate text-caption text-ink-tertiary">
                      {m.email}
                    </div>
                  </div>
                  {canManage && !isOwner ? (
                    <select
                      value={m.role}
                      onChange={(e) =>
                        updateRole.mutate({
                          userId: m.user_id,
                          role: e.target.value,
                        })
                      }
                      className="h-8 rounded-md border border-line-secondary bg-bg-primary px-2 text-[12px] text-ink-primary focus:border-brand-500 focus:outline-none"
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r[0].toUpperCase() + r.slice(1)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <Badge tone={isOwner ? "success" : "neutral"}>
                      {m.role[0].toUpperCase() + m.role.slice(1)}
                    </Badge>
                  )}
                  {canManage && !isOwner && (
                    <button
                      type="button"
                      aria-label={`Remove ${memberName(m)}`}
                      onClick={() => removeMember.mutate(m.user_id)}
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink-tertiary hover:bg-bg-secondary hover:text-red-600"
                    >
                      <IconTrash size={15} />
                    </button>
                  )}
                </li>
              );
            })}
          </ul>

          {!canManage && (
            <p className="mt-3 text-caption text-ink-tertiary">
              Only the project owner or an admin can add or change members.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
