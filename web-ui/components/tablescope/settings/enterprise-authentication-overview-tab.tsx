"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Switch } from "@/components/ui/switch";
import { useToasts } from "@/components/ui/toast";
import { updateEnterpriseAuthSettings, type EnterpriseAuthOverview, type EnterpriseAuthSettings } from "@/lib/api/enterprise-auth";
import { Section, useOverview, useSettings } from "./enterprise-authentication-shared";

export function OverviewTab({ overview }: { overview: EnterpriseAuthOverview | undefined }) {
  if (!overview) return <div className="text-sm text-ink-tertiary">Loading…</div>;
  return (
    <div className="space-y-4">
      <Section title="Enterprise Authentication" description="Current tenant-wide authentication state.">
        <dl className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <dt className="text-ink-tertiary">Two-factor enforcement</dt>
            <dd className="font-medium text-ink-primary">{overview.enforce_2fa ? "On" : "Off"}</dd>
          </div>
          <div>
            <dt className="text-ink-tertiary">Local login</dt>
            <dd className="font-medium text-ink-primary">{overview.local_login_allowed ? "Allowed" : "Disabled"}</dd>
          </div>
          <div>
            <dt className="text-ink-tertiary">LDAP status</dt>
            <dd className="font-medium text-ink-primary">{overview.ldap_status}</dd>
          </div>
          <div>
            <dt className="text-ink-tertiary">SSO status</dt>
            <dd className="font-medium text-ink-primary">{overview.sso_status}</dd>
          </div>
          {overview.sso_provider_display_name ? (
            <div className="col-span-2">
              <dt className="text-ink-tertiary">SSO provider</dt>
              <dd className="font-medium text-ink-primary">{overview.sso_provider_display_name}</dd>
            </div>
          ) : null}
          {overview.last_successful_directory_sync ? (
            <div className="col-span-2">
              <dt className="text-ink-tertiary">Last directory sync</dt>
              <dd className="font-medium text-ink-primary">{new Date(overview.last_successful_directory_sync).toLocaleString()}</dd>
            </div>
          ) : null}
        </dl>
      </Section>
    </div>
  );
}

export function SettingsToggles({ settings }: { settings: EnterpriseAuthSettings | undefined }) {
  const queryClient = useQueryClient();
  const { push } = useToasts();
  const mutation = useMutation({
    mutationFn: updateEnterpriseAuthSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["enterprise-auth"] });
      push("Settings updated", "success");
    },
    onError: (err: unknown) => push(err instanceof Error ? err.message : "Update failed", "error"),
  });

  if (!settings) return null;

  function update(key: keyof EnterpriseAuthSettings, value: boolean) {
    mutation.mutate({ [key]: value } as Partial<EnterpriseAuthSettings>);
  }

  return (
    <Section title="Global Settings">
      <div className="space-y-4">
        <Switch
          id="local-login"
          checked={settings.local_login_allowed}
          pending={mutation.isPending}
          label="Allow local (email/password) login"
          description="When off and SSO is required, users must sign in through the configured identity provider."
          onLabel="On"
          offLabel="Off"
          onChange={(next) => update("local_login_allowed", next)}
        />
      </div>
    </Section>
  );
}

export function OverviewSection() {
  const { data: overview } = useOverview();
  const { data: settings } = useSettings();
  return (
    <>
      <OverviewTab overview={overview} />
      <SettingsToggles settings={settings} />
    </>
  );
}
