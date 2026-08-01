import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DataSourceUpdateDialog } from "./data-source-update-dialog";
import type { PreflightResponse } from "@/lib/api/data-source-versions";

function preflight(over: {
  removedColumns?: string[];
  typeChangedColumns?: { column: string; from: string; to: string }[];
  dependencies?: { id: number; name: string }[];
}): PreflightResponse {
  const blockers = [
    ...(over.removedColumns?.length ? ["Replacement file is missing existing column(s): region"] : []),
    ...(over.typeChangedColumns?.length ? ["Column type change(s) detected: amount (number → string)"] : []),
  ];
  const version = {
    id: 2,
    versionNumber: 2,
    status: "staged" as const,
    updateMode: "replace",
    originalFilename: "sales.csv",
    checksum: "b",
    sizeBytes: 20,
    rowCount: 12,
    columnTypes: [],
    compatibility: {},
    uploaderId: 1,
    replacedVersionId: 1,
    activatedAt: null,
    createdAt: null,
    errorMessage: null,
  };
  return {
    status: "preflight_ready",
    viewName: "SALES_CSV",
    version,
    activeVersion: { ...version, id: 1, versionNumber: 1, status: "active" },
    compatibility: {
      addedColumns: ["channel"],
      removedColumns: over.removedColumns ?? [],
      typeChangedColumns: over.typeChangedColumns ?? [],
      blockers,
      compatible: blockers.length === 0,
      dependencies: over.dependencies ?? [],
      warnings: [],
      currentFileName: "sales.csv",
      proposedFileName: "sales.csv",
      currentRowCount: 10,
      proposedRowCount: 12,
      currentChecksum: "a",
      proposedChecksum: "b",
      updateMode: "replace",
    },
    canActivate: blockers.length === 0,
  };
}

function renderDialog(data: PreflightResponse, onConfirm = vi.fn()) {
  render(
    <DataSourceUpdateDialog
      open
      sourceName="sales.csv"
      preflight={data}
      busy={false}
      error={null}
      onConfirm={onConfirm}
      onCancel={vi.fn()}
    />,
  );
  return onConfirm;
}

describe("DataSourceUpdateDialog", () => {
  it("previews the schema diff and version transition", () => {
    renderDialog(preflight({}));
    expect(screen.getByText(/Added: channel/)).toBeInTheDocument();
    expect(screen.getByText(/Removed: none/)).toBeInTheDocument();
    expect(screen.getByText("v1 → v2")).toBeInTheDocument();
    expect(screen.getByText("10 → 12")).toBeInTheDocument();
  });

  it("previews dependent saved queries", () => {
    renderDialog(preflight({ dependencies: [{ id: 3, name: "Monthly revenue" }] }));
    expect(screen.getByText("Monthly revenue")).toBeInTheDocument();
  });

  it("activates only after explicit confirmation", () => {
    const onConfirm = renderDialog(preflight({}));
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Activate new version/ }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("blocks activation when a column was removed", () => {
    renderDialog(preflight({ removedColumns: ["region"] }));
    expect(
      screen.getByRole("button", { name: /Activate new version/ }),
    ).toBeDisabled();
    expect(screen.getByText(/missing existing column/)).toBeInTheDocument();
  });

  it("blocks activation when a column type changed", () => {
    renderDialog(
      preflight({
        typeChangedColumns: [{ column: "amount", from: "number", to: "string" }],
      }),
    );
    expect(
      screen.getByRole("button", { name: /Activate new version/ }),
    ).toBeDisabled();
    expect(screen.getByText(/Type changes: amount/)).toBeInTheDocument();
  });
});
