"use client";

import type { InsightCard } from "@/lib/api/home-intelligence";

function triggerDownload(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function sanitizeFilename(text: string): string {
  return text.replace(/[^\w\-]/g, "_").replace(/_+/g, "_").slice(0, 60);
}

export function insightSqlFilename(card: { projectName?: string; title?: string }): string {
  const parts = [card.projectName, card.title].filter(Boolean);
  return `${sanitizeFilename(parts.join(" - "))}.sql`;
}

export function exportInsightCardSql(card: InsightCard): void {
  const sql = card.sql?.trim();
  if (!sql) {
    throw new Error("SQL export is not available for this insight");
  }
  const blob = new Blob([sql], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  triggerDownload(url, insightSqlFilename(card));
  URL.revokeObjectURL(url);
}
