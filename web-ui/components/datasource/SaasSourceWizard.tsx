"use client";


import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";import { ConnectorType } from "./SaasSourceWizard/connector-type";
import { CONNECTORS } from "./SaasSourceWizard/connectors";
import { ObjectInfo } from "./SaasSourceWizard/object-info";
import { FieldInfo } from "./SaasSourceWizard/field-info";
import { PreviewResult } from "./SaasSourceWizard/preview-result";
import { Step } from "./SaasSourceWizard/step";
import { SavedCredential } from "./SaasSourceWizard/saved-credential";



export function SaasSourceWizard({
  projectId,
  initialConnector,
  initialCredentialId,
  onClose,
  onCreated,
}: {
  projectId?: number;
  initialConnector?: ConnectorType;
  initialCredentialId?: number;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [step, setStep] = useState<Step>("connect");
  const [connector, setConnector] = useState<ConnectorType>(
    initialConnector ?? "hubspot"
  );
  const [savedCreds, setSavedCreds] = useState<SavedCredential[]>([]);

  // HubSpot
  const [hsToken, setHsToken] = useState("");
  // Salesforce
  const [sf, setSf] = useState({
    instance_url: "",
    client_id: "",
    client_secret: "",
    username: "",
    password: "",
    security_token: "",
  });
  // QuickBooks
  const [qb, setQb] = useState({
    access_token: "",
    realm_id: "",
    environment: "production",
  });

  const [credName, setCredName] = useState("");
  const [credentialId, setCredentialId] = useState<number | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testMessage, setTestMessage] = useState<string | null>(null);

  const [objects, setObjects] = useState<ObjectInfo[]>([]);
  const [selectedObject, setSelectedObject] = useState<ObjectInfo | null>(null);
  const [fields, setFields] = useState<FieldInfo[]>([]);
  const [selectedFields, setSelectedFields] = useState<Set<string>>(new Set());
  const [displayName, setDisplayName] = useState("");
  const [previewData, setPreviewData] = useState<PreviewResult | null>(null);

  function config(): Record<string, unknown> {
    if (connector === "hubspot") return { access_token: hsToken };
    if (connector === "quickbooks") return { ...qb };
    return { ...sf };
  }

  function credValid(): boolean {
    if (connector === "hubspot") return !!hsToken.trim();
    if (connector === "quickbooks")
      return !!qb.access_token.trim() && !!qb.realm_id.trim();
    return (
      !!sf.instance_url &&
      !!sf.client_id &&
      !!sf.client_secret &&
      !!sf.username &&
      !!sf.password
    );
  }

  async function handleTest() {
    setBusy(true);
    setError(null);
    setTestMessage(null);
    try {
      const res = await apiClient.post<{ success: boolean; message: string }>(
        "/api/saas-sources/test",
        credentialId != null
          ? { credential_id: credentialId }
          : { connector_type: connector, config: config() }
      );
      if (!res.success) {
        setError(res.message);
        return;
      }
      setTestMessage(res.message);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connection test failed");
    } finally {
      setBusy(false);
    }
  }

  // Load saved SaaS credentials; if launched from a saved one (the "Connected"
  // category), select it and jump straight to object selection (item 5).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await apiClient.get<SavedCredential[]>(
          "/api/saas-sources/credentials",
        );
        if (cancelled) return;
        setSavedCreds(rows);
        if (initialCredentialId != null) {
          const match = rows.find((r) => r.id === initialCredentialId);
          if (match) {
            setCredentialId(match.id);
            setConnector(match.connector_type as ConnectorType);
            void loadObjectsFor(match.id);
          }
        }
      } catch {
        // Non-fatal: user can still enter credentials manually.
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadObjectsFor(credId: number) {
    setBusy(true);
    setError(null);
    try {
      const res = await apiClient.post<{ objects: ObjectInfo[] }>(
        "/api/saas-sources/objects",
        { credential_id: credId },
      );
      setObjects(res.objects);
      setStep("object");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load objects");
    } finally {
      setBusy(false);
    }
  }

  async function handleConnectNext() {
    setBusy(true);
    setError(null);
    try {
      // Persist the credential (encrypted) then list objects.
      let credId = credentialId;
      if (credId === null) {
        const cred = await apiClient.post<{ id: number }>(
          "/api/saas-sources/credentials",
          {
            connector_type: connector,
            display_name: credName.trim() || `${connector} connection`,
            config: config(),
          }
        );
        credId = cred.id;
        setCredentialId(credId);
      }
      const res = await apiClient.post<{ objects: ObjectInfo[] }>(
        "/api/saas-sources/objects",
        { credential_id: credId }
      );
      setObjects(res.objects);
      setStep("object");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not connect");
    } finally {
      setBusy(false);
    }
  }

  async function loadFields(obj: ObjectInfo) {
    if (credentialId === null) return;
    setBusy(true);
    setError(null);
    try {
      const res = await apiClient.post<{ fields: FieldInfo[] }>(
        "/api/saas-sources/fields",
        { credential_id: credentialId, object_type: obj.name }
      );
      setFields(res.fields);
      // Default-select a handful of common fields (first 8) for convenience.
      setSelectedFields(new Set(res.fields.slice(0, 8).map((f) => f.name)));
      setSelectedObject(obj);
      setDisplayName(`${connector}_${obj.name}`);
      setStep("fields");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load fields");
    } finally {
      setBusy(false);
    }
  }

  async function loadPreview() {
    if (credentialId === null || !selectedObject) return;
    setBusy(true);
    setError(null);
    try {
      const res = await apiClient.post<PreviewResult>(
        "/api/saas-sources/preview",
        {
          credential_id: credentialId,
          object_type: selectedObject.name,
          selected_fields: Array.from(selectedFields),
          limit: 20,
        }
      );
      setPreviewData(res);
      setStep("preview");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load preview");
    } finally {
      setBusy(false);
    }
  }

  async function handleSave() {
    if (credentialId === null || !selectedObject || !displayName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiClient.post("/api/saas-sources", {
        credential_id: credentialId,
        connector_type: connector,
        object_type: selectedObject.name,
        selected_fields: Array.from(selectedFields),
        display_name: displayName.trim(),
        project_id: projectId ?? null,
      });
      onCreated();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create data source");
    } finally {
      setBusy(false);
    }
  }

  function toggleField(name: string) {
    setSelectedFields((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  const input =
    "w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none";
  const label = "block text-xs font-medium text-slate-600 mb-1";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-lg bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">Connect SaaS App</h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Step indicator */}
        <div className="mb-4 flex items-center gap-2 text-xs">
          {(["connect", "object", "fields", "preview"] as Step[]).map((s, i) => (
            <span
              key={s}
              className={`rounded-full px-2 py-0.5 ${
                step === s ? "bg-brand text-brand-fg" : "bg-slate-100 text-slate-500"
              }`}
            >
              {i + 1}. {s}
            </span>
          ))}
        </div>

        {error && (
          <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Step 1: Connector + credentials */}
        {step === "connect" && (
          <div className="space-y-3">
            {savedCreds.filter((c) => c.connector_type === connector).length > 0 && (
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <label className={label}>Use a saved connection (Connected)</label>
                <select
                  className={input}
                  value={credentialId ?? ""}
                  onChange={(e) =>
                    setCredentialId(e.target.value ? Number(e.target.value) : null)
                  }
                >
                  <option value="">— Enter new credentials —</option>
                  {savedCreds
                    .filter((c) => c.connector_type === connector)
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.display_name}
                      </option>
                    ))}
                </select>
                {credentialId != null && (
                  <p className="mt-2 text-xs text-slate-500">
                    Using saved credentials — no need to re-enter them.
                  </p>
                )}
              </div>
            )}
            <div>
              <label className={label}>App</label>
              <select
                className={input}
                value={connector}
                onChange={(e) => {
                  setConnector(e.target.value as ConnectorType);
                  setCredentialId(null);
                  setTestMessage(null);
                }}
              >
                {CONNECTORS.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className={label}>Connection Name</label>
              <input
                className={input}
                value={credName}
                onChange={(e) => setCredName(e.target.value)}
                placeholder={`${connector} connection`}
              />
            </div>

            {connector === "hubspot" && (
              <div>
                <label className={label}>Private App Access Token</label>
                <input
                  className={input}
                  type="password"
                  value={hsToken}
                  onChange={(e) => setHsToken(e.target.value)}
                  placeholder="pat-na1-..."
                  autoComplete="new-password"
                />
                <p className="mt-1 text-xs text-slate-400">
                  Settings → Integrations → Private Apps → create app with CRM read scopes.
                </p>
              </div>
            )}

            {connector === "salesforce" && (
              <div className="space-y-3">
                <div>
                  <label className={label}>Instance URL</label>
                  <input
                    className={input}
                    value={sf.instance_url}
                    onChange={(e) => setSf((s) => ({ ...s, instance_url: e.target.value }))}
                    placeholder="https://login.salesforce.com"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={label}>Client ID</label>
                    <input
                      className={input}
                      value={sf.client_id}
                      onChange={(e) => setSf((s) => ({ ...s, client_id: e.target.value }))}
                      autoComplete="off"
                    />
                  </div>
                  <div>
                    <label className={label}>Client Secret</label>
                    <input
                      className={input}
                      type="password"
                      value={sf.client_secret}
                      onChange={(e) => setSf((s) => ({ ...s, client_secret: e.target.value }))}
                      autoComplete="new-password"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={label}>Username</label>
                    <input
                      className={input}
                      value={sf.username}
                      onChange={(e) => setSf((s) => ({ ...s, username: e.target.value }))}
                      autoComplete="off"
                    />
                  </div>
                  <div>
                    <label className={label}>Password</label>
                    <input
                      className={input}
                      type="password"
                      value={sf.password}
                      onChange={(e) => setSf((s) => ({ ...s, password: e.target.value }))}
                      autoComplete="new-password"
                    />
                  </div>
                </div>
                <div>
                  <label className={label}>Security Token (optional)</label>
                  <input
                    className={input}
                    type="password"
                    value={sf.security_token}
                    onChange={(e) => setSf((s) => ({ ...s, security_token: e.target.value }))}
                    autoComplete="new-password"
                  />
                </div>
              </div>
            )}

            {connector === "quickbooks" && (
              <div className="space-y-3">
                <div>
                  <label className={label}>Access Token (OAuth2)</label>
                  <input
                    className={input}
                    type="password"
                    value={qb.access_token}
                    onChange={(e) => setQb((s) => ({ ...s, access_token: e.target.value }))}
                    placeholder="eyJ..."
                    autoComplete="new-password"
                  />
                  <p className="mt-1 text-xs text-slate-400">
                    Generate from the Intuit Developer portal (OAuth2 Playground) with the
                    Accounting scope. Tokens expire ~1h.
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={label}>Company (Realm) ID</label>
                    <input
                      className={input}
                      value={qb.realm_id}
                      onChange={(e) => setQb((s) => ({ ...s, realm_id: e.target.value }))}
                      placeholder="1234567890"
                      autoComplete="off"
                    />
                  </div>
                  <div>
                    <label className={label}>Environment</label>
                    <select
                      className={input}
                      value={qb.environment}
                      onChange={(e) => setQb((s) => ({ ...s, environment: e.target.value }))}
                    >
                      <option value="production">Production</option>
                      <option value="sandbox">Sandbox</option>
                    </select>
                  </div>
                </div>
              </div>
            )}

            {testMessage && <p className="text-sm text-green-700">{testMessage}</p>}

            <div className="flex justify-between pt-2">
              <button
                onClick={handleTest}
                disabled={busy || (credentialId == null && !credValid())}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                {busy ? "Testing..." : "Test Connection"}
              </button>
              <button
                onClick={handleConnectNext}
                disabled={busy || (credentialId == null && !credValid())}
                className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
              >
                Next: Choose Object
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Object */}
        {step === "object" && (
          <div className="space-y-3">
            <label className={label}>Select an Object</label>
            <div className="max-h-72 overflow-y-auto rounded-md border border-slate-200">
              {objects.length === 0 && (
                <p className="px-3 py-2 text-sm text-slate-400">No objects available.</p>
              )}
              {objects.map((o) => (
                <button
                  key={o.name}
                  onClick={() => loadFields(o)}
                  disabled={busy}
                  className="flex w-full items-center justify-between border-b border-slate-100 px-3 py-2 text-left text-sm hover:bg-slate-50 disabled:opacity-50"
                >
                  <span className="font-medium text-slate-800">{o.label}</span>
                  <span className="text-xs uppercase text-slate-400">{o.name}</span>
                </button>
              ))}
            </div>
            <div className="flex justify-between pt-2">
              <button
                onClick={() => setStep("connect")}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Back
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Fields */}
        {step === "fields" && selectedObject && (
          <div className="space-y-3">
            <div>
              <label className={label}>Data Source Name</label>
              <input
                className={input}
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
              />
            </div>
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium text-slate-600">
                Fields in {selectedObject.label} ({selectedFields.size} selected)
              </p>
              <div className="flex gap-2 text-xs">
                <button
                  onClick={() => setSelectedFields(new Set(fields.map((f) => f.name)))}
                  className="text-brand hover:underline"
                >
                  Select All
                </button>
                <button
                  onClick={() => setSelectedFields(new Set())}
                  className="text-slate-500 hover:underline"
                >
                  Clear
                </button>
              </div>
            </div>
            <div className="max-h-60 overflow-y-auto rounded-md border border-slate-200">
              {fields.map((f) => (
                <label
                  key={f.name}
                  className="flex cursor-pointer items-center gap-2 border-b border-slate-100 px-3 py-1.5 text-sm hover:bg-slate-50"
                >
                  <input
                    type="checkbox"
                    checked={selectedFields.has(f.name)}
                    onChange={() => toggleField(f.name)}
                  />
                  <span className="flex-1 text-slate-800">{f.label}</span>
                  <span className="text-xs text-slate-400">{f.saas_type}</span>
                </label>
              ))}
            </div>
            <div className="flex justify-between pt-2">
              <button
                onClick={() => setStep("object")}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Back
              </button>
              <button
                onClick={loadPreview}
                disabled={busy || selectedFields.size === 0}
                className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
              >
                {busy ? "Loading..." : "Next: Preview"}
              </button>
            </div>
          </div>
        )}

        {/* Step 4: Preview + Save */}
        {step === "preview" && previewData && (
          <div className="space-y-3">
            <p className="text-xs font-medium text-slate-600">
              Preview ({previewData.rows.length} sample rows). On save, the object syncs
              into a staging table and becomes queryable.
            </p>
            <div className="max-h-72 overflow-auto rounded-md border border-slate-200">
              <table className="min-w-full divide-y divide-slate-200">
                <thead className="bg-slate-50">
                  <tr>
                    {previewData.columns.map((c) => (
                      <th
                        key={c}
                        className="whitespace-nowrap px-3 py-2 text-left text-xs font-medium uppercase text-slate-500"
                      >
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {previewData.rows.map((row, i) => (
                    <tr key={i}>
                      {previewData.columns.map((c) => (
                        <td
                          key={c}
                          className="whitespace-nowrap px-3 py-1.5 text-sm text-slate-700"
                        >
                          {row[c] === null || row[c] === undefined
                            ? ""
                            : String(row[c])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex justify-between pt-2">
              <button
                onClick={() => setStep("fields")}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Back
              </button>
              <button
                onClick={handleSave}
                disabled={busy || !displayName.trim()}
                className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
              >
                {busy ? "Creating..." : "Create Data Source"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
