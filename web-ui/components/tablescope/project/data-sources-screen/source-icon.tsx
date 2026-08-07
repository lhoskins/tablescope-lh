"use client";

import { IconDatabase, IconFileSpreadsheet, IconApi } from "@tabler/icons-react";
import type { DataSource } from "@/lib/ui/use-project-data";
import { isDatabase } from "./is-database";
import { isSaas } from "./is-saas";

export function SourceIcon({ source }: { source: DataSource }) {
  const Icon = isDatabase(source)
    ? IconDatabase
    : isSaas(source)
      ? IconApi
      : IconFileSpreadsheet;
  return (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-bg-secondary text-ink-secondary">
      <Icon size={18} />
    </span>
  );
}
