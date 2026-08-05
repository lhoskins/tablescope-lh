"use client";


import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createRepositoryConnection,
  deleteRepositoryConnection,
  getRepositoryProfile,
  listRepositoryConnections,
  listRepositoryItems,
  listRepositoryScans,
  listRepositoryConnectorTypes,
  startRepositoryScan,
  testExistingRepositoryConnection,
  testRepositoryConnectionConfig,
  updateRepositoryConnection,
  type RepositoryConnection,
  type RepositoryConnectionCreate,
  type RepositoryConnectionUpdate,
  type RepositoryItem,
  type RepositoryScan,
} from "@/lib/api/repository-connectors";import { classNames } from "./utils";



export function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    active: "bg-emerald-50 text-emerald-700",
    disabled: "bg-slate-100 text-slate-500",
    error: "bg-red-50 text-red-700",
    queued: "bg-sky-50 text-sky-700",
    running: "bg-amber-50 text-amber-700",
    succeeded: "bg-emerald-50 text-emerald-700",
    partial: "bg-amber-50 text-amber-700",
    failed: "bg-red-50 text-red-700",
    pending: "bg-slate-100 text-slate-500",
    completed: "bg-emerald-50 text-emerald-700",
    governance_blocked: "bg-amber-50 text-amber-700",
    skipped: "bg-slate-100 text-slate-500",
  };
  const cls = styles[status] ?? "bg-slate-100 text-slate-600";
  return (
    <span className={classNames("rounded-full px-2 py-0.5 text-xs font-medium", cls)}>
      {status.replace(/_/g, " ")}
    </span>
  );
}