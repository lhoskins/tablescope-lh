import { apiClient } from "@/lib/api-client";

export interface HomeActionItem {
  id: number;
  project_id: number;
  project_name: string;
  title: string;
  status: string;
  priority: string;
  percent_complete: number;
  due_date: string | null;
  completed_at: string | null;
  updated_at: string | null;
}

export interface HomeActionSummary {
  highlights: {
    needs_attention: number;
    due_this_week: number;
    recently_completed: number;
  };
  assigned: HomeActionItem[];
  updates: HomeActionItem[];
  /** True when `updates` was filtered down to items matching the user's
   *  "My Focus" topics; false when no focus is set or nothing matched, in
   *  which case `updates` falls back to plain recency. */
  updates_matched_focus: boolean;
}

export function getHomeActionSummary(): Promise<HomeActionSummary> {
  return apiClient.get<HomeActionSummary>("/api/projects/actions-home");
}
