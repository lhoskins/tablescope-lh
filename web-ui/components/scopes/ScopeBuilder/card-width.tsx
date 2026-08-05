"use client";


import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useNotifyScopesChanged } from "@/lib/ui/scope-refresh";
import {
  IconArrowNarrowRight,
  IconArrowsExchange,
  IconChevronDown,
  IconDeviceFloppy,
  IconGripVertical,
  IconMaximize,
  IconPencil,
  IconPlus,
  IconSearch,
  IconSparkles,
  IconTrash,
  IconX,
  IconZoomIn,
  IconZoomOut,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import {
  scopesApi,
  type MatchMode,
  type ScopeAISuggestion,
  type ScopeBuilderTable,
  type ScopeDirection,
  type ScopeMap,
} from "@/lib/api/scopes";


// Canvas layout geometry (deterministic so we can draw lines without DOM reads).
export const CARD_WIDTH = 320;