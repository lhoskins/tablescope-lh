"use client";

import type { DataSource } from "@/lib/ui/use-project-data";
import { isDatabase } from "./is-database";
import { isSaas } from "./is-saas";

export function sourceTypeLabel(s: DataSource): string {
  if (isDatabase(s)) return s.dbType ? `${s.dbType} table` : "Database table";
  if (isSaas(s)) return s.connectorType ? `${s.connectorType} object` : "SaaS object";
  return s.sourceType || "File";
}
