import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { AiUploadDropzone } from "./ai-upload-dropzone";
import type { Classification } from "@/lib/uploads/intake";

const addSource = vi.fn();
const markCreated = vi.fn();
const analyzeFile = vi.fn();
const upload = vi.fn();
const classifyFile = vi.fn();

vi.mock("@/lib/stores/data-source-builder-store", () => ({
  useBuilderStore: (selector: (s: unknown) => unknown) =>
    selector({ addSource, markCreated, hasSource: () => false }),
}));

vi.mock("@/lib/api/data-source-builder", () => ({
  analyzeFile: (...args: unknown[]) => analyzeFile(...args),
}));

vi.mock("@/lib/api-client", () => ({
  apiClient: { upload: (...args: unknown[]) => upload(...args) },
}));

vi.mock("@/lib/uploads/intake", async () => {
  const actual = await vi.importActual<typeof import("@/lib/uploads/intake")>(
    "@/lib/uploads/intake",
  );
  return {
    ...actual,
    fetchCapabilities: () => Promise.resolve(actual.FALLBACK_CAPABILITIES),
    classifyFile: (...args: unknown[]) => classifyFile(...args),
  };
});

function classification(over: Partial<Classification>): Classification {
  return {
    extension: ".csv",
    family: "structured_tabular",
    destination: "data_source",
    confidence: "high",
    reason: "",
    ambiguous: false,
    alternatives: [],
    ...over,
  };
}

const previewResponse = {
  upload_session_id: "sess-1",
  file: {
    file_name: "sales.csv",
    file_type: "csv",
    row_count: 2,
    column_count: 1,
    file_size_bytes: 10,
    sheet_name: null,
  },
  fields: [{ field_name: "id" }],
};

async function pick(fileName: string, type: string) {
  const input = document.querySelector(
    'input[type="file"]',
  ) as HTMLInputElement;
  const file = new File(["a,b\n1,2\n"], fileName, { type });
  await act(async () => {
    fireEvent.change(input, { target: { files: [file] } });
  });
}

describe("AiUploadDropzone (unified intake)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    analyzeFile.mockResolvedValue(previewResponse);
    upload.mockResolvedValue({});
  });

  it("routes a classified spreadsheet into the structured pipeline", async () => {
    classifyFile.mockResolvedValue(classification({}));
    render(<AiUploadDropzone projectId={7} />);
    await pick("sales.csv", "text/csv");

    await waitFor(() => expect(addSource).toHaveBeenCalledTimes(1));
    expect(analyzeFile).toHaveBeenCalled();
    expect(upload).not.toHaveBeenCalled();
    expect(markCreated).toHaveBeenCalled();
  });

  it("routes a classified document into the document pipeline", async () => {
    classifyFile.mockResolvedValue(
      classification({
        extension: ".pdf",
        family: "unstructured_document",
        destination: "document",
      }),
    );
    render(<AiUploadDropzone projectId={7} />);
    await pick("policy.pdf", "application/pdf");

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect(upload.mock.calls[0][0]).toBe("/api/projects/7/assets/upload");
    expect(addSource).not.toHaveBeenCalled();
  });

  it("asks the user to decide when the classifier is unsure", async () => {
    classifyFile.mockResolvedValue(
      classification({
        extension: ".txt",
        family: "semi_structured",
        destination: "document",
        confidence: "medium",
        ambiguous: true,
        alternatives: ["data_source", "document"],
      }),
    );
    render(<AiUploadDropzone projectId={7} />);
    await pick("notes.txt", "text/plain");

    const dataButton = await screen.findByRole("button", { name: "Use as data" });
    expect(upload).not.toHaveBeenCalled();
    expect(addSource).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(dataButton);
    });
    await waitFor(() => expect(addSource).toHaveBeenCalledTimes(1));
  });

  it("surfaces a rejected file without ingesting it", async () => {
    classifyFile.mockRejectedValue(new Error("payload.exe: unsupported file type."));
    render(<AiUploadDropzone />);
    await pick("payload.exe", "application/octet-stream");

    expect(
      await screen.findByText(/unsupported file type/i),
    ).toBeInTheDocument();
    expect(addSource).not.toHaveBeenCalled();
    expect(upload).not.toHaveBeenCalled();
  });

  it("refuses a document upload when no project context is available", async () => {
    classifyFile.mockResolvedValue(
      classification({
        extension: ".pdf",
        family: "unstructured_document",
        destination: "document",
      }),
    );
    render(<AiUploadDropzone />);
    await pick("policy.pdf", "application/pdf");

    expect(
      await screen.findByText(/open this upload from a project/i),
    ).toBeInTheDocument();
    expect(upload).not.toHaveBeenCalled();
  });

  it("accepts both spreadsheets and documents on the file input", async () => {
    classifyFile.mockResolvedValue(classification({}));
    render(<AiUploadDropzone projectId={7} />);
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    await waitFor(() => expect(input.accept).toContain(".pdf"));
    expect(input.accept).toContain(".csv");
    expect(input.accept).toContain(".docx");
  });
});
