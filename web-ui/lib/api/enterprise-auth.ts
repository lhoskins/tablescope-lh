"use client";

import { apiClient } from "@/lib/api-client";

export interface EnterpriseAuthOverview {
  tenant_id: number;
  local_login_allowed: boolean;
  enforce_2fa: boolean;
  ldap_status: string;
  sso_status: string;
  sso_provider_display_name: string | null;
  last_successful_directory_sync: string | null;
  last_successful_sso_test: string | null;
}

export interface EnterpriseAuthSettings {
  tenant_id: number;
  ldap_enabled: boolean;
  sso_enabled: boolean;
  sso_required: boolean;
  local_login_allowed: boolean;
  sso_provider_display_name: string | null;
  sso_status: string | null;
  sso_last_tested_at: string | null;
  sso_last_test_result: string | null;
  ldap_connection_id: number | null;
}

export interface LdapConnection {
  id: number;
  tenant_id: number;
  name: string;
  protocol: string;
  host: string;
  port: number;
  base_dn: string;
  user_search_base: string | null;
  user_filter: string | null;
  group_search_base: string | null;
  group_filter: string | null;
  bind_dn: string | null;
  has_bind_secret: boolean;
  has_ca_certificate: boolean;
  use_starttls: boolean;
  require_cert_validation: boolean;
  connect_timeout: number;
  page_size: number;
  nested_group_resolution: boolean;
  max_nested_depth: number;
  sync_interval_minutes: number;
  disabled_user_handling: string;
  removed_group_handling: string;
  tenant_data_plane_id: number | null;
  enabled: boolean;
  archived: boolean;
  last_test_status: string | null;
  last_test_message_safe: string | null;
  last_tested_at: string | null;
}

export interface LdapConnectionPayload {
  name: string;
  protocol?: string;
  host: string;
  port: number;
  base_dn: string;
  user_search_base?: string;
  user_filter?: string;
  group_search_base?: string;
  group_filter?: string;
  bind_dn?: string;
  bind_secret?: string;
  ca_certificate?: string;
  use_starttls?: boolean;
  require_cert_validation?: boolean;
  connect_timeout?: number;
  page_size?: number;
  nested_group_resolution?: boolean;
  max_nested_depth?: number;
  sync_interval_minutes?: number;
  disabled_user_handling?: string;
  removed_group_handling?: string;
  tenant_data_plane_id?: number | null;
  enabled?: boolean;
}

export interface LdapTestResult {
  success: boolean;
  status: string;
  message: string;
}

export interface DirectoryPreview {
  users: Array<Record<string, unknown>>;
  groups: Array<Record<string, unknown>>;
  membership_count: number;
}

