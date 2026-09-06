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
