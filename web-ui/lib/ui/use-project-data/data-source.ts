"use client";

// ── Data sources ─────────────────────────────────────────────────────

export interface DataSource {
  fileName: string;
  viewName: string;
  size: number | null;
  sourceType: string;
  dbType: string | null;
  connectorType?: string | null;
  id?: number;
  fileMetaId?: number | null;
  ownerId?: number | null;
  ownerName?: string | null;
  columnTypes?: unknown[];
  aiMetadata?: Record<string, unknown> | null;
  archived?: boolean;
  archivedAt?: string | null;
  lifecycleKind: "file" | "database" | "saas";
  lifecycleId: string;
}