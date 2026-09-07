"use client";

/**
 * Local-only design preview mocks.
 *
 * Only ever installed when NEXT_PUBLIC_MOCK_API=1 is set (see .env.local,
 * which is gitignored — this never runs in staging/production). It fakes a
 * logged-in session and intercepts a small, growing set of /api/* calls so
 * the real UI renders with plausible data even though no backend is running.
 *
 * Anything not listed in `routes` below falls through to the real fetch and
 * will fail/empty-state exactly as it does today. When you hit a new blocked
 * screen, that's the signal to add another entry here.
 */

const USER_META_KEY = "tablescope.user_meta";
const TOKEN_KEY = "tablescope.token";

function b64url(obj: unknown): string {
  const json = JSON.stringify(obj);
  const b64 =
    typeof window !== "undefined"
      ? window.btoa(json)
      : Buffer.from(json).toString("base64");
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function seedFakeSession(): void {
  if (typeof window === "undefined") return;
  if (!window.localStorage.getItem(USER_META_KEY)) {
    window.localStorage.setItem(
      USER_META_KEY,
      JSON.stringify({
        role: "tenant_admin",
        is_super_admin: true,
        tenant_id: 1,
        user_id: 1,
        tenant_slug: null,
      }),
    );
  }
  if (!window.localStorage.getItem(TOKEN_KEY)) {
    const fakeToken = `${b64url({ alg: "none" })}.${b64url({
      tenant_id: 1,
      user_id: 1,
    })}.mock`;
    window.localStorage.setItem(TOKEN_KEY, fakeToken);
  }
}

type MockRoute = {
  method: string;
  test: RegExp;
  respond: (url: string, body: unknown, form: FormData | null) => unknown;
};

let nextProjectId = 1000;
const createdProjects: Array<Record<string, unknown>> = [];

let nextUploadId = 5000;
let nextDataSourceId = 200;

// ── Workspaces ───────────────────────────────────────────────────────────
// The Workspace screen is unusable without these: listWorkspaces() throwing
// leaves the tab strip empty and every pane with nothing to render. Kept as a
// mutable in-memory list so create/rename/publish/delete/pin all behave for a
// whole session, rather than snapping back to a canned response.
// Shapes: lib/api/workspaces.ts (Workspace, WorkspaceCard).
const MOCK_USER_ID = 1;
let nextWorkspaceId = 10;
let nextWorkspaceCardId = 100;

function mockWorkspaceCard(
  resource_type: string,
  resource_id: string,
  label: string,
  position: number,
): Record<string, unknown> {
  return {
    id: nextWorkspaceCardId++,
    resource_type,
    resource_id,
    view_mode: "card",
    position,
    added_at: new Date().toISOString(),
    label,
  };
}

const mockWorkspaces: Array<Record<string, unknown>> = [
  {
    id: 1,
    tenant_id: 1,
    project_id: 1,
    owner_user_id: MOCK_USER_ID,
    name: "Cost review",
    visibility: "private",
    published_at: null,
    created_at: new Date(Date.now() - 864e5 * 3).toISOString(),
    updated_at: new Date().toISOString(),
    // Workspaces start empty on purpose: cards arrive by dragging a resource
    // in from the sidebar or via "+ Add card". Pre-seeding them made the
    // preview misrepresent the flow.
    cards: [],
  },
  {
    id: 2,
    tenant_id: 1,
    project_id: 1,
    owner_user_id: MOCK_USER_ID,
    name: "Vendor spend",
    visibility: "shared_project",
    published_at: new Date(Date.now() - 864e5).toISOString(),
    created_at: new Date(Date.now() - 864e5 * 6).toISOString(),
    updated_at: new Date().toISOString(),
    cards: [],
  },
];

function findMockWorkspace(url: string): Record<string, unknown> | undefined {
  const id = Number(/\/workspaces\/(\d+)/.exec(url)?.[1]);
  return mockWorkspaces.find((w) => w.id === id);
}

// ── Project tables + documents ───────────────────────────────────────────
// Backs the sidebar asset tree, the workspace "+ Add Files" catalog and the
// preview pane. Shapes: lib/ui/use-project-data/{saved-query,project-asset}.ts
function mockSavedQuery(
  id: number,
  name: string,
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    id,
    project_id: 1,
    owner_id: MOCK_USER_ID,
    name,
    description: null,
    left_datasource: null,
    right_datasource: null,
    join_type: null,
    left_column: null,
    right_column: null,
    sql_text: `SELECT * FROM ${name} LIMIT 100`,
    ai_generated: false,
    is_shared: false,
    run_count: 3,
    last_run_at: new Date().toISOString(),
    avg_runtime_ms: 240,
    is_archived: false,
    archived_at: null,
    created_at: new Date(Date.now() - 864e5 * 4).toISOString(),
    updated_at: new Date().toISOString(),
    owner_name: "Design Preview",
    origin: "manual",
    origin_label: "Manual",
    source_name: "OpenAI_CSV",
    has_outgoing_scope: false,
    outgoing_scope_count: 0,
    has_incoming_scope: false,
    incoming_scope_count: 0,
    has_active_scope: false,
    active_scope_count: 0,
    ...overrides,
  };
}

