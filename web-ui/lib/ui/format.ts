import type { AiStatus } from "./types";

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.floor((Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  const weeks = Math.floor(days / 7);
  if (weeks < 5) return `${weeks}w ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

const AI_STATUS_SET: ReadonlySet<string> = new Set([
  "ready",
  "active",
  "indexing",
  "idle",
]);

export function toAiStatus(value: string | null | undefined): AiStatus {
  return value && AI_STATUS_SET.has(value) ? (value as AiStatus) : "idle";
}

const AI_STATUS_LABEL: Record<AiStatus, string> = {
  ready: "AI Ready",
  active: "Active",
  indexing: "Indexing",
  idle: "Idle",
};

export function aiStatusLabel(status: AiStatus): string {
  return AI_STATUS_LABEL[status];
}

export function aiStatusTone(
  status: AiStatus,
): "brand" | "success" | "warning" | "neutral" {
  switch (status) {
    case "ready":
      return "brand";
    case "active":
      return "success";
    case "indexing":
      return "warning";
    default:
      return "neutral";
  }
}

export function greeting(name: string): string {
  const hour = new Date().getHours();
  const part =
    hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const first = name.trim().split(/\s+/)[0] || "there";
  return `${part}, ${first}`;
}
