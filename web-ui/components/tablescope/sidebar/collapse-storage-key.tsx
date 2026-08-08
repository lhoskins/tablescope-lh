"use client";


import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import {
  IconChevronDown,
  IconPlus,
  IconUsers,
  IconUserCircle,
  IconLogout,
  IconLayoutSidebarLeftCollapse,
  IconLayoutSidebarLeftExpand,
  IconSettings,
} from "@tabler/icons-react";
import { signOut } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { accentFor } from "@/lib/ui/color";
import type {
  CurrentUser,
  NavKey,
  ProjectSummary,
  TenantSummary,
} from "@/lib/ui/types";

import {
  homeNavGroups,
  projectNavGroups,
  type NavGroup,
  type NavItem,
} from "../nav";


export const COLLAPSE_STORAGE_KEY = "tablescope:sidebar-collapsed";