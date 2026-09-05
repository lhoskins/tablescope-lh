import { StatusBadge } from "./status-badge";
import type { DataPlane, HealthReport } from "./types";

export function StorageCell({ plane }: { plane: DataPlane }) {
  return (
    <td className="px-4 py-3 text-xs">
      <StatusBadge value={plane.storage_status} />
      <div
        className="mt-1 max-w-40 truncate font-mono text-[10px] text-slate-400"
        title={plane.s3_bucket_name ?? undefined}
      >
        {plane.s3_bucket_name ??
          `${plane.s3_region ?? "region pending"} · metadata pending`}
      </div>
    </td>
  );
}

export function HealthCell({
  plane,
  health,
}: {
  plane: DataPlane;
  health?: HealthReport;
}) {
  return (
    <td className="px-4 py-3 text-xs">
      {health ? (
        <div className="space-y-1">
          <div>teiid <StatusBadge value={health.teiid_status} /></div>
          <div>fw <StatusBadge value={health.firewall_status} /></div>
          <div>vdb <StatusBadge value={health.vdb_path_status} /></div>
          <div>s3 <StatusBadge value={health.storage_status} /></div>
        </div>
      ) : (
        <span className="text-slate-400">{plane.last_health_status ?? "—"}</span>
      )}
    </td>
  );
}
