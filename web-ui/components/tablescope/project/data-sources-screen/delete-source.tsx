"use client";

import type { DataSource } from "@/lib/ui/use-project-data";
import {
  deleteFileSource,
  deleteDatabaseSource,
  deleteSaasSource,
} from "@/lib/api/data-sources";

export function deleteSource(source: DataSource) {
  if (source.lifecycleKind === "saas") {
    return deleteSaasSource(Number(source.lifecycleId));
  }
  if (source.lifecycleKind === "database") {
    return deleteDatabaseSource(Number(source.lifecycleId));
  }
  return deleteFileSource(source.lifecycleId);
}
