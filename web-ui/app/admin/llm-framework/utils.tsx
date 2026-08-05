"use client";


import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  activateLLMDeployment,
  approveLLMDeployment,
  getLLMAuditEvents,
  getLLMCapabilities,
  getLLMDeployments,
  getLLMFrameworkStatus,
  getLLMInventory,
  getLLMEmbeddingMigrations,
  getLLMModelConversions,
  installLLMArtifact,
  preflightLLMInstall,
  registerLLMRuntimeTarget,
  rollbackLLMDeployment,
  searchLLMCatalog,
  stageLLMArtifact,
  reindexLLMArtifact,
  convertLLMCatalogEntry,
  upsertLLMRoutingProfile,
  type AuditEvent,
  type CatalogSearchResult,
  type Deployment,
  type LLMInventory,
  type RuntimeTarget,
} from "@/lib/api/llm-framework";


export function formatBytes(value: number | null | undefined): string {
  if (value == null) return "-";
  if (value === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** i).toFixed(i === 0 ? 0 : 2)} ${units[i]}`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

export function formatCapability(value: string): string {
  return value
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line-tertiary bg-bg-primary p-4 shadow-sm">
      <h2 className="mb-3 text-lg font-semibold text-ink-primary">{title}</h2>
      {children}
    </section>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "active" || status === "verified"
      ? "bg-emerald-50 text-emerald-700"
      : status === "quarantined" || status === "failed"
        ? "bg-red-50 text-red-700"
        : status === "staged" || status === "pending" || status === "downloading" || status === "verifying"
          ? "bg-amber-50 text-amber-700"
          : "bg-slate-100 text-slate-600";
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}