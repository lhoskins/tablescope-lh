"use client";


import { useMemo, useRef, useState, useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconRefresh,
  IconDatabase,
  IconFileSpreadsheet,
  IconApi,
  IconArchive,
  IconArrowBackUp,
  IconTrash,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { ConnectorsMenu } from "@/components/datasource/ConnectorsMenu";

import {
  ContextPanel,
  ContextSection,
} from "@/components/tablescope/context-panel";
import { StatTile } from "@/components/ui/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { DataSourceUpdateDialog } from "@/components/tablescope/project/data-source-update-dialog";
import {
  activateSourceVersion,
  listSourceVersions,
  preflightSourceUpdate,
  rollbackSourceVersion,
  type PreflightResponse,
  type SourceVersion,
} from "@/lib/api/data-source-versions";
import {
  archiveFileSource,
  archiveDatabaseSource,
  archiveSaasSource,
  preflightDeleteFileSource,
  preflightDeleteDatabaseSource,
  preflightDeleteSaasSource,
  deleteFileSource,
  deleteDatabaseSource,
  deleteSaasSource,
  type PreflightDeleteResponse,
} from "@/lib/api/data-sources";
import {
  useProjectDataSources,
  columnLabel,
  type DataSource,
} from "@/lib/ui/use-project-data";
import { metaList } from "@/lib/ui/ai-meta";
import { DataSourceResultView } from "@/components/tablescope/project/detail-views";import { isDatabase } from "./is-database";
import { isSaas } from "./is-saas";



export function preflightDelete(source: DataSource) {
  if (isSaas(source) && source.id != null) {
    return preflightDeleteSaasSource(source.id);
  }
  if (isDatabase(source) && source.id != null) {
    return preflightDeleteDatabaseSource(source.id);
  }
  return preflightDeleteFileSource(source.viewName);
}