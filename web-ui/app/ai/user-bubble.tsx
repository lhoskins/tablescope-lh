"use client";

import { MessageTimestamp } from "./message-timestamp";

export function UserBubble({
  content,
  timestamp,
}: {
  content: string;
  timestamp?: string | null;
}) {
  return (
    <div className="group flex flex-col items-end">
      <div className="max-w-[75%] rounded-xl bg-brand px-4 py-3 text-[13px] leading-relaxed text-brand-fg">
        <span className="whitespace-pre-wrap break-words">{content}</span>
      </div>
      <MessageTimestamp value={timestamp} label="Sent" align="right" />
    </div>
  );
}
