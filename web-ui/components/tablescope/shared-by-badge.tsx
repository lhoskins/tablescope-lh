import { IconLock, IconUsers, IconUser } from "@tabler/icons-react";

/**
 * Renders the "Shared by" cell value:
 * - "Private"  → lock icon, muted
 * - "Shared"   → users icon (shared by the project owner)
 * - any name   → user icon (shared by that named user)
 */
export function SharedByBadge({ value }: { value: string }) {
  if (value === "Private") {
    return (
      <span className="inline-flex items-center gap-1.5 text-ink-tertiary">
        <IconLock size={13} />
        Private
      </span>
    );
  }
  if (value === "Shared") {
    return (
      <span className="inline-flex items-center gap-1.5 text-brand-700">
        <IconUsers size={13} />
        Shared
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-ink-secondary">
      <IconUser size={13} />
      {value}
    </span>
  );
}
