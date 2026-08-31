"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";
import {
  formatConversationTimestamp,
  type ConversationTimestamp,
} from "./conversation-row";

export function MessageTimestamp({
  value,
  label,
  align = "left",
}: {
  value?: string | null;
  label: "Sent" | "Answered";
  align?: "left" | "right";
}) {
  const [timestamp, setTimestamp] = useState<ConversationTimestamp | null>(null);

  useEffect(() => {
    setTimestamp(value ? formatConversationTimestamp(value) : null);
  }, [value]);

  if (!timestamp || !value) return null;

  return (
    <time
      dateTime={value}
      title={`${label} ${timestamp.full}`}
      aria-label={`${label} ${timestamp.full}`}
      data-testid="message-timestamp"
      className={cn(
        "mt-1 block select-none text-[11px] leading-4 text-ink-tertiary opacity-0 transition-opacity duration-150 group-hover:opacity-100",
        align === "right" ? "text-right" : "text-left",
      )}
    >
      {timestamp.compact}
    </time>
  );
}