const projectQueries: Array<Record<string, unknown>> = [
  mockSavedQuery(3001, "openai_export_invoice"),
  mockSavedQuery(3002, "google_cloud_gemini"),
  mockSavedQuery(3003, "AI - Spend by Category", {
    ai_generated: true,
    origin: "ai",
    origin_label: "AI-generated",
  }),
];

const projectAssets: Array<Record<string, unknown>> = [
  {
    id: 9001,
    project_id: 1,
    asset_type: "document",
    source_type: "upload",
    title: "It 003 Cybersecurity Incident Report",
    description:
      "A cybersecurity incident report summarizing security findings and remediation for Simplicit Demo Company.",
    filename: "it_003_cybersecurity_incident_report.md",
    original_filename: "It 003 Cybersecurity Incident Report.md",
    content_type: "text/markdown",
    file_extension: "md",
    file_size_bytes: 462,
    visibility: "project",
    status: "ready",
    ai_status: "profiled",
    ai_summary:
      "This is a cybersecurity incident report that summarizes security findings and remediation for Simplicit Demo Company.",
    ai_metadata: {
      document_type: "report",
      business_domain: "IT Operations",
      tags: [{ name: "Cybersecurity", confidence: 0.95 }],
      entities: [{ type: "company", value: "Simplicit Demo Company" }],
      suggested_questions: [
        "What are the security findings and remediation steps for Simplicit Demo Company?",
      ],
    },
    created_by: MOCK_USER_ID,
    created_at: new Date(Date.now() - 864e5 * 10).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 9002,
    project_id: 1,
    asset_type: "document",
    source_type: "upload",
    title: "It 002 Q2 2026 Helpdesk Metrics Report",
    description:
      "Overview of incident volumes and resolution times for Q2, highlighting elevated access-category incidents.",
    filename: "it_002_q2_2026_helpdesk_metrics.md",
    original_filename: "It 002 Q2 2026 Helpdesk Metrics Report.md",
    content_type: "text/markdown",
    file_extension: "md",
    file_size_bytes: 488,
    visibility: "project",
    status: "ready",
    ai_status: "profiled",
    ai_summary:
      "Incident volumes and resolution times for Q2, recommending automation of onboarding access provisioning.",
    ai_metadata: {
      document_type: "report",
      business_domain: "IT Operations",
      tags: [{ name: "Helpdesk", confidence: 0.91 }],
      entities: [],
      suggested_questions: ["Which incident category grew fastest in Q2?"],
    },
    created_by: MOCK_USER_ID,
    created_at: new Date(Date.now() - 864e5 * 12).toISOString(),
    updated_at: new Date().toISOString(),
  },
];

// ── Chat ─────────────────────────────────────────────────────────────────
// Canned assistant replies so the chat pane is demonstrable offline. It echoes
// the grounding it was given, which also makes it obvious at a glance whether
// active_resources actually reached the request.
let nextConversationId = 700;
let nextTurnId = 7000;
let mockConversationId: number | null = null;

