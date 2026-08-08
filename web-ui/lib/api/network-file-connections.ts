"use client";

import { apiClient } from "@/lib/api-client";

export interface NetworkHost {
  id: number;
  name: string;
  host: string;
  enabled: boolean;
  archived?: boolean;
}

export interface NetworkFileConnection {
  id: number;
  name: string;
  label: string;
  host: string;
  port: number;
  share_name: string;
  approved_root_path: string;
  domain: string | null;
  username: string | null;
  has_secret: boolean;
  require_signing: boolean;
  require_encryption: boolean;
  enabled: boolean;
  last_test_status: string | null;
  last_test_message: string | null;
  last_tested_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface NetworkFileConnectionCreate {
  name: string;
  host: string;
  share_name: string;
  approved_root_path?: string;
  port?: number;
  domain?: string;
  username?: string;
  password?: string;
  require_signing?: boolean;
  require_encryption?: boolean;
  enabled?: boolean;
}

export interface NetworkFileEntry {
  name: string;
  path: string;
  kind: "directory" | "file";
  size_bytes: number;
  modified_at: number | null;
}

export function listNetworkFileConnections(): Promise<NetworkFileConnection[]> {
  return apiClient.get<NetworkFileConnection[]>("/api/network-file-connections");
}

export function createNetworkFileConnection(
  body: NetworkFileConnectionCreate,
): Promise<NetworkFileConnection> {
  return apiClient.post<NetworkFileConnection>("/api/network-file-connections", body);
}

export function updateNetworkFileConnection(
  id: number,
  body: NetworkFileConnectionCreate,
): Promise<NetworkFileConnection> {
  return apiClient.patch<NetworkFileConnection>(`/api/network-file-connections/${id}`, body);
}

export function deleteNetworkFileConnection(
  id: number,
): Promise<{ status: string }> {
  return apiClient.delete(`/api/network-file-connections/${id}`);
}

export function testNetworkFileConnection(
  id: number,
): Promise<{ ok: boolean; message?: string }> {
  return apiClient.post<{ ok: boolean; message?: string }>(
    `/api/network-file-connections/${id}/test`,
    {},
  );
}

export function browseNetworkFileConnection(
  connectionId: number,
  path?: string,
): Promise<{ entries: NetworkFileEntry[]; path: string }> {
  const params = new URLSearchParams();
  if (path) params.set("path", path);
  return apiClient.get<{ entries: NetworkFileEntry[]; path: string }>(
    `/api/network-file-connections/${connectionId}/browse?${params.toString()}`,
  );
}

export function listNetworkHosts(): Promise<NetworkHost[]> {
  return apiClient.get<NetworkHost[]>("/api/network-file-hosts");
}

export function createNetworkHost(
  host: { name: string; host: string; enabled?: boolean },
): Promise<NetworkHost> {
  return apiClient.post<NetworkHost>("/api/network-file-hosts", host);
}

export function updateNetworkHost(
  id: number,
  host: { name: string; host: string; enabled?: boolean },
): Promise<NetworkHost> {
  return apiClient.patch<NetworkHost>(`/api/network-file-hosts/${id}`, host);
}

export function deleteNetworkHost(id: number): Promise<{ status: string }> {
  return apiClient.delete(`/api/network-file-hosts/${id}`);
}
