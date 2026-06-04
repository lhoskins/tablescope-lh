"use client";

/**
 * Standard Yes / Cancel confirmation dialog used for destructive or
 * overwriting actions (e.g. drag-to-replace a datasource).
 */
export function ConfirmDialog({
  open,
  title = "Are you sure?",
  message,
  confirmLabel = "Yes",
  cancelLabel = "Cancel",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title?: string;
  message: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-sm rounded-lg bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-slate-900">{title}</h3>
        <div className="mt-2 text-sm text-slate-600">{message}</div>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-slate-300 bg-white px-4 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-md bg-brand px-4 py-1.5 text-sm font-medium text-brand-fg hover:bg-brand/90"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
