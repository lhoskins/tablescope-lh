"use client";

import { apiClient } from "@/lib/api-client";

/** Where the intake sends a file after classification. */
export type UploadDestination = "data_source" | "document";

export interface UploadCapability {
  extension: string;
  family: string;
  destination: UploadDestination;
  mimeTypes: string[];
  ambiguous: boolean;
}

export interface UploadCapabilities {
  maxFileSizeBytes: number;
  accepted: UploadCapability[];
}

export interface Classification {
  extension: string;
  family: string;
  destination: UploadDestination;
  confidence: string;
  reason: string;
  ambiguous: boolean;
  alternatives: UploadDestination[];
  fileName?: string;
  sizeBytes?: number;
  checksum?: string;
}

/**
 * Mirrors the server allowlist so the dropzone still renders sensible accepted
 * types if the capability call fails. The server remains authoritative — a file
 * accepted here can still be rejected by the classifier.
 */
export const FALLBACK_CAPABILITIES: UploadCapabilities = {
  maxFileSizeBytes: 100 * 1024 * 1024,
  accepted: [
    { extension: ".csv", family: "structured_tabular", destination: "data_source", mimeTypes: [], ambiguous: false },
    { extension: ".tsv", family: "structured_tabular", destination: "data_source", mimeTypes: [], ambiguous: false },
    { extension: ".xlsx", family: "structured_tabular", destination: "data_source", mimeTypes: [], ambiguous: false },
    { extension: ".xls", family: "structured_tabular", destination: "data_source", mimeTypes: [], ambiguous: false },
    { extension: ".json", family: "semi_structured", destination: "data_source", mimeTypes: [], ambiguous: true },
    { extension: ".xml", family: "semi_structured", destination: "data_source", mimeTypes: [], ambiguous: true },
    { extension: ".txt", family: "semi_structured", destination: "document", mimeTypes: [], ambiguous: true },
    { extension: ".md", family: "unstructured_document", destination: "document", mimeTypes: [], ambiguous: false },
    { extension: ".pdf", family: "unstructured_document", destination: "document", mimeTypes: [], ambiguous: false },
    { extension: ".docx", family: "unstructured_document", destination: "document", mimeTypes: [], ambiguous: false },
    { extension: ".pptx", family: "unstructured_document", destination: "document", mimeTypes: [], ambiguous: false },
  ],
};

export function extensionOf(fileName: string): string {
  const idx = fileName.lastIndexOf(".");
  return idx === -1 ? "" : fileName.slice(idx).toLowerCase();
}

export function acceptAttribute(capabilities: UploadCapabilities): string {
  return capabilities.accepted.map((c) => c.extension).join(",");
}

export function fetchCapabilities(): Promise<UploadCapabilities> {
  return apiClient
    .get<UploadCapabilities>("/api/uploads/capabilities")
    .catch(() => FALLBACK_CAPABILITIES);
}

/**
 * Classify a file server-side (extension + MIME + magic bytes). If the intake
 * endpoint is unreachable we fall back to the extension table so uploads keep
 * working; the ingestion endpoints validate again either way.
 */
export async function classifyFile(
  file: File,
  capabilities: UploadCapabilities,
): Promise<Classification> {
  try {
    return await apiClient.upload<Classification>("/api/uploads/classify", file);
  } catch (err) {
    const message = err instanceof Error ? err.message : "";
    // 422 means the server deliberately rejected the file — surface that.
    if (/unsupported|mismatch|macro|encrypted|too large|empty|bomb|corrupt/i.test(message)) {
      throw err;
    }
    const spec = capabilities.accepted.find((c) => c.extension === extensionOf(file.name));
    if (!spec) throw err;
    return {
      extension: spec.extension,
      family: spec.family,
      destination: spec.destination,
      confidence: "low",
      reason: "Classified from the file extension — the server will re-check on upload.",
      ambiguous: spec.ambiguous,
      alternatives: spec.ambiguous ? ["data_source", "document"] : [],
    };
  }
}

export function destinationLabel(destination: UploadDestination): string {
  return destination === "data_source" ? "Data Source" : "Document";
}

export function familyLabel(family: string): string {
  switch (family) {
    case "structured_tabular":
      return "Structured data";
    case "semi_structured":
      return "Semi-structured";
    case "unstructured_document":
      return "Document";
    default:
      return family;
  }
}
