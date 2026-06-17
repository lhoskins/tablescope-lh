import { apiClient } from "@/lib/api-client";

export type ReferenceTier = "industry" | "company" | "project";

export interface ReferenceDocument {
  id: number;
  tier: ReferenceTier;
  tenantId: number | null;
  projectId: number | null;
  title: string;
  issuingBody: string | null;
  domainTag: string | null;
  applicabilityTag: string | null;
  sourceUrl: string | null;
  effectiveDate: string | null;
  versionLabel: string | null;
  status: string;
  hasFile: boolean;
  fileType: string | null;
  fileSizeBytes: number | null;
  originalFilename: string | null;
  aiSummary: string | null;
  aiErrorMessage: string | null;
  inheritDefault: boolean;
  createdAt: string | null;
  // present on project-library responses
  tierBadge?: string;
  assignmentId?: number;
  reasoning?: string | null;
}

export interface ReferenceMeta {
  domains: string[];
  issuers: string[];
  applicabilityTags: string[];
  permissions: {
    industryWrite: boolean;
    companyWrite: boolean;
  };
}

export interface ProjectLibrary {
  inherited: ReferenceDocument[];
  suggested: ReferenceDocument[];
  projectUnique: ReferenceDocument[];
  summary: {
    inherited: number;
    suggested: number;
    suggestedPending: number;
    projectUnique: number;
    totalActive: number;
  };
}

export interface BulkImportRow {
  rowNumber: number;
  title: string;
  issuingBody?: string | null;
  domainTag: string | null;
  applicabilityTag?: string | null;
  sourceUrl: string;
  versionLabel?: string | null;
  fetchMethodHint?: string | null;
  status: string;
  failureReason?: string | null;
  warnings: string[];
  willUpdateExistingId?: number | null;
  id?: number;
}

export interface BulkValidateResult {
  batchId: number;
  totalRows: number;
  readyCount: number;
  skippedCount: number;
  errorCount: number;
  warningCount: number;
  rows: BulkImportRow[];
}

const BASE = "/api/reference-library";

export const referenceLibraryApi = {
  meta: () => apiClient.get<ReferenceMeta>(`${BASE}/meta`),

  listDocuments: (params: {
    tier: ReferenceTier;
    projectId?: number;
    domain?: string;
    search?: string;
  }) => {
    const q = new URLSearchParams({ tier: params.tier });
    if (params.projectId != null) q.set("project_id", String(params.projectId));
    if (params.domain) q.set("domain", params.domain);
    if (params.search) q.set("search", params.search);
    return apiClient.get<{ documents: ReferenceDocument[] }>(
      `${BASE}/documents?${q.toString()}`,
    );
  },

  createDocument: (form: FormData) =>
    apiClient.postForm<ReferenceDocument>(`${BASE}/documents`, form),

  updateDocument: (id: number, body: Record<string, unknown>) =>
    apiClient.patch<ReferenceDocument>(`${BASE}/documents/${id}`, body),

  reprocess: (id: number) =>
    apiClient.post<{ status: string }>(`${BASE}/documents/${id}/process`, {}),

  companyLibrary: () =>
    apiClient.get<{
      documents: ReferenceDocument[];
      stats: { total: number; byDomain: Record<string, number>; inheritByDefault: number };
    }>(`${BASE}/company`),

  projectLibrary: (projectId: number) =>
    apiClient.get<ProjectLibrary>(`${BASE}/project/${projectId}`),

  approveSuggestion: (assignmentId: number) =>
    apiClient.post(`${BASE}/assignments/${assignmentId}/approve`, {}),

  dismissSuggestion: (assignmentId: number) =>
    apiClient.post(`${BASE}/assignments/${assignmentId}/dismiss`, {}),

  removeInherited: (projectId: number, documentId: number) =>
    apiClient.post(`${BASE}/project/${projectId}/documents/${documentId}/remove`, {}),

  readdInherited: (projectId: number, documentId: number) =>
    apiClient.post(`${BASE}/project/${projectId}/documents/${documentId}/add`, {}),

  generateSuggestions: (projectId: number) =>
    apiClient.post<{ created: number }>(
      `${BASE}/suggestions/generate?project_id=${projectId}`,
      {},
    ),

  createRequest: (body: {
    title: string;
    issuing_body?: string;
    source_url?: string;
    domain_tag?: string;
    justification?: string;
  }) => apiClient.post<{ success: boolean; id: number }>(`${BASE}/requests`, body),

  // ── bulk import ──
  bulkValidate: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiClient.postForm<BulkValidateResult>(`${BASE}/bulk-import/validate`, form);
  },

  bulkRun: (batchId: number) =>
    apiClient.post<{ status: string; batchId: number }>(
      `${BASE}/bulk-import/${batchId}/run`,
      {},
    ),

  bulkRetry: (batchId: number) =>
    apiClient.post<{ status: string; batchId: number }>(
      `${BASE}/bulk-import/${batchId}/retry`,
      {},
    ),

  bulkStream: (batchId: number) =>
    apiClient.stream(`${BASE}/bulk-import/${batchId}/stream`),

  downloadFailures: async (batchId: number) => {
    const res = await apiClient.stream(`${BASE}/bulk-import/${batchId}/failures.csv`, {
      headers: { Accept: "text/csv" },
    });
    if (!res.ok) throw new Error(`Download failed: ${res.status}`);
    return res.blob();
  },
};
