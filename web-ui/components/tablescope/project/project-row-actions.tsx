"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { IconDotsVertical, IconExternalLink, IconPencil, IconTrash } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";
import { deleteProject, updateProject } from "@/lib/ui/use-shell-data";
import type { ToastTone } from "@/components/ui/toast";

const DELETE_BODY =
  "This will permanently delete the project and remove its project membership, dashboards, queries, scopes, documents, and project-specific data source assignments. This action cannot be undone.";

export function ProjectRowActions({
  project,
  onToast,
}: {
  project: { id: string; name: string };
  onToast: (message: string, tone: ToastTone) => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuPortalRef = useRef<HTMLDivElement>(null);
  const [menuPosition, setMenuPosition] = useState<{ top: number; left: number } | null>(
    null,
  );

  const updateMenuPosition = useCallback(() => {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;
    const menuWidth = 176;
    const estimatedMenuHeight = 120;
    const margin = 8;
    let top = rect.bottom + 6;
    if (top + estimatedMenuHeight > window.innerHeight - margin) {
      top = rect.top - estimatedMenuHeight - 6;
    }
    let left = rect.right - menuWidth;
    left = Math.max(margin, Math.min(left, window.innerWidth - menuWidth - margin));
    setMenuPosition({ top, left });
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        buttonRef.current?.contains(target) ||
        menuPortalRef.current?.contains(target)
      ) {
        return;
      }
      setOpen(false);
    };
    const onReposition = () => updateMenuPosition();
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("scroll", onReposition, true);
    window.addEventListener("resize", onReposition);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("scroll", onReposition, true);
      window.removeEventListener("resize", onReposition);
    };
  }, [open, updateMenuPosition]);

  const refetchProjects = () =>
    queryClient.invalidateQueries({ queryKey: ["projects", "summaries"] });

  const deleteMutation = useMutation({
    mutationFn: () => deleteProject(project.id),
    onSuccess: async () => {
      setConfirmDelete(false);
      onToast("Project deleted.", "success");
      await refetchProjects();
    },
    onError: (err: unknown) => {
      const status = err instanceof ApiError ? err.status : 0;
      if (status === 403) {
        onToast("Only the project owner or an admin can delete this project.", "error");
      } else if (status === 404) {
        onToast("Project not found or already deleted.", "error");
        void refetchProjects();
      } else {
        onToast("Could not delete project. Please try again.", "error");
      }
      setConfirmDelete(false);
    },
  });

  return (
    <>
      <div className="flex justify-end">
        <button
          ref={buttonRef}
          type="button"
          aria-label={`Actions for ${project.name}`}
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setOpen((current) => {
              const next = !current;
              if (!current) {
                requestAnimationFrame(updateMenuPosition);
              }
              return next;
            });
          }}
          className="flex h-7 w-7 items-center justify-center rounded-md text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
        >
          <IconDotsVertical size={16} />
        </button>
        {open &&
          menuPosition &&
          createPortal(
            <div
              ref={menuPortalRef}
              className="fixed z-[100] w-44 overflow-hidden rounded-md border border-line-secondary bg-bg-primary py-1 shadow-lg"
              style={{ top: menuPosition.top, left: menuPosition.left }}
            >
              <MenuItem
                icon={<IconExternalLink size={15} />}
                label="Open"
                onClick={() => {
                  setOpen(false);
                  router.push(`/projects/${project.id}`);
                }}
              />
              <MenuItem
                icon={<IconPencil size={15} />}
                label="Rename"
                onClick={() => {
                  setOpen(false);
                  setRenaming(true);
                }}
              />
              <MenuItem
                icon={<IconTrash size={15} />}
                label="Delete project"
                danger
                onClick={() => {
                  setOpen(false);
                  setConfirmDelete(true);
                }}
              />
            </div>,
            document.body,
          )}
      </div>

      {confirmDelete && (
        <DeleteProjectDialog
          name={project.name}
          pending={deleteMutation.isPending}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => deleteMutation.mutate()}
        />
      )}

      {renaming && (
        <RenameProjectDialog
          project={project}
          onClose={() => setRenaming(false)}
          onToast={onToast}
          onRenamed={refetchProjects}
        />
      )}
    </>
  );
}

function MenuItem({
  icon,
  label,
  onClick,
  danger,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-[13px] hover:bg-bg-secondary ${
        danger ? "text-red-600" : "text-ink-primary"
      }`}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

function DeleteProjectDialog({
  name,
  pending,
  onCancel,
  onConfirm,
}: {
  name: string;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const [typed, setTyped] = useState("");
  const canDelete = typed.trim() === name.trim() && !pending;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-lg bg-bg-primary p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-ink-primary">Delete project?</h3>
        <p className="mt-2 text-[13px] leading-relaxed text-ink-secondary">{DELETE_BODY}</p>
        <label className="mt-4 block text-[12px] font-medium text-ink-secondary">
          Type <span className="font-semibold text-ink-primary">{name}</span> to confirm
        </label>
        <input
          autoFocus
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder={name}
          className="mt-1.5 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
        />
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="danger" disabled={!canDelete} onClick={onConfirm}>
            {pending ? "Deleting…" : "Delete project"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function RenameProjectDialog({
  project,
  onClose,
  onToast,
  onRenamed,
}: {
  project: { id: string; name: string };
  onClose: () => void;
  onToast: (message: string, tone: ToastTone) => void;
  onRenamed: () => void;
}) {
  const [name, setName] = useState(project.name);
  const mutation = useMutation({
    mutationFn: () => updateProject(project.id, { name: name.trim() }),
    onSuccess: async () => {
      onToast("Project renamed.", "success");
      onRenamed();
      onClose();
    },
    onError: (err: unknown) => {
      const status = err instanceof ApiError ? err.status : 0;
      if (status === 403) {
        onToast("Only the project owner or an admin can rename this project.", "error");
      } else {
        onToast("Could not rename project. Please try again.", "error");
      }
    },
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const canSave = name.trim().length > 0 && name.trim() !== project.name && !mutation.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-lg bg-bg-primary p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-ink-primary">Rename project</h3>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && canSave) mutation.mutate();
          }}
          className="mt-3 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
        />
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!canSave} onClick={() => mutation.mutate()}>
            {mutation.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>
    </div>
  );
}
