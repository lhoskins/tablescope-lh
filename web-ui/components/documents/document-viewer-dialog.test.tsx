import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const get = vi.fn();
const stream = vi.fn();

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: (...args: unknown[]) => get(...args),
    stream: (...args: unknown[]) => stream(...args),
  },
}));

import { DocumentViewerDialog } from "./document-viewer-dialog";
import type { ProjectDocument } from "./DocumentsTab/project-document";

function makeDoc(overrides: Partial<ProjectDocument> = {}): ProjectDocument {
  return {
    id: 1,
    title: null,
    filename: "report.txt",
    original_filename: "report.txt",
    asset_type: "txt",
    content_type: "text/plain",
    file_extension: ".txt",
    file_size_bytes: 42,
    status: "uploaded",
    ai_status: "pending",
    ai_summary: null,
    ai_metadata: null,
    visibility: "shared_project",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("DocumentViewerDialog", () => {
  beforeEach(() => {
    get.mockReset();
    stream.mockReset();
    (URL as unknown as { createObjectURL: () => string }).createObjectURL = vi.fn(() => "blob:mock-url");
    (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a bounded text preview for a .txt document", async () => {
    get.mockResolvedValueOnce({
      assetId: 1, filename: "report.txt", contentType: "text/plain", fileSizeBytes: 42,
      kind: "text", text: "Hello, viewer!", truncated: false,
    });

    render(<DocumentViewerDialog projectId={7} document={makeDoc()} onClose={vi.fn()} />);

    await screen.findByText("Hello, viewer!");
    expect(get).toHaveBeenCalledWith("/api/projects/7/assets/1/preview");
    expect(stream).not.toHaveBeenCalled();
  });

  it("shows a truncation notice when the preview was cut short", async () => {
    get.mockResolvedValueOnce({
      assetId: 1, filename: "report.txt", contentType: "text/plain", fileSizeBytes: 999,
      kind: "text", text: "partial…", truncated: true,
    });

    render(<DocumentViewerDialog projectId={7} document={makeDoc()} onClose={vi.fn()} />);

    await screen.findByText(/this preview is truncated/i);
  });

  it("fetches an authenticated blob and renders a PDF with <embed>, not a raw src URL", async () => {
    const blob = new Blob(["%PDF-1.4"], { type: "application/pdf" });
    stream.mockResolvedValueOnce({ ok: true, status: 200, blob: async () => blob });

    render(
      <DocumentViewerDialog
        projectId={7}
        document={makeDoc({ filename: "doc.pdf", original_filename: "doc.pdf", file_extension: ".pdf", content_type: "application/pdf" })}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => expect(stream).toHaveBeenCalledWith("/api/projects/7/assets/1/content"));
    expect(get).not.toHaveBeenCalled();
    await waitFor(() => {
      const el = document.querySelector("embed");
      expect(el).toBeTruthy();
      expect(el?.getAttribute("src")).toBe("blob:mock-url");
    });
  });

  it("shows the failure reason and a working Download action for an unsupported file", async () => {
    get.mockResolvedValueOnce({
      assetId: 1, filename: "old.doc", contentType: "application/msword", fileSizeBytes: 10,
      kind: "unsupported", reason: "This file could not be converted for preview.",
    });
    const blob = new Blob(["raw bytes"]);
    stream.mockResolvedValueOnce({ ok: true, status: 200, blob: async () => blob });

    render(
      <DocumentViewerDialog
        projectId={7}
        document={makeDoc({ filename: "old.doc", original_filename: "old.doc", file_extension: ".doc" })}
        onClose={vi.fn()}
      />,
    );

    await screen.findByText("This file could not be converted for preview.");
    const downloadButtons = screen.getAllByRole("button", { name: /download/i });
    fireEvent.click(downloadButtons[downloadButtons.length - 1]);

    await waitFor(() => expect(stream).toHaveBeenCalledWith("/api/projects/7/assets/1/content"));
  });

  it("closes on Escape", async () => {
    get.mockResolvedValueOnce({ assetId: 1, filename: "report.txt", contentType: "text/plain", fileSizeBytes: 42, kind: "text", text: "hi" });
    const onClose = vi.fn();
    render(<DocumentViewerDialog projectId={7} document={makeDoc()} onClose={onClose} />);
    await screen.findByText("hi");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("renders a bounded spreadsheet preview with sheet tabs", async () => {
    get.mockResolvedValueOnce({
      assetId: 1, filename: "book.xlsx", contentType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      fileSizeBytes: 500, kind: "spreadsheet", truncatedSheets: false,
      sheets: [
        { name: "Sheet1", rows: [["a", "b"], [1, 2]], totalRows: 2, totalCols: 2, truncatedRows: false, truncatedCols: false },
        { name: "Sheet2", rows: [["x"]], totalRows: 1, totalCols: 1, truncatedRows: false, truncatedCols: false },
      ],
    });

    render(
      <DocumentViewerDialog
        projectId={7}
        document={makeDoc({ filename: "book.xlsx", original_filename: "book.xlsx", file_extension: ".xlsx" })}
        onClose={vi.fn()}
      />,
    );

    await screen.findByText("Sheet1");
    expect(screen.getByText("Sheet2")).toBeTruthy();
    expect(screen.getByText("a")).toBeTruthy();

    fireEvent.click(screen.getByText("Sheet2"));
    expect(screen.getByText("x")).toBeTruthy();
  });
});
