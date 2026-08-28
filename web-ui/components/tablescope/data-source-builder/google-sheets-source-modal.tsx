"use client";

import { useEffect, useMemo, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import {
  IconCheck,
  IconFileSpreadsheet,
  IconLoader2,
  IconTable,
  IconX,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import type { SaasCredential } from "@/lib/api/connectors";
import {
  listGoogleDriveFiles,
  listGoogleSheetTabs,
  detectGoogleSheetTables,
  confirmGoogleSheetTable,
  type GoogleDriveFile,
  type GoogleSheetTab,
  type DetectedTable,
} from "@/lib/api/data-source-builder";
import {
  useBuilderStore,
  type SessionSource,
} from "@/lib/stores/data-source-builder-store";

export function GoogleSheetsSourceModal({
  credential,
  onClose,
}: {
  credential: SaasCredential;
  onClose: () => void;
}) {
  const { addSource, markCreated } = useBuilderStore(
    useShallow((s) => ({
      addSource: s.addSource,
      markCreated: s.markCreated,
    })),
  );

  const [files, setFiles] = useState<GoogleDriveFile[]>([]);
  const [loadingFiles, setLoadingFiles] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedFile, setSelectedFile] = useState<GoogleDriveFile | null>(null);
  const [tabs, setTabs] = useState<GoogleSheetTab[]>([]);
  const [loadingTabs, setLoadingTabs] = useState(false);

  const [selectedTab, setSelectedTab] = useState<GoogleSheetTab | null>(null);
  const [tables, setTables] = useState<DetectedTable[]>([]);
  const [loadingTables, setLoadingTables] = useState(false);

  const [selectedTableId, setSelectedTableId] = useState<number | null>(null);
  const [displayName, setDisplayName] = useState("");

  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoadingFiles(true);
    setError(null);
    listGoogleDriveFiles(credential.id)
      .then((res) => {
        if (!cancelled) setFiles(res.files);
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof Error ? err.message : "Could not load Google Drive files.",
          );
      })
      .finally(() => {
        if (!cancelled) setLoadingFiles(false);
      });
    return () => {
      cancelled = true;
    };
  }, [credential.id]);

  const selectFile = async (file: GoogleDriveFile) => {
    if (file.sourceType !== "google_sheet") {
      setError("Only native Google Sheets are supported in this flow.");
      return;
    }
    setSelectedFile(file);
    setSelectedTab(null);
    setTables([]);
    setSelectedTableId(null);
    setDisplayName(file.name);
    setError(null);
    setLoadingTabs(true);
    try {
      const res = await listGoogleSheetTabs(credential.id, file.id);
      setTabs(res.tabs);
      if (res.tabs.length === 1) {
        await selectTab(res.tabs[0], file);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load sheet tabs.");
    } finally {
      setLoadingTabs(false);
    }
  };

  const selectTab = async (tab: GoogleSheetTab, file = selectedFile) => {
    if (!file) return;
    setSelectedTab(tab);
    setTables([]);
    setSelectedTableId(null);
    setLoadingTables(true);
    setError(null);
    try {
      const res = await detectGoogleSheetTables(credential.id, file.id, {
        sheet_name: tab.title,
        max_rows: 1000,
        project_id: null,
      });
      setTables(res.tables);
      if (res.tables.length > 0) {
        setSelectedTableId(res.tables[0].mapping.id);
      }
      setDisplayName(`${file.name} · ${tab.title}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not detect tables.");
    } finally {
      setLoadingTables(false);
    }
  };

  const selectedTable = useMemo(
    () => tables.find((t) => t.mapping.id === selectedTableId) ?? null,
    [tables, selectedTableId],
  );

  const handleConfirm = async () => {
    if (!selectedFile || !selectedTab || !selectedTable) return;
    setConfirming(true);
    setError(null);
    try {
      const meta = await confirmGoogleSheetTable(
        credential.id,
        selectedFile.id,
        selectedTable.mapping.id,
        {
          display_name: displayName.trim() || selectedTable.mapping.tableName,
          project_id: null,
        },
      );
      const columns = selectedTable.columns;
      const source: SessionSource = {
        id: crypto.randomUUID(),
        sourceType: "google_drive",
        displayName: meta.file_name || displayName,
        connectionConfig: { credential_id: String(credential.id) },
        status: "ready",
        isFileUpload: true,
        viewName: meta.view_name,
        existing: true,
        projectId: null,
        fileMetadata: {
          name: meta.file_name || selectedFile.name,
          rows: 0,
          columns: columns.map((c) => c.relationalName),
          sheets: [selectedTab.title],
          acquisitionMethod: "google_drive",
          sourceHost: "Google Drive",
        },
        previewFields: columns.map((c) => ({
          field_name: c.relationalName,
          detected_type: c.teiidType,
        })),
        tables: [
          {
            tableName: meta.view_name,
            rows: 0,
            cols: columns.length,
            aiEnabled: true,
            state: "adding",
          },
        ],
      };
      addSource(source);
      markCreated([source.id]);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not confirm table.");
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl bg-bg-primary shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#0F9D58]/10 text-[#0F9D58]">
              <IconFileSpreadsheet size={20} />
            </span>
            <div>
              <h2 className="text-h3 text-ink-primary">Select Google Sheet</h2>
              <p className="text-caption text-ink-tertiary">
                Choose a spreadsheet, tab, and detected table from {credential.display_name}.
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

        {error && (
          <div className="border-b border-danger/20 bg-danger-bg/30 px-4 py-2 text-[12px] text-danger">
            {error}
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          {loadingFiles ? (
            <div className="flex items-center justify-center gap-2 py-12 text-small text-ink-tertiary">
              <IconLoader2 size={15} className="animate-spin" /> Loading files…
            </div>
          ) : files.length === 0 ? (
            <p className="py-12 text-center text-small text-ink-tertiary">
              No supported Google Drive files found.
            </p>
          ) : (
            <div className="space-y-4">
              <section>
                <p className="mb-2 text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
                  1. Spreadsheet
                </p>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {files.map((file) => {
                    const isSheet = file.sourceType === "google_sheet";
                    const isSelected = selectedFile?.id === file.id;
                    return (
                      <button
                        key={file.id}
                        type="button"
                        onClick={() => isSheet && selectFile(file)}
                        disabled={!isSheet}
                        className={`flex items-center gap-2 rounded-lg border px-3 py-2.5 text-left ${
                          isSelected
                            ? "border-brand-500 bg-brand-50/30"
                            : "border-line-tertiary bg-bg-primary hover:bg-bg-secondary"
                        } ${!isSheet ? "cursor-not-allowed opacity-50" : ""}`}
                      >
                        <IconFileSpreadsheet
                          size={18}
                          className={isSheet ? "text-[#0F9D58]" : "text-ink-tertiary"}
                        />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[13px] font-medium text-ink-primary">
                            {file.name}
                          </p>
                          <p className="text-caption text-ink-tertiary">
                            {isSheet ? "Google Sheet" : file.sourceType ?? file.mimeType}
                          </p>
                        </div>
                        {isSelected && <IconCheck size={16} className="text-brand-500" />}
                      </button>
                    );
                  })}
                </div>
              </section>

              {selectedFile && (
                <section>
                  <p className="mb-2 text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
                    2. Tab
                  </p>
                  {loadingTabs ? (
                    <div className="flex items-center gap-2 py-4 text-small text-ink-tertiary">
                      <IconLoader2 size={15} className="animate-spin" /> Loading tabs…
                    </div>
                  ) : tabs.length === 0 ? (
                    <p className="text-small text-ink-tertiary">No tabs found.</p>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {tabs.map((tab) => {
                        const isSelected = selectedTab?.title === tab.title;
                        return (
                          <button
                            key={tab.title}
                            type="button"
                            onClick={() => selectTab(tab)}
                            className={`rounded-lg border px-3 py-2 text-left text-[13px] ${
                              isSelected
                                ? "border-brand-500 bg-brand-50/30 font-medium text-ink-primary"
                                : "border-line-tertiary bg-bg-primary text-ink-secondary hover:bg-bg-secondary"
                            }`}
                          >
                            {tab.title}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </section>
              )}

              {selectedTab && (
                <section>
                  <p className="mb-2 text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
                    3. Detected tables
                  </p>
                  {loadingTables ? (
                    <div className="flex items-center gap-2 py-4 text-small text-ink-tertiary">
                      <IconLoader2 size={15} className="animate-spin" /> Detecting tables…
                    </div>
                  ) : tables.length === 0 ? (
                    <p className="text-small text-ink-tertiary">No tables detected.</p>
                  ) : (
                    <div className="space-y-2">
                      {tables.map((table) => {
                        const isSelected = selectedTableId === table.mapping.id;
                        return (
                          <button
                            key={table.mapping.id}
                            type="button"
                            onClick={() => setSelectedTableId(table.mapping.id)}
                            className={`w-full rounded-lg border px-3 py-2.5 text-left ${
                              isSelected
                                ? "border-brand-500 bg-brand-50/30"
                                : "border-line-tertiary bg-bg-primary hover:bg-bg-secondary"
                            }`}
                          >
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <IconTable size={16} className="text-brand-500" />
                                <span className="text-[13px] font-medium text-ink-primary">
                                  {table.mapping.tableName}
                                </span>
                                <span className="text-caption text-ink-tertiary">
                                  {table.mapping.rangeA1}
                                </span>
                              </div>
                              {isSelected && (
                                <IconCheck size={16} className="text-brand-500" />
                              )}
                            </div>
                            <p className="mt-1 truncate text-caption text-ink-tertiary">
                              {table.columns.map((c) => c.relationalName).join(", ")}
                            </p>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </section>
              )}

              {selectedTable && (
                <section>
                  <p className="mb-2 text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
                    4. Display name
                  </p>
                  <input
                    type="text"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
                  />
                </section>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-line-tertiary px-4 py-3">
          <Button variant="ghost" onClick={onClose} disabled={confirming}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => void handleConfirm()}
            disabled={confirming || !selectedTable || !displayName.trim()}
          >
            {confirming && <IconLoader2 size={14} className="animate-spin" />}
            Confirm & add source
          </Button>
        </div>
      </div>
    </div>
  );
}
