"use client";

import { useState } from "react";
import { OverviewSection } from "./enterprise-authentication-overview-tab";
import { LdapDirectoryTab } from "./enterprise-authentication-ldap-tab";
import { SsoTab } from "./enterprise-authentication-sso-tab";
import { IdentityMappingsTab } from "./enterprise-authentication-mappings-tab";
import { Tabs, type TabKey } from "./enterprise-authentication-shared";

export function EnterpriseAuthenticationPanel() {
  const [activeTab, setActiveTab] = useState<TabKey>("overview");

  return (
    <section className="max-w-4xl">
      <header className="mb-6">
        <h2 className="text-2xl font-semibold text-ink-primary">Enterprise Authentication</h2>
        <p className="mt-1 text-sm text-ink-tertiary">
          Configure LDAP directory sync and SAML single sign-on for this tenant.
        </p>
      </header>
      <Tabs active={activeTab} onChange={setActiveTab} />
      {activeTab === "overview" && <OverviewSection />}
      {activeTab === "ldap" && <LdapDirectoryTab />}
      {activeTab === "sso" && <SsoTab />}
      {activeTab === "mappings" && <IdentityMappingsTab />}
    </section>
  );
}
