"use client";

import { useQuery } from "@tanstack/react-query";
import { getEnterpriseAuthOverview, getEnterpriseAuthSettings, type EnterpriseAuthOverview, type EnterpriseAuthSettings } from "@/lib/api/enterprise-auth";

export type TabKey = "overview" | "ldap" | "sso" | "mappings";

export function Tabs({ active, onChange }: { active: TabKey; onChange: (t: TabKey) => void }) {
  const tabs: { key: TabKey; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "ldap", label: "LDAP Directory" },
    { key: "sso", label: "SSO" },
    { key: "mappings", label: "Identity Mappings" },
  ];
  return (
    <div className="mb-6 flex gap-2 border-b border-line-secondary">
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          onClick={() => onChange(t.key)}
          className={`px-3 py-2 text-sm font-medium ${
            active === t.key ? "border-b-2 border-brand text-ink-primary" : "text-ink-tertiary hover:text-ink-primary"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="mb-6 rounded-lg border border-line-secondary bg-bg-primary p-5 shadow-sm">
      <h3 className="text-base font-semibold text-ink-primary">{title}</h3>
      {description ? <p className="mt-1 text-sm text-ink-tertiary">{description}</p> : null}
      <div className="mt-4">{children}</div>
    </div>
  );
}

export function Label({ children }: { children: React.ReactNode }) {
  return <label className="mb-1 block text-sm font-medium text-ink-primary">{children}</label>;
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`w-full rounded-md border border-line-secondary bg-bg-primary px-3 py-2 text-sm text-ink-primary focus:border-brand focus:outline-none ${props.className || ""}`}
    />
  );
}

export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={`w-full rounded-md border border-line-secondary bg-bg-primary px-3 py-2 text-sm text-ink-primary focus:border-brand focus:outline-none ${props.className || ""}`}
    />
  );
}

export function Button(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={`rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg disabled:opacity-50 ${props.className || ""}`}
    />
  );
}

export function GhostButton(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={`rounded-md border border-line-secondary px-4 py-2 text-sm font-medium text-ink-primary hover:bg-bg-secondary disabled:opacity-50 ${props.className || ""}`}
    />
  );
}

export function useOverview() {
  return useQuery<EnterpriseAuthOverview>({
    queryKey: ["enterprise-auth", "overview"],
    queryFn: getEnterpriseAuthOverview,
  });
}

export function useSettings() {
  return useQuery<EnterpriseAuthSettings>({
    queryKey: ["enterprise-auth", "settings"],
    queryFn: getEnterpriseAuthSettings,
  });
}
