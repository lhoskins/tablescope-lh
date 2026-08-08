import { ReactNode } from "react";
import {
  IconAlertCircle,
  IconAlertTriangle,
  IconArrowUpRight,
  IconBulb,
  IconSparkles,
} from "@tabler/icons-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { SUMMARY_TONES } from "@/lib/ui/insight-tones";
import type { ExecutiveSummary } from "@/lib/api/project-insight";

interface ExecutiveProjectSummaryProps {
  summary?: ExecutiveSummary | null;
}

function SummaryCard({
  title,
  tone,
  icon,
  items,
}: {
  title: string;
  tone: keyof typeof SUMMARY_TONES;
  icon: ReactNode;
  items: string[];
}) {
  const t = SUMMARY_TONES[tone];
  return (
    <div className={cn("rounded-lg border p-3.5", t.box)}>
      <div
        className={cn(
          "mb-1.5 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide",
          t.label,
        )}
      >
        {icon}
        {title}
      </div>
      {items.length === 0 ? (
        <p className="text-small text-ink-tertiary">None</p>
      ) : (
        <ul className="space-y-1">
          {items.map((it, i) => (
            <li
              key={i}
              className="text-[13px] leading-snug text-ink-secondary"
            >
              {it}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ExecutiveProjectSummary({
  summary,
}: ExecutiveProjectSummaryProps) {
  if (!summary) {
    return (
      <section className="rounded-lg border border-line-tertiary bg-bg-primary p-5">
        <p className="text-ink-secondary">No summary available for this project yet.</p>
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-line-tertiary bg-bg-primary p-5">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <IconSparkles size={18} className="text-brand-500" />
          <h2 className="text-h2 text-ink-primary">Executive Project Summary</h2>
        </div>
        <Badge tone="ai" size="md">
          AI Generated
        </Badge>
      </div>
      <p className="max-w-4xl text-[13px] leading-relaxed text-ink-secondary">
        {summary.summary || "No summary available for this project yet."}
      </p>
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          title="Critical"
          tone="danger"
          icon={<IconAlertCircle size={15} />}
          items={summary.critical}
        />
        <SummaryCard
          title="Warnings"
          tone="warning"
          icon={<IconAlertTriangle size={15} />}
          items={summary.warnings}
        />
        <SummaryCard
          title="Opportunities"
          tone="success"
          icon={<IconArrowUpRight size={15} />}
          items={summary.opportunities}
        />
        <SummaryCard
          title="Recommendations"
          tone="brand"
          icon={<IconBulb size={15} />}
          items={summary.recommendations}
        />
      </div>
    </section>
  );
}
