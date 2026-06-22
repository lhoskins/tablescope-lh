"use client";

import { useEffect, useMemo, useState } from "react";
import { IconCheck, IconLoader2, IconX } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  createDbConnection,
  createSaasCredential,
  testDbConnectionInline,
  testSaasInline,
  updateDbConnection,
  updateSaasCredential,
  type CreatedConnection,
} from "@/lib/api/connectors";
import { type ConnectorSpec } from "./connector-fields";
import { BrandLogo, connectorChip } from "./brand-logo";

export interface EditTarget {
  connection: CreatedConnection;
}

export function ConnectionModal({
  spec,
  editTarget,
  onClose,
  onSaved,
}: {
  spec: ConnectorSpec;
  editTarget?: CreatedConnection | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = Boolean(editTarget);
  const [name, setName] = useState(editTarget?.friendlyName ?? "");
  const [values, setValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const f of spec.fields) {
      init[f.key] =
        f.key === "port" && spec.defaultPort ? String(spec.defaultPort) : "";
    }
    if (editTarget && spec.kind === "database") {
      init.host = editTarget.hostOrAccount;
    }
    return init;
  });
  const [ssl, setSsl] = useState(spec.kind === "database");
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [tested, setTested] = useState(isEdit); // editing allows save without retest
  const [error, setError] = useState<string | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);

  useEffect(() => {
    setTested(isEdit);
    setError(null);
    setOkMsg(null);
  }, [isEdit, values, name]);

  const requiredFilled = useMemo(() => {
    if (!name.trim()) return false;
    return spec.fields.every(
      (f) => f.optional || (values[f.key] ?? "").trim().length > 0,
    );
  }, [name, spec.fields, values]);

  const config = (): Record<string, string> => {
    const out: Record<string, string> = {};
    for (const f of spec.fields) {
      const v = (values[f.key] ?? "").trim();
      if (v) out[f.key] = v;
    }
    return out;
  };

  const setField = (key: string, v: string) =>
    setValues((prev) => ({ ...prev, [key]: v }));

  const handleTest = async () => {
    setTesting(true);
    setError(null);
    setOkMsg(null);
    try {
      const res =
        spec.kind === "database"
          ? await testDbConnectionInline({
              db_type: spec.key,
              host: values.host,
              port: values.port ? Number(values.port) : undefined,
              database_name: values.database_name,
              username: values.username,
              password: values.password,
              ssl_mode: ssl ? "require" : undefined,
            })
          : await testSaasInline({ connector_type: spec.key, config: config() });
      if (res.success) {
        setTested(true);
        setOkMsg(res.message || "Connection successful");
      } else {
        setError(res.message || "Connection failed");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection failed");
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      if (spec.kind === "database") {
        const body = {
          name: name.trim(),
          db_type: spec.key,
          host: values.host,
          port: values.port ? Number(values.port) : undefined,
          database_name: values.database_name,
          username: values.username,
          password: values.password || undefined,
          ssl_mode: ssl ? "require" : undefined,
        };
        if (editTarget) await updateDbConnection(editTarget.id, body);
        else await createDbConnection(body);
      } else {
        if (editTarget) {
          await updateSaasCredential(editTarget.id, {
            display_name: name.trim(),
            config: Object.keys(config()).length ? config() : undefined,
          });
        } else {
          await createSaasCredential({
            connector_type: spec.key,
            display_name: name.trim(),
            config: config(),
          });
        }
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save connection");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[88vh] w-full max-w-lg overflow-y-auto rounded-xl bg-bg-primary p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between">
          <div className="flex items-center gap-3">
            <span
              className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${connectorChip(
                spec.key,
              )}`}
            >
              <BrandLogo connector={spec.key} size={22} />
            </span>
            <div>
              <h2 className="text-h2 text-ink-primary">
                {isEdit ? "Edit connection" : `Connect ${spec.name}`}
              </h2>
              <p className="text-small text-ink-tertiary">
                {spec.kind === "database"
                  ? "Database connection"
                  : "SaaS connection"}{" "}
                · give it a friendly name to reuse it later.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-7 w-7 items-center justify-center rounded text-ink-tertiary hover:bg-bg-secondary"
          >
            <IconX size={16} />
          </button>
        </div>

        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-ink-secondary">
              Friendly name
            </span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Sales DB"
              className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
            />
          </label>

          <div className="grid grid-cols-2 gap-3">
            {spec.fields.map((f) => (
              <label
                key={f.key}
                className={f.key === "host" ? "col-span-2 block" : "block"}
              >
                <span className="mb-1 block text-[12px] font-medium text-ink-secondary">
                  {f.label}
                  {f.optional && (
                    <span className="ml-1 text-ink-tertiary">(optional)</span>
                  )}
                </span>
                <input
                  type={f.type ?? "text"}
                  value={values[f.key] ?? ""}
                  placeholder={
                    f.placeholder ??
                    (isEdit && f.type === "password"
                      ? "•••••••• (unchanged)"
                      : undefined)
                  }
                  onChange={(e) => setField(f.key, e.target.value)}
                  className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
                />
              </label>
            ))}
          </div>

          {spec.kind === "database" && (
            <label className="flex items-center gap-2 text-[12px] text-ink-secondary">
              <input
                type="checkbox"
                checked={ssl}
                onChange={(e) => setSsl(e.target.checked)}
                className="h-4 w-4 accent-[var(--brand,#185FA5)]"
              />
              Use SSL
            </label>
          )}

          {error && (
            <div className="rounded-md border border-danger/40 bg-danger-bg/40 px-3 py-2 text-[12px] text-danger">
              {error}
            </div>
          )}
          {okMsg && !error && (
            <div className="flex items-center gap-1.5 rounded-md border border-success/40 bg-success-bg/40 px-3 py-2 text-[12px] text-success">
              <IconCheck size={14} /> {okMsg}
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="secondary"
              onClick={handleTest}
              disabled={testing || !requiredFilled}
            >
              {testing && <IconLoader2 size={14} className="animate-spin" />}
              Test connection
            </Button>
            <Button
              variant="primary"
              onClick={handleSave}
              disabled={saving || !requiredFilled || (!tested && !isEdit)}
            >
              {saving && <IconLoader2 size={14} className="animate-spin" />}
              {isEdit ? "Save changes" : "Save connection"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
