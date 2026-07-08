import { IconUser } from "@tabler/icons-react";

/**
 * Renders the "Owner" cell value: a user icon followed by the owner/creator
 * name. Falls back to an em dash when the owner is unknown.
 */
export function OwnerBadge({ name }: { name: string }) {
  const label = name && name !== "—" ? name : "—";
  return (
    <span className="inline-flex items-center gap-1.5 text-ink-secondary">
      <IconUser size={13} />
      {label}
    </span>
  );
}
