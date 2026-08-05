"use client";


import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  IconSparkles,
  IconSearch,
  IconTarget,
  IconPlus,
  IconArchive,
  IconArrowBackUp,
  IconTrash,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import {
  ContextPanel,
  ContextSection,
} from "@/components/tablescope/context-panel";
import { AddDatasourceModal } from "@/components/datasource/AddDatasourceModal";
import { StatTile } from "@/components/ui/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { apiClient } from "@/lib/api-client";
import { timeAgo } from "@/lib/ui/format";
import {
  useProjectQueries,
  useProjectArchivedQueries,
  useProjectDataSources,
  type SavedQuery,
} from "@/lib/ui/use-project-data";
import {
  QueryResultView,
  QueryBuilderEdit,
  QueryBuilderCreate,
} from "@/components/tablescope/project/detail-views";import { Filter } from "./filter";



export const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "ai", label: "AI-generated" },
  { key: "manual", label: "Manual" },
  { key: "shared", label: "Shared" },
  { key: "private", label: "Private" },
  { key: "archive", label: "Archive" },
];