"use client";

import type { DataSource } from "@/lib/ui/use-project-data";

export function isSaas(s: DataSource): boolean {
  return s.sourceType === "saas_object";
}
