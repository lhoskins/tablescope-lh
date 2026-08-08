"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useToasts } from "@/components/ui/toast";
import {
  createGroupMapping,
  deleteGroupMapping,
  getGroupMappings,
  getLdapConnection,
  previewLdapDirectory,
  saveLdapConnection,
  testLdapConnection,
  triggerLdapSync,
  type DirectoryGroupRoleMapping,
  type DirectoryGroupRoleMappingPayload,
  type LdapConnection,
  type LdapConnectionPayload,
} from "@/lib/api/enterprise-auth";
import { Button, GhostButton, Input, Label, Section, TextArea } from "./enterprise-authentication-shared";

function GroupMappingsTab() {
  const queryClient = useQueryClient();
  const { push } = useToasts();
  const { data: mappings } = useQuery<DirectoryGroupRoleMapping[]>({
    queryKey: ["enterprise-auth", "ldap", "group-mappings"],
    queryFn: getGroupMappings,
  });
  const [newMapping, setNewMapping] = useState<DirectoryGroupRoleMappingPayload>({
    directory_group_guid: "",
    target_type: "tenant",
    mapped_role: "member",
    enabled: true,
  });

  const createMutation = useMutation({
    mutationFn: createGroupMapping,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["enterprise-auth", "ldap", "group-mappings"] });
      push("Group mapping created", "success");
    },
    onError: (err: unknown) => push(err instanceof Error ? err.message : "Create failed", "error"),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteGroupMapping,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["enterprise-auth", "ldap", "group-mappings"] });
      push("Group mapping deleted", "success");
    },
    onError: (err: unknown) => push(err instanceof Error ? err.message : "Delete failed", "error"),
  });

  return (
    <Section title="Directory Group Role Mappings" description="Map external directory groups to tenant or project roles.">
      <div className="mb-4 flex gap-2">
        <Input
          placeholder="Directory group GUID"
          value={newMapping.directory_group_guid}
          onChange={(e) => setNewMapping((m) => ({ ...m, directory_group_guid: e.target.value }))}
        />
        <select
          value={newMapping.target_type}
          onChange={(e) => setNewMapping((m) => ({ ...m, target_type: e.target.value as DirectoryGroupRoleMappingPayload["target_type"] }))}
          className="rounded-md border border-line-secondary bg-bg-primary px-2 text-sm"
        >
          <option value="tenant">Tenant</option>
          <option value="project">Project</option>
          <option value="capability">Capability</option>
        </select>
        <Input
          placeholder="Mapped role"
          value={newMapping.mapped_role}
          onChange={(e) => setNewMapping((m) => ({ ...m, mapped_role: e.target.value }))}
        />
        <Button onClick={() => createMutation.mutate(newMapping)} disabled={createMutation.isPending}>
          Add
        </Button>
      </div>
      {mappings?.length ? (
        <ul className="divide-y divide-line-secondary">
          {mappings.map((m) => (
            <li key={m.id} className="flex items-center justify-between py-3 text-sm">
              <div>
                <span className="font-medium text-ink-primary">{m.directory_group_guid}</span>
                <span className="ml-2 text-ink-tertiary">→ {m.target_type}</span>
                <span className="ml-2 rounded bg-bg-secondary px-2 py-0.5 text-ink-primary">{m.mapped_role}</span>
              </div>
              <GhostButton className="py-1 text-xs" onClick={() => deleteMutation.mutate(m.id)}>
                Delete
              </GhostButton>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-ink-tertiary">No group mappings configured.</p>
      )}
    </Section>
  );
}

export function LdapDirectoryTab() {
  const queryClient = useQueryClient();
  const { push } = useToasts();
  const { data: conn } = useQuery<LdapConnection | null>({
    queryKey: ["enterprise-auth", "ldap", "connection"],
    queryFn: getLdapConnection,
  });
  const [form, setForm] = useState<LdapConnectionPayload>(() => ({
    name: "",
    host: "",
    port: 636,
    base_dn: "",
    protocol: "ldaps",
    bind_secret: "",
  }));

  const testMutation = useMutation({
    mutationFn: testLdapConnection,
    onSuccess: (data) => push(data.message, data.success ? "success" : "error"),
    onError: (err: unknown) => push(err instanceof Error ? err.message : "Test failed", "error"),
  });

  const saveMutation = useMutation({
    mutationFn: saveLdapConnection,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["enterprise-auth", "ldap"] });
      queryClient.invalidateQueries({ queryKey: ["enterprise-auth", "overview"] });
      push("LDAP connection saved", "success");
    },
    onError: (err: unknown) => push(err instanceof Error ? err.message : "Save failed", "error"),
  });

  const previewMutation = useMutation({
    mutationFn: previewLdapDirectory,
    onSuccess: (data) => push(`Preview: ${data.users.length} users, ${data.groups.length} groups`, "success"),
    onError: (err: unknown) => push(err instanceof Error ? err.message : "Preview failed", "error"),
  });

  const syncMutation = useMutation({
    mutationFn: triggerLdapSync,
    onSuccess: (data) => push(data.message, "success"),
    onError: (err: unknown) => push(err instanceof Error ? err.message : "Sync failed", "error"),
  });

  function setField<K extends keyof LdapConnectionPayload>(key: K, value: LdapConnectionPayload[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  return (
    <div className="space-y-6">
      <Section title="LDAP Connection" description="Directory connection details are encrypted at rest.">
        <div className="grid grid-cols-2 gap-4">
          <div className="col-span-2">
            <Label>Connection name</Label>
            <Input value={form.name} onChange={(e) => setField("name", e.target.value)} />
          </div>
          <div>
            <Label>Protocol</Label>
            <select
              value={form.protocol}
              onChange={(e) => setField("protocol", e.target.value)}
              className="w-full rounded-md border border-line-secondary bg-bg-primary px-3 py-2 text-sm text-ink-primary"
            >
              <option value="ldaps">LDAPS</option>
              <option value="ldap">LDAP</option>
            </select>
          </div>
          <div>
            <Label>Port</Label>
            <Input type="number" value={form.port} onChange={(e) => setField("port", parseInt(e.target.value, 10) || 0)} />
          </div>
          <div className="col-span-2">
            <Label>Host</Label>
            <Input value={form.host} onChange={(e) => setField("host", e.target.value)} />
          </div>
          <div className="col-span-2">
            <Label>Base DN</Label>
            <Input value={form.base_dn} onChange={(e) => setField("base_dn", e.target.value)} />
          </div>
          <div className="col-span-2">
            <Label>Bind DN</Label>
            <Input value={form.bind_dn || ""} onChange={(e) => setField("bind_dn", e.target.value)} />
          </div>
          <div className="col-span-2">
            <Label>Bind password</Label>
            <Input type="password" value={form.bind_secret || ""} onChange={(e) => setField("bind_secret", e.target.value)} />
          </div>
          <div>
            <Label>User search base (optional)</Label>
            <Input value={form.user_search_base || ""} onChange={(e) => setField("user_search_base", e.target.value)} />
          </div>
          <div>
            <Label>Group search base (optional)</Label>
            <Input value={form.group_search_base || ""} onChange={(e) => setField("group_search_base", e.target.value)} />
          </div>
          <div className="col-span-2">
            <Label>CA certificate (PEM)</Label>
            <TextArea rows={4} value={form.ca_certificate || ""} onChange={(e) => setField("ca_certificate", e.target.value)} />
          </div>
          <div className="flex items-center gap-2">
            <input id="starttls" type="checkbox" checked={!!form.use_starttls} onChange={(e) => setField("use_starttls", e.target.checked)} />
            <Label>Use StartTLS</Label>
          </div>
          <div className="flex items-center gap-2">
            <input id="cert-validation" type="checkbox" checked={form.require_cert_validation !== false} onChange={(e) => setField("require_cert_validation", e.target.checked)} />
            <Label>Require certificate validation</Label>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button onClick={() => saveMutation.mutate(form)} disabled={saveMutation.isPending}>
            {saveMutation.isPending ? "Saving…" : "Save connection"}
          </Button>
          <GhostButton onClick={() => testMutation.mutate(form)} disabled={testMutation.isPending}>
            {testMutation.isPending ? "Testing…" : "Test connection"}
          </GhostButton>
          <GhostButton onClick={() => previewMutation.mutate(form)} disabled={previewMutation.isPending}>
            {previewMutation.isPending ? "Previewing…" : "Preview directory"}
          </GhostButton>
          <GhostButton onClick={() => syncMutation.mutate()} disabled={syncMutation.isPending || !conn}>
            {syncMutation.isPending ? "Syncing…" : "Run sync"}
          </GhostButton>
        </div>
        {conn?.last_test_status ? (
          <p className="mt-2 text-sm text-ink-tertiary">Last test: {conn.last_test_status} — {conn.last_test_message_safe}</p>
        ) : null}
      </Section>
      <GroupMappingsTab />
    </div>
  );
}
