import { apiClient } from "@/lib/api-client";

export interface HomePin {
  id: number;
  pin_type: "insight_card" | "live_widget";
  pin_key: string;
  title: string;
  project_id: number | null;
  config: Record<string, unknown>;
  layout: HomePinLayout;
  frozen_payload: Record<string, unknown> | null;
  last_refreshed_at: string | null;
  refresh_error: string | null;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
}

export interface HomePinLayout {
  x?: number;
  y?: number;
  w?: number;
  h?: number;
  position?: number;
}

export interface CreateHomePinPayload {
  pin_type: "insight_card" | "live_widget";
  pin_key: string;
  title: string;
  project_id?: number | null;
  config?: Record<string, unknown>;
  layout?: HomePinLayout;
  frozen_payload?: Record<string, unknown> | null;
}

export interface HomePinLayoutItem {
  id: number;
  grid_x: number;
  grid_y: number;
  grid_w: number;
  grid_h: number;
  position: number;
}

export function getHomePins(): Promise<HomePin[]> {
  return apiClient.get<HomePin[]>("/api/home-pins");
}

export function createHomePin(payload: CreateHomePinPayload): Promise<HomePin> {
  return apiClient.post<HomePin>("/api/home-pins", payload);
}

export function deleteHomePin(pinId: number): Promise<void> {
  return apiClient.delete<void>(`/api/home-pins/${pinId}`);
}

export function updateHomePinLayout(
  layout: HomePinLayoutItem[],
): Promise<HomePin[]> {
  return apiClient.patch<HomePin[]>("/api/home-pins/layout", { layout });
}

export function refreshHomePin(pinId: number): Promise<HomePin> {
  return apiClient.post<HomePin>(`/api/home-pins/${pinId}/refresh`, {});
}

export function refreshAllHomePins(): Promise<{
  refreshed: number;
  errors: number;
  total: number;
}> {
  return apiClient.post<{ refreshed: number; errors: number; total: number }>(
    "/api/home-pins/refresh",
    {},
  );
}
