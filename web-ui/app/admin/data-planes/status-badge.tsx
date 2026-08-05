"use client";

const STATUS_STYLES: Record<string, string> = {
  active: "bg-green-100 text-green-700",
  provisioning: "bg-amber-100 text-amber-700",
  container_pending: "bg-amber-100 text-amber-700",
  healthy: "bg-green-100 text-green-700",
  applied: "bg-green-100 text-green-700",
  ok: "bg-green-100 text-green-700",
  up: "bg-green-100 text-green-700",
  down: "bg-red-100 text-red-700",
  not_applicable: "bg-slate-100 text-slate-500",
  not_configured: "bg-slate-100 text-slate-500",
  unknown: "bg-slate-100 text-slate-500",
};

export function StatusBadge({ value }: { value: string | null }) {
  const v = value ?? "unknown";
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
        STATUS_STYLES[v] ?? "bg-slate-100 text-slate-600"
      }`}
    >
      {v}
    </span>
  );
}
