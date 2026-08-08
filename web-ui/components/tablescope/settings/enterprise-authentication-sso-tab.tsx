"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Switch } from "@/components/ui/switch";
import { useToasts } from "@/components/ui/toast";
import {
  getSsoConfiguration,
  testSsoConfiguration,
  updateSsoConfiguration,
  updateSsoPolicy,
  type EnterpriseAuthSettings,
  type SsoConfigurationPayload,
  type SsoConfigurationRead,
} from "@/lib/api/enterprise-auth";
import { Button, GhostButton, Input, Label, Section, TextArea, useSettings } from "./enterprise-authentication-shared";

export function SsoTab() {
  const queryClient = useQueryClient();
  const { push } = useToasts();
  const { data: settings } = useSettings();
  const { data: config } = useQuery<SsoConfigurationRead>({
    queryKey: ["enterprise-auth", "sso", "configuration"],
    queryFn: getSsoConfiguration,
  });
  const [form, setForm] = useState<SsoConfigurationPayload>(() => ({
    provider_friendly_name: "",
    metadata_url: "",
    metadata_xml: "",
    expected_entity_id: "",
    allowed_email_domains: [],
  }));

  const configMutation = useMutation({
    mutationFn: updateSsoConfiguration,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["enterprise-auth"] });
      push("SSO provider configured", "success");
    },
    onError: (err: unknown) => push(err instanceof Error ? err.message : "Configuration failed", "error"),
  });

  const testMutation = useMutation({
    mutationFn: testSsoConfiguration,
    onSuccess: (data) => push(data.message, data.success ? "success" : "error"),
    onError: (err: unknown) => push(err instanceof Error ? err.message : "SSO test failed", "error"),
  });

  const policyMutation = useMutation({
    mutationFn: updateSsoPolicy,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["enterprise-auth"] });
      push("SSO policy updated", "success");
    },
    onError: (err: unknown) => push(err instanceof Error ? err.message : "Policy update failed", "error"),
  });

  function setField<K extends keyof SsoConfigurationPayload>(key: K, value: SsoConfigurationPayload[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function setDomains(value: string) {
    setField(
      "allowed_email_domains",
      value
        .split(",")
        .map((d) => d.trim())
        .filter(Boolean),
    );
  }

  function updatePolicy(key: keyof EnterpriseAuthSettings, value: boolean) {
    policyMutation.mutate({ [key]: value } as Partial<EnterpriseAuthSettings>);
  }

  return (
    <div className="space-y-6">
      <Section title="SSO Provider" description="Configure a SAML 2.0 identity provider through Supabase SSO.">
        <div className="space-y-4">
          <div>
            <Label>Provider friendly name</Label>
            <Input value={form.provider_friendly_name} onChange={(e) => setField("provider_friendly_name", e.target.value)} />
          </div>
          <div>
            <Label>Metadata URL</Label>
            <Input value={form.metadata_url || ""} onChange={(e) => setField("metadata_url", e.target.value)} />
          </div>
          <div>
            <Label>Metadata XML</Label>
            <TextArea rows={6} value={form.metadata_xml || ""} onChange={(e) => setField("metadata_xml", e.target.value)} />
          </div>
          <div>
            <Label>Expected entity ID</Label>
            <Input value={form.expected_entity_id || ""} onChange={(e) => setField("expected_entity_id", e.target.value)} />
          </div>
          <div>
            <Label>Allowed email domains (comma-separated)</Label>
            <Input value={(form.allowed_email_domains || []).join(", ")} onChange={(e) => setDomains(e.target.value)} />
          </div>
          <div className="flex gap-2">
            <Button onClick={() => configMutation.mutate(form)} disabled={configMutation.isPending}>
              {configMutation.isPending ? "Saving…" : "Save provider"}
            </Button>
            <GhostButton onClick={() => testMutation.mutate()} disabled={testMutation.isPending}>
              {testMutation.isPending ? "Testing…" : "Test provider"}
            </GhostButton>
          </div>
          {config?.sso_last_test_result ? (
            <p className="text-sm text-ink-tertiary">Last test: {config.sso_status} — {config.sso_last_test_result}</p>
          ) : null}
        </div>
      </Section>
      <Section title="SSO Policy">
        <div className="space-y-4">
          <Switch
            id="sso-enabled"
            checked={settings?.sso_enabled ?? false}
            pending={policyMutation.isPending}
            label="Enable SSO"
            description="Show the SSO button on the tenant login page and allow SAML sign-ins."
            onLabel="On"
            offLabel="Off"
            onChange={(next) => updatePolicy("sso_enabled", next)}
          />
          <Switch
            id="sso-required"
            checked={settings?.sso_required ?? false}
            pending={policyMutation.isPending}
            label="Require SSO"
            description="When required, local login is blocked unless an administrator bypass is used."
            onLabel="On"
            offLabel="Off"
            onChange={(next) => updatePolicy("sso_required", next)}
          />
        </div>
      </Section>
    </div>
  );
}