export interface DirectoryGroupRoleMapping {
  id: number;
  tenant_id: number;
  connection_id: number;
  directory_group_guid: string;
  group_display_name: string | null;
  target_type: string;
  target_project_id: number | null;
  mapped_role: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface DirectoryGroupRoleMappingPayload {
  directory_group_guid: string;
  group_display_name?: string;
  target_type: "tenant" | "project" | "capability";
  target_project_id?: number | null;
  mapped_role: string;
  enabled?: boolean;
}

export interface SsoConfigurationPayload {
  provider_friendly_name: string;
  identity_provider_type?: string;
  metadata_url?: string;
  metadata_xml?: string;
  expected_entity_id?: string;
  allowed_email_domains?: string[];
}

export interface SsoConfigurationRead {
  provider_friendly_name: string | null;
  identity_provider_type: string | null;
  expected_entity_id: string | null;
  allowed_email_domains: string[];
  sso_status: string | null;
  sso_last_tested_at: string | null;
  sso_last_test_result: string | null;
}

export interface SsoTestResult {
  success: boolean;
  status: string;
  message: string;
}

export interface SsoPolicy {
  sso_enabled: boolean;
  sso_required: boolean;
  local_login_allowed: boolean;
}

export interface IdentityMapping {
  id: number;
  user_id: number;
  provider_type: string;
  external_subject: string;
  verification_state: string;
  sso_provider_uuid: boolean;
  suspended: boolean;
  linked_at: string | null;
  last_authenticated_at: string | null;
  last_synchronized_at: string | null;
}

export function getEnterpriseAuthOverview() {
  return apiClient.get<EnterpriseAuthOverview>("/api/tenants/current/enterprise-auth");
}

export function getEnterpriseAuthSettings() {
  return apiClient.get<EnterpriseAuthSettings>("/api/tenants/current/enterprise-auth/settings");
}

export function updateEnterpriseAuthSettings(payload: Partial<EnterpriseAuthSettings>) {
  return apiClient.put<EnterpriseAuthSettings>("/api/tenants/current/enterprise-auth/settings", payload);
}

export function getLdapConnection() {
  return apiClient.get<LdapConnection | null>("/api/tenants/current/enterprise-auth/ldap/connection");
}

export function saveLdapConnection(payload: LdapConnectionPayload) {
  return apiClient.put<LdapConnection>("/api/tenants/current/enterprise-auth/ldap/connection", payload);
}

export function testLdapConnection(payload: LdapConnectionPayload) {
  return apiClient.post<LdapTestResult>("/api/tenants/current/enterprise-auth/ldap/connection/test", payload);
}

export function previewLdapDirectory(payload: LdapConnectionPayload) {
  return apiClient.post<DirectoryPreview>("/api/tenants/current/enterprise-auth/ldap/connection/preview", payload);
}

export function testSavedLdapConnection(connectionId: number) {
  return apiClient.post<LdapTestResult>(`/api/tenants/current/enterprise-auth/ldap/connection/${connectionId}/test`, {});
}

export function triggerLdapSync() {
  return apiClient.post<{ sync_run_id: number | null; status: string; message: string }>(
    "/api/tenants/current/enterprise-auth/ldap/sync",
    {},
  );
}

export function getGroupMappings() {
  return apiClient.get<DirectoryGroupRoleMapping[]>("/api/tenants/current/enterprise-auth/ldap/group-mappings");
}

export function createGroupMapping(payload: DirectoryGroupRoleMappingPayload) {
  return apiClient.post<DirectoryGroupRoleMapping>("/api/tenants/current/enterprise-auth/ldap/group-mappings", payload);
}

export function updateGroupMapping(id: number, payload: Partial<DirectoryGroupRoleMappingPayload>) {
  return apiClient.put<DirectoryGroupRoleMapping>(`/api/tenants/current/enterprise-auth/ldap/group-mappings/${id}`, payload);
}

export function deleteGroupMapping(id: number) {
  return apiClient.delete(`/api/tenants/current/enterprise-auth/ldap/group-mappings/${id}`);
}

export function getSsoConfiguration() {
  return apiClient.get<SsoConfigurationRead>("/api/tenants/current/enterprise-auth/sso/configuration");
}

export function updateSsoConfiguration(payload: SsoConfigurationPayload) {
  return apiClient.put<EnterpriseAuthSettings>("/api/tenants/current/enterprise-auth/sso/configuration", payload);
}

export function testSsoConfiguration() {
  return apiClient.post<SsoTestResult>("/api/tenants/current/enterprise-auth/sso/test", {});
}

export function updateSsoPolicy(payload: Partial<SsoPolicy>) {
  return apiClient.put<EnterpriseAuthSettings>("/api/tenants/current/enterprise-auth/sso/policy", payload);
}

export function getIdentityMappings() {
  return apiClient.get<IdentityMapping[]>("/api/tenants/current/enterprise-auth/sso/identity-mappings");
}

export function confirmIdentityMapping(id: number, userId: number) {
  return apiClient.post(`/api/tenants/current/enterprise-auth/sso/identity-mappings/${id}/confirm`, { user_id: userId });
}

export function rejectIdentityMapping(id: number) {
  return apiClient.post(`/api/tenants/current/enterprise-auth/sso/identity-mappings/${id}/reject`, {});
}
