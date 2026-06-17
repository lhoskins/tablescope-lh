"use client";

import { useEffect, useState } from "react";
import {
  IconApi,
  IconDatabase,
  IconFileSpreadsheet,
  IconServer,
  IconX,
  type Icon,
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import type { SourceType } from "@/lib/stores/data-source-builder-store";
import { ConnectionForm } from "./connection-form";
import { FileUploadForm } from "./file-upload-form";
import type { SourceCategory } from "./util";

interface Connector {
  type: SourceType;
  label: string;
  description: string;
  icon: Icon;
  category: SourceCategory;
  enabled: boolean;
}

const CONNECTORS: Connector[] = [
  {
    type: "postgresql",
    label: "PostgreSQL",
    description: "Connect a PostgreSQL database",
    icon: IconDatabase,
    category: "database",
    enabled: true,
  },
  {
    type: "mysql",
    label: "MySQL / MariaDB",
    description: "Connect a MySQL or MariaDB database",
    icon: IconDatabase,
    category: "database",
    enabled: true,
  },
  {
    type: "snowflake",
    label: "Snowflake",
    description: "Connect a Snowflake warehouse",
    icon: IconServer,
    category: "warehouse",
    enabled: true,
  },
  {
    type: "bigquery",
    label: "BigQuery",
    description: "Connect a BigQuery dataset",
    icon: IconServer,
    category: "warehouse",
    enabled: true,
  },
  {
    type: "rest_api",
    label: "REST API",
    description: "Connect a REST API source (coming soon)",
    icon: IconApi,
    category: "api",
    enabled: false,
  },
  {
    type: "csv",
    label: "File upload (CSV/Excel)",
    description: "Upload a CSV or Excel file",
    icon: IconFileSpreadsheet,
    category: "file",
    enabled: true,
  },
];

export function SourceTypePickerModal({
  open,
  initialCategory,
  onClose,
}: {
  open: boolean;
  initialCategory?: SourceCategory;
  onClose: () => void;
}) {
  const [selected, setSelected] = useState<Connector | null>(null);

  useEffect(() => {
    if (open) setSelected(null);
  }, [open]);

  if (!open) return null;

  const visible = initialCategory
    ? CONNECTORS.filter((c) => c.category === initialCategory)
    : CONNECTORS;

  const isFile = selected?.category === "file";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[85vh] w-full max-w-xl overflow-y-auto rounded-xl bg-bg-primary p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-h2 text-ink-primary">
              {selected ? `Connect ${selected.label}` : "Add a data source"}
            </h2>
            <p className="text-small text-ink-tertiary">
              {selected
                ? "Configure the connection and add it to your session."
                : "Pick a connector to add to this session."}
            </p>
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

        {!selected ? (
          <div className="grid grid-cols-2 gap-2.5">
            {visible.map((c) => {
              const Icon = c.icon;
              return (
                <button
                  key={c.type}
                  type="button"
                  disabled={!c.enabled}
                  onClick={() => setSelected(c)}
                  className={cn(
                    "flex items-start gap-3 rounded-lg border border-line-tertiary p-3 text-left transition-colors",
                    c.enabled
                      ? "hover:border-brand-500 hover:bg-brand-50/30"
                      : "cursor-not-allowed opacity-50",
                  )}
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-bg-secondary text-ink-secondary">
                    <Icon size={18} />
                  </span>
                  <span>
                    <span className="block text-[13px] font-semibold text-ink-primary">
                      {c.label}
                    </span>
                    <span className="block text-caption text-ink-tertiary">
                      {c.description}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        ) : isFile ? (
          <FileUploadForm onAdded={onClose} onCancel={() => setSelected(null)} />
        ) : (
          <ConnectionForm
            sourceType={selected.type}
            onAdded={onClose}
            onCancel={() => setSelected(null)}
          />
        )}
      </div>
    </div>
  );
}
