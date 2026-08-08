"use client";

import type { DataSource } from "@/lib/ui/use-project-data";

export function isDatabase(s: DataSource): boolean {
  return s.sourceType === "database_table";
}