// Fake catalog for the project "Data Sources" area (All Data Sources tab +
// Connected Sources tab). See components/tablescope/project/data-sources-screen.tsx
// and .../data-source-builder/connected-sources-section.tsx for the real shapes.
const projectDataSources: Array<Record<string, unknown>> = [
  {
    fileName: "sales.csv",
    viewName: "sales_CSV",
    size: 184320,
    sourceType: "csv",
    dbType: null,
    connectorType: null,
    id: 101,
    fileMetaId: 101,
    ownerId: 1,
    ownerName: "Design Preview",
    columnTypes: [
      { name: "date", type: "date" },
      { name: "amount", type: "double" },
      { name: "region", type: "string" },
    ],
    archived: false,
    archivedAt: null,
    lifecycleKind: "file",
    lifecycleId: "sales_CSV",
  },
  {
    fileName: "Postgres orders",
    viewName: "orders_POSTGRES",
    size: null,
    sourceType: "database_table",
    dbType: "postgres",
    connectorType: null,
    id: 102,
    ownerId: 1,
    ownerName: "Design Preview",
    columnTypes: [
      { name: "id", type: "integer" },
      { name: "customer", type: "string" },
      { name: "total", type: "double" },
    ],
    archived: false,
    archivedAt: null,
    lifecycleKind: "database",
    lifecycleId: "102",
  },
  {
    fileName: "ServiceNow incidents",
    viewName: "incident_SERVICENOW",
    size: null,
    sourceType: "saas_object",
    dbType: "servicenow",
    connectorType: "servicenow",
    id: 103,
    ownerId: 1,
    ownerName: "Design Preview",
    columnTypes: [
      { name: "sys_id", type: "string" },
      { name: "short_description", type: "string" },
    ],
    archived: true,
    archivedAt: new Date(Date.now() - 86400000 * 3).toISOString(),
    lifecycleKind: "saas",
    lifecycleId: "103",
  },
];

const connectedSources: Array<Record<string, unknown>> = [
  {
    id: "conn-servicenow-dev",
    kind: "saas",
    source: "assigned",
    friendlyName: "Servicenow Dev",
    connectorType: "servicenow",
    displayLocation: "dev12345.service-now.com",
    status: "connected",
    enabled: true,
    allowedActions: ["create_data_source"],
    credentialId: 501,
    assignedBy: "Leonard",
  },
  {
    id: "conn-google-drive-leonard",
    kind: "saas",
    source: "owned",
    friendlyName: "Leonard Google Drive",
    connectorType: "google_drive",
    displayLocation: "leonard@vitruvity.local",
    status: "connected",
    enabled: true,
    allowedActions: ["create_data_source"],
    credentialId: 502,
  },
  {
    id: "conn-finance-fileshare",
    kind: "network_repository",
    source: "shared",
    friendlyName: "Finance Shared Drive",
    connectorType: "network_share",
    displayLocation: "\\\\fs01\\finance",
    status: "ok",
    enabled: true,
    allowedActions: ["browse"],
    connectionId: 7,
  },
];

