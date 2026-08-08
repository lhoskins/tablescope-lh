"use client";

import { isDatabase } from "./is-database";
import { isSaas } from "./is-saas";
import type { DataSource } from "@/lib/ui/use-project-data";
import {
  archiveFileSource,
  archiveDatabaseSource,
  archiveSaasSource,
} from "@/lib/api/data-sources";

export function archiveSource(source: DataSource, archived: boolean) {
  if (source.lifecycleKind === "saas") {
    return archiveSaasSource(Number(source.lifecycleId), archived);
  }
  if (source.lifecycleKind === "database") {
    return archiveDatabaseSource(Number(source.lifecycleId), archived);
  }
  return archiveFileSource(source.lifecycleId, archived);
}
