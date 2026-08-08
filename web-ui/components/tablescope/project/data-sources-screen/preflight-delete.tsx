"use client";

import type { DataSource } from "@/lib/ui/use-project-data";
import {
  preflightDeleteFileSource,
  preflightDeleteDatabaseSource,
  preflightDeleteSaasSource,
} from "@/lib/api/data-sources";

export function preflightDelete(source: DataSource) {
  if (source.lifecycleKind === "saas") {
    return preflightDeleteSaasSource(Number(source.lifecycleId));
  }
  if (source.lifecycleKind === "database") {
    return preflightDeleteDatabaseSource(Number(source.lifecycleId));
  }
  return preflightDeleteFileSource(source.lifecycleId);
}