const routes: MockRoute[] = [
  {
    method: "GET",
    test: /\/api\/auth\/me(\?.*)?$/,
    respond: () => ({
      user_id: 1,
      email: "design-preview@vitruvity.local",
      display_name: "Design Preview",
      first_name: "Design",
      last_name: "Preview",
      role: "tenant_admin",
      is_super_admin: true,
      tenant_id: 1,
      tenant_name: "Vitruvity",
      tenant_slug: null,
      avatar_url: null,
      company_logo_url: null,
      voice_input_enabled: true,
      chat_attachments_enabled: true,
      servicenow_itsm_dashboards_v2_enabled: true,
      permissions: ["*"],
    }),
  },
  {
    method: "GET",
    test: /\/api\/projects\/summaries/,
    respond: () => [
      {
        id: 1,
        name: "API Costs",
        is_shared: false,
        updated_at: new Date().toISOString(),
        document_count: 2,
        query_count: 0,
        dashboard_count: 0,
        action_count: 19,
        member_count: 1,
        data_source_count: 2,
        ai_status: "idle",
      },
      ...createdProjects,
    ],
  },
  {
    method: "POST",
    test: /\/api\/projects$/,
    respond: (_url, body) => {
      const id = nextProjectId++;
      const payload = (body ?? {}) as {
        name?: string;
        description?: string;
        is_shared?: boolean;
      };
      createdProjects.push({
        id,
        name: payload.name ?? "Untitled",
        is_shared: !!payload.is_shared,
        updated_at: new Date().toISOString(),
        document_count: 0,
        query_count: 0,
        dashboard_count: 0,
        action_count: 0,
        member_count: 1,
        data_source_count: 0,
        ai_status: "idle",
      });
      return { id };
    },
  },
  {
    // Workspace screen's table/document catalog — see
    // lib/ui/use-project-data/{metadata-catalog,catalog-table,catalog-field,catalog-document}.ts
    // for the real shape. Two fake tables with a few fields each, one fake
    // document — enough to render the workspace grid/cards without a
    // real data source connected. Add more/adjust as you design further.
    method: "GET",
    test: /\/api\/projects\/\d+\/metadata-catalog/,
    respond: () => ({
      tables: [
        {
          data_source_id: 1,
          name: "openai_export_invoice",
          source: "OpenAI_CSV",
          row_count: 5,
          field_count: 4,
          ai_summary: "Monthly OpenAI API token usage and cost by model.",
          ai_quality_summary: "No missing values detected.",
          status: "ready",
          last_synced: new Date().toISOString(),
          fields: [
            {
              name: "month",
              type: "date",
              ai_description: "Billing month",
              null_percent: 0,
              distinct_count: 5,
              sample_values: ["2024-01", "2024-02"],
              include_in_ai: true,
            },
            {
              name: "model",
              type: "string",
              ai_description: "OpenAI model name",
              null_percent: 0,
              distinct_count: 3,
              sample_values: ["gpt-4", "gpt-4o"],
              include_in_ai: true,
            },
            {
              name: "input_tokens",
              type: "integer",
              ai_description: "Input tokens consumed",
              null_percent: 0,
              distinct_count: 5,
              sample_values: [4120000, 5340000],
              include_in_ai: true,
            },
            {
              name: "cost_usd",
              type: "float",
              ai_description: "Cost in USD",
              null_percent: 0,
              distinct_count: 5,
              sample_values: [148.2, 195.6],
              include_in_ai: true,
            },
          ],
        },
        {
          data_source_id: 2,
          name: "google_cloud_gemini",
          source: "GCP_Billing_CSV",
          row_count: 4,
          field_count: 3,
          ai_summary: "Gemini API usage and cost by month.",
          ai_quality_summary: "No missing values detected.",
          status: "ready",
          last_synced: new Date().toISOString(),
          fields: [
            {
              name: "month",
              type: "date",
              ai_description: "Billing month",
              null_percent: 0,
              distinct_count: 4,
              sample_values: ["2024-01", "2024-02"],
              include_in_ai: true,
            },
            {
              name: "model",
              type: "string",
              ai_description: "Gemini model name",
              null_percent: 0,
              distinct_count: 2,
              sample_values: ["gemini-pro"],
              include_in_ai: true,
            },
            {
              name: "cost_usd",
              type: "float",
              ai_description: "Cost in USD",
              null_percent: 0,
              distinct_count: 4,
              sample_values: [49.0, 54.25],
              include_in_ai: true,
            },
          ],
        },
      ],
      documents: [
        {
          id: 1,
          title: "AI Budget Report.pdf",
          type: "pdf",
          status: "processed",
          clauses: 0,
          relationships: 3,
        },
      ],
    }),
  },
  {
    // Project "All Data Sources" tab — components/tablescope/project/data-sources-screen.tsx
    method: "GET",
    test: /\/api\/projects\/\d+\/datasources(\?|$)/,
    respond: () => projectDataSources,
  },
  {
    // Project "Connected Sources" tab — .../data-source-builder/connected-sources-section.tsx
    method: "GET",
    test: /\/api\/connected-sources/,
    respond: () => ({ items: connectedSources }),
  },
  {
    // Data Builder Step 1's "All Data Sources" sub-view — all-data-sources-panel.tsx
    method: "GET",
    test: /\/api\/projects\/datasources\/all/,
    respond: () => ({
      items: projectDataSources
        .filter((s) => !s.archived)
        .map((s) => ({
          id: String(s.lifecycleId),
          backendId: s.id,
          kind: s.lifecycleKind,
          name: s.fileName,
          viewName: s.viewName,
          sourceType: s.sourceType,
          connectorType: s.connectorType,
          dbType: s.dbType,
          columns: (s.columnTypes as unknown[] | undefined)?.length ?? 0,
          projectId: 1,
          projectName: "API Costs",
          ownerId: s.ownerId,
          ownerName: s.ownerName,
          createdAt: new Date().toISOString(),
        })),
      total: projectDataSources.filter((s) => !s.archived).length,
      next_cursor: null,
    }),
  },
  {
    // Data Builder Step 1 "existing sources to reuse" — kept empty so the
    // preview always exercises the fresh-upload path.
    method: "GET",
    test: /\/api\/projects\/my-datasources/,
    respond: () => [],
  },
  {
    // File dropped into the Data Builder's upload panel — ai-upload-dropzone.tsx.
    // The real endpoint is multipart; `form` carries the parsed FormData.
    method: "POST",
    test: /\/api\/data-sources\/upload\/analyze/,
    respond: (_url, _body, form) => {
      const file = form?.get("file") as File | undefined;
      const fileName = file?.name ?? "uploaded-file.csv";
      const ext = (fileName.split(".").pop() || "csv").toLowerCase();
      const jobId = `mock-job-${nextUploadId++}`;
      return {
        import_job_id: jobId,
        upload_session_id: jobId,
        acquisition_method: "local_upload",
        content_family: "structured_tabular",
        source_host: null,
        source_locator_redacted: null,
        sha256: null,
        file: {
          file_name: fileName,
          file_type: ext,
          file_size_bytes: file?.size ?? 20480,
          row_count: 128,
          column_count: 4,
          sheet_name: null,
        },
        fields: [
          {
            field_name: "id",
            detected_type: "integer",
            sample_values: [1, 2, 3],
          },
          {
            field_name: "name",
            detected_type: "string",
            sample_values: ["Alpha", "Beta"],
          },
          {
            field_name: "amount",
            detected_type: "float",
            sample_values: [12.5, 40.0],
          },
          {
            field_name: "created_at",
            detected_type: "date",
            sample_values: ["2026-08-01"],
          },
        ],
      };
    },
  },
  {
    // "Apply changes" on a freshly-uploaded file — data-source-builder.ts applyFileAddition.
    method: "POST",
    test: /\/api\/data-sources\/upload\/finalize/,
    respond: (_url, body) => {
      const b = (body ?? {}) as { display_name?: string };
      const base = (b.display_name ?? "data_source")
        .replace(/\.[^.]+$/, "")
        .replace(/\s+/g, "_");
      const dataSourceId = nextDataSourceId++;
      return { view_name: `${base}_CSV`, data_source_id: dataSourceId };
    },
  },
  {
    // Associating an already-created source with (another) project.
    method: "POST",
    test: /\/api\/projects\/\d+\/datasources\/add/,
    respond: (_url, body) => {
      const items = ((body ?? {}) as { items?: unknown[] }).items ?? [];
      return { status: "ok", added: items.length };
    },
  },

  // ── Workspaces ─────────────────────────────────────────────────────────
  {
    method: "GET",
    test: /\/api\/projects\/\d+\/workspaces$/,
    respond: () => mockWorkspaces,
  },
  {
    method: "GET",
    test: /\/api\/projects\/\d+\/workspaces\/\d+$/,
    respond: (url) => findMockWorkspace(url) ?? mockWorkspaces[0],
  },
  {
    method: "POST",
    test: /\/api\/projects\/\d+\/workspaces$/,
    respond: (_url, body) => {
      const payload = (body ?? {}) as {
        name?: string;
        cards?: { resource_type: string; resource_id: string }[];
      };
      const created = {
        id: nextWorkspaceId++,
        tenant_id: 1,
        project_id: 1,
        owner_user_id: MOCK_USER_ID,
        name: payload.name ?? "Untitled workspace",
        visibility: "private",
        published_at: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        cards: (payload.cards ?? []).map((c, i) =>
          mockWorkspaceCard(c.resource_type, c.resource_id, c.resource_id, i),
        ),
      };
      mockWorkspaces.push(created);
      return created;
    },
  },
  {
    // Rename and the full card-list replacement share one PATCH.
    method: "PATCH",
    test: /\/api\/projects\/\d+\/workspaces\/\d+$/,
    respond: (url, body) => {
      const workspace = findMockWorkspace(url);
      if (!workspace) return mockWorkspaces[0];
      const payload = (body ?? {}) as {
        name?: string;
        cards?: { resource_type: string; resource_id: string; view_mode?: string }[];
      };
      if (payload.name != null) workspace.name = payload.name;
      if (payload.cards) {
        // Reuse the existing card id where the resource is unchanged, so the
        // server-authoritative ids the screen swaps in stay stable across a
        // reorder -- matching how the real endpoint behaves.
        const existing = workspace.cards as Array<Record<string, unknown>>;
        workspace.cards = payload.cards.map((card, position) => {
          const prior = existing.find(
            (e) =>
              e.resource_type === card.resource_type &&
              e.resource_id === card.resource_id,
          );
          return {
            id: prior?.id ?? nextWorkspaceCardId++,
            resource_type: card.resource_type,
            resource_id: card.resource_id,
            view_mode: card.view_mode ?? "card",
            position,
            added_at: prior?.added_at ?? new Date().toISOString(),
            label: prior?.label ?? card.resource_id,
          };
        });
      }
      workspace.updated_at = new Date().toISOString();
      return workspace;
    },
  },
  {
    method: "POST",
    test: /\/api\/projects\/\d+\/workspaces\/\d+\/publish$/,
    respond: (url) => {
      const workspace = findMockWorkspace(url);
      if (!workspace) return mockWorkspaces[0];
      workspace.visibility = "shared_project";
      workspace.published_at = new Date().toISOString();
      return workspace;
    },
  },
  {
    method: "POST",
    test: /\/api\/projects\/\d+\/workspaces\/\d+\/unpublish$/,
    respond: (url) => {
      const workspace = findMockWorkspace(url);
      if (!workspace) return mockWorkspaces[0];
      workspace.visibility = "private";
      workspace.published_at = null;
      return workspace;
    },
  },
  {
    method: "DELETE",
    test: /\/api\/projects\/\d+\/workspaces\/\d+$/,
    respond: (url) => {
      const workspace = findMockWorkspace(url);
      if (workspace) mockWorkspaces.splice(mockWorkspaces.indexOf(workspace), 1);
      return { status: "deleted" };
    },
  },

  // ── Project tables + documents ─────────────────────────────────────────
  {
    method: "GET",
    test: /\/api\/projects\/\d+\/queries(\?|$)/,
    respond: (url) =>
      /include_archived=true/.test(url)
        ? projectQueries
        : projectQueries.filter((q) => !q.is_archived),
  },
  {
    method: "GET",
    test: /\/api\/projects\/\d+\/assets(\?|$)/,
    respond: () => projectAssets,
  },
  {
    method: "GET",
    test: /\/api\/projects\/\d+\/dashboards(\?|$)/,
    respond: () => [],
  },

  // ── Preview pane ───────────────────────────────────────────────────────
  {
    // Structured document preview -- see app/services/document_preview.py for
    // the real shape and the "kind" values the viewer switches on.
    method: "GET",
    test: /\/api\/projects\/\d+\/assets\/\d+\/preview/,
    respond: (url) => {
      const assetId = Number(/\/assets\/(\d+)\//.exec(url)?.[1]);
      const asset = projectAssets.find((a) => a.id === assetId);
      return {
        assetId,
        filename: asset?.filename ?? "document.md",
        contentType: "text/markdown",
        fileSizeBytes: asset?.file_size_bytes ?? 0,
        kind: "text",
        truncated: false,
        text:
          `# ${asset?.title ?? "Document"}\n\n` +
          `${asset?.ai_summary ?? ""}\n\n` +
          "## Findings\n\n" +
          "1. Access provisioning during onboarding is manual and slow.\n" +
          "2. Two incidents in the period traced back to stale credentials.\n" +
          "3. Mean time to resolution improved 18% quarter over quarter.\n\n" +
          "## Recommendation\n\n" +
          "Automate provisioning and expire credentials on role change.\n\n" +
          "_This preview is local mock content (lib/dev-mock/mock-api.ts)._\n",
      };
    },
  },
  {
    // Table / data-source result grids both post here.
    method: "POST",
    test: /\/api\/query\/datasource/,
    // Shape per QueryResult in detail-views/query-result.tsx: rows are objects
    // keyed by column name, not positional arrays.
    respond: () => ({
      columns: ["month", "vendor", "amount_usd"],
      rows: [
        { month: "2026-06", vendor: "OpenAI", amount_usd: 4820.55 },
        { month: "2026-06", vendor: "Google Cloud", amount_usd: 2140.0 },
        { month: "2026-07", vendor: "OpenAI", amount_usd: 5310.2 },
        { month: "2026-07", vendor: "Google Cloud", amount_usd: 1980.75 },
        { month: "2026-08", vendor: "OpenAI", amount_usd: 6102.4 },
      ],
      total: 5,
    }),
  },

  // ── Chat (canonical turns) ─────────────────────────────────────────────
  {
    method: "GET",
    test: /\/api\/conversational-analytics\/conversations(\?|$)/,
    respond: () => [],
  },
  {
    method: "POST",
    test: /\/api\/conversational-analytics\/canonical-turns$/,
    respond: (_url, body) => {
      const payload = (body ?? {}) as {
        surface?: string;
        project_id?: number;
        message?: string;
        active_resources?: { resource_type: string; resource_id: number }[];
      };
      const grounded = payload.active_resources ?? [];
      const created = mockConversationId == null;
      if (created) mockConversationId = nextConversationId++;
      return {
        conversation_id: mockConversationId,
        conversation_created: created,
        surface: payload.surface ?? "project_workspace",
        project_id: payload.project_id ?? 1,
        turn: {
          id: nextTurnId++,
          sequence: nextTurnId,
          user_message: payload.message ?? "",
          intent_type: "analysis",
          status: "complete",
          assistant_message: grounded.length
            ? `Mock reply. Grounded on ${grounded.length} workspace item(s): ` +
              `${grounded.map((r) => `${r.resource_type}#${r.resource_id}`).join(", ")}.`
            : "Mock reply. No workspace items are pinned, so this answer isn't grounded on anything.",
          sql: null,
          result: null,
          chart_config: null,
          explanation: null,
          error_code: null,
          matched_insight: null,
          attachments: [],
        },
      };
    },
  },
];

export function installDevMocks(): void {
  if (typeof window === "undefined") return;
  const w = window as unknown as { __devMocksInstalled?: boolean };
  if (w.__devMocksInstalled) return;
  w.__devMocksInstalled = true;

  seedFakeSession();

  const realFetch = window.fetch.bind(window);
  window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
    const method = (init?.method ?? "GET").toUpperCase();
    const route = routes.find((r) => r.method === method && r.test.test(url));
    if (route) {
      let body: unknown = undefined;
      let form: FormData | null = null;
      if (init?.body && typeof init.body === "string") {
        try {
          body = JSON.parse(init.body);
        } catch {
          /* not JSON, ignore */
        }
      } else if (init?.body instanceof FormData) {
        form = init.body;
      }
      console.log("[dev-mock]", method, url);
      return new Response(JSON.stringify(route.respond(url, body, form)), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return realFetch(input as RequestInfo, init);
  }) as typeof window.fetch;

  console.log(
    `[dev-mock] fetch interceptor active — ${routes.length} route(s) mocked. ` +
      `Unmocked /api calls still hit the real (likely absent) backend and will show empty/error states — that's expected, add a route here when you need one.`,
  );
}
