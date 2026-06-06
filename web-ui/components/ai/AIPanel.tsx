"use client";

import { useState, useCallback } from "react";
import { apiClient } from "@/lib/api-client";

/* ---------- Types ---------- */

type AIResponse = {
  answer?: string;
  sql?: string;
  explanation?: string;
  relationships?: Array<{
    left_table: string;
    left_column: string;
    right_table: string;
    right_column: string;
    confidence: number;
    reason: string;
  }>;
  suggestions?: Array<{
    title: string;
    widgets: Array<{ type: string; title: string; sql: string }>;
  }>;
  request_id?: string;
  model_used?: string;
  context_summary?: Record<string, number>;
  status?: string;
  error?: string;
};

type SaveResult = {
  action: string;
  status: string;
  query_id?: number;
  dashboard_id?: number;
  dashboard_name?: string;
  widgets_created?: number;
  queries_created?: number[];
  name?: string;
  sql_text?: string;
  model_used?: string;
};

type Props = {
  projectId: number;
  onQuerySaved?: () => void;
  onDashboardSaved?: () => void;
  onScopeCreated?: () => void;
};

/* ---------- Component ---------- */

export function AIPanel({ projectId, onQuerySaved, onDashboardSaved, onScopeCreated }: Props) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [activeFeature, setActiveFeature] = useState<
    "ask" | "sql" | "relationships" | "scopemap" | "dashboard"
  >("ask");
  const [creatingScope, setCreatingScope] = useState<string | null>(null);
  const [scopeCreated, setScopeCreated] = useState<Set<string>>(new Set());
  const [response, setResponse] = useState<AIResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saveResult, setSaveResult] = useState<SaveResult | null>(null);
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saveDescription, setSaveDescription] = useState("");
  const [dashboardPrompt, setDashboardPrompt] = useState("");
  const [history, setHistory] = useState<
    Array<{ question: string; answer: string; feature: string }>
  >([]);

  const callAI = useCallback(
    async (feature: string, body: Record<string, unknown>) => {
      setLoading(true);
      setError(null);
      setResponse(null);
      setSaveResult(null);
      try {
        const endpoints: Record<string, string> = {
          ask: "/api/ai/ask",
          sql: "/api/ai/query/generate",
          relationships: "/api/ai/project/relationships/generate",
          scopemap: "/api/ai/project/scope-map/generate",
          dashboard: "/api/ai/dashboard/suggest",
        };
        const resp = await apiClient.post<AIResponse>(
          endpoints[feature],
          body,
        );
        setResponse(resp);
        if (resp.answer || resp.sql) {
          setHistory((h) => [
            { question: question || feature, answer: resp.answer || resp.sql || "", feature },
            ...h.slice(0, 19),
          ]);
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "AI request failed";
        setError(msg);
      } finally {
        setLoading(false);
      }
    },
    [question],
  );

  const handleAsk = () => {
    if (!question.trim()) return;
    callAI(activeFeature, {
      project_id: projectId,
      question: question.trim(),
      prompt: question.trim(),
    });
  };

  const handleRelationships = () => {
    callAI("relationships", { project_id: projectId });
  };

  const handleScopeMap = () => {
    setScopeCreated(new Set());
    callAI("scopemap", { project_id: projectId });
  };

  const handleCreateScope = async (rel: NonNullable<AIResponse["relationships"]>[0]) => {
    const key = `${rel.left_table}.${rel.left_column}`;
    setCreatingScope(key);
    try {
      await apiClient.post("/api/scopes", {
        sourceTable: rel.left_table,
        sourceColumn: rel.left_column,
        targetTable: rel.right_table,
        targetColumn: rel.right_column,
      });
      setScopeCreated((prev) => new Set(prev).add(key));
      onScopeCreated?.();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create scope";
      setError(msg);
    } finally {
      setCreatingScope(null);
    }
  };

  const handleDashboardSuggest = () => {
    callAI("dashboard", { project_id: projectId });
  };

  /* ---------- Save Actions ---------- */

  const handleSaveQuery = async () => {
    if (!response?.sql || !saveName.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const result = await apiClient.post<SaveResult>("/api/ai/actions/save-query", {
        project_id: projectId,
        name: saveName.trim(),
        description: saveDescription.trim() || undefined,
        sql_text: response.sql,
      });
      setSaveResult(result);
      setShowSaveDialog(false);
      setSaveName("");
      setSaveDescription("");
      onQuerySaved?.();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save query";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleGenerateAndSaveQuery = async () => {
    if (!question.trim() || !saveName.trim()) return;
    setSaving(true);
    setError(null);
    setSaveResult(null);
    try {
      const result = await apiClient.post<SaveResult>("/api/ai/actions/generate-and-save-query", {
        project_id: projectId,
        prompt: question.trim(),
        name: saveName.trim(),
        description: saveDescription.trim() || undefined,
      });
      setSaveResult(result);
      setShowSaveDialog(false);
      setSaveName("");
      setSaveDescription("");
      onQuerySaved?.();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to generate and save query";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleGenerateAndSaveDashboard = async () => {
    setSaving(true);
    setError(null);
    setSaveResult(null);
    try {
      const result = await apiClient.post<SaveResult>("/api/ai/actions/generate-and-save-dashboard", {
        project_id: projectId,
        prompt: dashboardPrompt.trim() || undefined,
        name: saveName.trim() || undefined,
        description: saveDescription.trim() || undefined,
      });
      setSaveResult(result);
      setShowSaveDialog(false);
      setSaveName("");
      setSaveDescription("");
      setDashboardPrompt("");
      onDashboardSaved?.();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to generate and save dashboard";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleSaveDashboardFromSuggestion = async () => {
    if (!response?.suggestions?.length) return;
    setSaving(true);
    setError(null);
    setSaveResult(null);
    try {
      const result = await apiClient.post<SaveResult>("/api/ai/actions/generate-and-save-dashboard", {
        project_id: projectId,
        name: saveName.trim() || response.suggestions[0].title,
        description: saveDescription.trim() || undefined,
      });
      setSaveResult(result);
      setShowSaveDialog(false);
      setSaveName("");
      setSaveDescription("");
      onDashboardSaved?.();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save dashboard";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* AI boundary notice */}
      <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
        <div className="flex items-center gap-2 text-sm text-blue-800">
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span className="font-medium">AI Context: This project only</span>
        </div>
        <div className="mt-1 flex flex-wrap gap-3 text-xs text-blue-600">
          <span>Cross-project search: Off</span>
          <span>Tenant-wide memory: Off</span>
          <span>Private memory: On</span>
        </div>
      </div>

      {/* Feature tabs */}
      <div className="flex gap-1 rounded-lg bg-slate-100 p-1">
        {(
          [
            { key: "ask", label: "Ask AI" },
            { key: "sql", label: "Generate SQL" },
            { key: "relationships", label: "Relationships" },
            { key: "scopemap", label: "Scope Map" },
            { key: "dashboard", label: "Suggest Dashboard" },
          ] as const
        ).map((f) => (
          <button
            key={f.key}
            onClick={() => {
              setActiveFeature(f.key);
              setSaveResult(null);
            }}
            className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
              activeFeature === f.key
                ? "bg-white text-slate-900 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Input area for Ask / SQL */}
      {(activeFeature === "ask" || activeFeature === "sql") && (
        <div className="space-y-2">
          <div className="flex gap-2">
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAsk()}
              placeholder={
                activeFeature === "ask"
                  ? "Ask a question about this project..."
                  : "Describe the query you want (e.g., 'Show revenue by region')..."
              }
              className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              disabled={loading || saving}
            />
            <button
              onClick={handleAsk}
              disabled={loading || !question.trim()}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? "Thinking..." : activeFeature === "ask" ? "Ask" : "Generate"}
            </button>
          </div>

          {/* Generate & Save as Query shortcut */}
          {activeFeature === "sql" && question.trim() && (
            <button
              onClick={() => {
                setSaveName(`AI: ${question.trim().slice(0, 80)}`);
                setSaveDescription("");
                setShowSaveDialog(true);
              }}
              disabled={loading || saving}
              className="rounded-md border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
            >
              Generate &amp; Save as Query
            </button>
          )}
        </div>
      )}

      {/* Action buttons for non-text features */}
      {activeFeature === "relationships" && (
        <button
          onClick={handleRelationships}
          disabled={loading}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Analyzing..." : "Generate Relationship Map"}
        </button>
      )}

      {activeFeature === "scopemap" && (
        <button
          onClick={handleScopeMap}
          disabled={loading}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading ? "Analyzing..." : "Generate Scope Map"}
        </button>
      )}

      {activeFeature === "dashboard" && (
        <div className="space-y-2">
          <div className="flex gap-2">
            <input
              type="text"
              value={dashboardPrompt}
              onChange={(e) => setDashboardPrompt(e.target.value)}
              placeholder="Describe the dashboard you want (optional)..."
              className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              disabled={loading || saving}
            />
            <button
              onClick={handleDashboardSuggest}
              disabled={loading}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? "Generating..." : "Suggest"}
            </button>
          </div>
          <button
            onClick={() => {
              setSaveName("");
              setSaveDescription("");
              setShowSaveDialog(true);
            }}
            disabled={loading || saving}
            className="rounded-md border border-violet-300 bg-violet-50 px-3 py-1.5 text-xs font-medium text-violet-700 hover:bg-violet-100 disabled:opacity-50"
          >
            Generate &amp; Save Dashboard
          </button>
        </div>
      )}

      {/* Loading indicator */}
      {(loading || saving) && (
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          {saving ? "Saving..." : "Processing with tenant-isolated AI..."}
        </div>
      )}

      {/* Error display */}
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Save success */}
      {saveResult && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3">
          <div className="flex items-center gap-2 text-sm font-medium text-emerald-800">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            {saveResult.action === "save_query" && (
              <span>Query saved! (ID: {saveResult.query_id})</span>
            )}
            {saveResult.action === "generate_and_save_query" && (
              <span>Query generated &amp; saved! (ID: {saveResult.query_id})</span>
            )}
            {saveResult.action === "generate_and_save_dashboard" && (
              <span>
                Dashboard &quot;{saveResult.dashboard_name}&quot; created with {saveResult.widgets_created} widget(s)
                and {saveResult.queries_created?.length ?? 0} query(ies)
              </span>
            )}
          </div>
          {saveResult.sql_text && (
            <pre className="mt-2 overflow-x-auto rounded bg-slate-900 p-2 text-xs text-green-400">
              {saveResult.sql_text}
            </pre>
          )}
          <p className="mt-1 text-xs text-emerald-600">
            {saveResult.query_id && "View in the Queries tab."}
            {saveResult.dashboard_id && "View in the Dashboards tab."}
          </p>
        </div>
      )}

      {/* Response display */}
      {response && !error && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          {/* Ask response */}
          {response.answer && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-900">AI Response</h3>
              <p className="whitespace-pre-wrap text-sm text-slate-700">{response.answer}</p>
            </div>
          )}

          {/* SQL response */}
          {response.sql && (
            <div>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-900">Generated SQL</h3>
                <button
                  onClick={() => {
                    setSaveName(`AI: ${question.trim().slice(0, 80)}`);
                    setSaveDescription(response.explanation || "");
                    setShowSaveDialog(true);
                  }}
                  disabled={saving}
                  className="rounded-md bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                >
                  Save as Query
                </button>
              </div>
              <pre className="overflow-x-auto rounded-md bg-slate-900 p-3 text-sm text-green-400">
                {response.sql}
              </pre>
              {response.explanation && (
                <p className="mt-2 text-sm text-slate-600">{response.explanation}</p>
              )}
            </div>
          )}

          {/* Relationships response */}
          {response.relationships && response.relationships.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-900">
                Suggested Relationships ({response.relationships.length})
              </h3>
              <div className="space-y-2">
                {response.relationships.map((rel, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-2 rounded-md border border-slate-100 bg-slate-50 p-2 text-sm"
                  >
                    <span className="font-mono text-blue-700">
                      {rel.left_table}.{rel.left_column}
                    </span>
                    <span className="text-slate-400">&rarr;</span>
                    <span className="font-mono text-blue-700">
                      {rel.right_table}.{rel.right_column}
                    </span>
                    <span className="ml-auto rounded bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                      {Math.round(rel.confidence * 100)}%
                    </span>
                    <span className="text-xs text-slate-500">{rel.reason}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Scope Map response */}
          {activeFeature === "scopemap" && response.relationships && response.relationships.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-900">
                AI Scope Map ({response.relationships.length} suggestions)
              </h3>
              <p className="mb-3 text-xs text-slate-500">
                Click &quot;Create Scope&quot; to add a drill-down scope. Source column clicks will navigate to the target table filtered by that value.
              </p>
              <div className="space-y-2">
                {response.relationships.map((rel, i) => {
                  const key = `${rel.left_table}.${rel.left_column}`;
                  const alreadyCreated = scopeCreated.has(key) || (rel as Record<string, unknown>).scope_exists === true;
                  const isCreating = creatingScope === key;
                  return (
                    <div
                      key={i}
                      className={`flex items-center gap-2 rounded-md border p-3 text-sm ${
                        alreadyCreated
                          ? "border-green-200 bg-green-50"
                          : "border-slate-200 bg-white"
                      }`}
                    >
                      <div className="flex flex-1 flex-wrap items-center gap-2">
                        <span className="rounded bg-blue-100 px-2 py-1 font-mono text-xs text-blue-800">
                          {rel.left_table}
                        </span>
                        <span className="font-mono text-xs text-slate-600">.{rel.left_column}</span>
                        <svg className="h-4 w-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
                        </svg>
                        <span className="rounded bg-indigo-100 px-2 py-1 font-mono text-xs text-indigo-800">
                          {rel.right_table}
                        </span>
                        <span className="font-mono text-xs text-slate-600">.{rel.right_column}</span>
                        <span className="rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-medium text-green-700">
                          {Math.round(rel.confidence * 100)}%
                        </span>
                      </div>
                      <span className="hidden text-xs text-slate-400 sm:inline">{rel.reason}</span>
                      {alreadyCreated ? (
                        <span className="whitespace-nowrap rounded bg-green-200 px-3 py-1.5 text-xs font-medium text-green-800">
                          Scope Created
                        </span>
                      ) : (
                        <button
                          onClick={() => handleCreateScope(rel)}
                          disabled={isCreating || !!creatingScope}
                          className="whitespace-nowrap rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                        >
                          {isCreating ? "Creating..." : "Create Scope"}
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
              {scopeCreated.size > 0 && (
                <div className="mt-3 rounded-md border border-green-200 bg-green-50 p-2 text-xs text-green-700">
                  {scopeCreated.size} scope(s) created. View them on the Scopes page.
                </div>
              )}
            </div>
          )}

          {/* Dashboard suggestions */}
          {response.suggestions && response.suggestions.length > 0 && (
            <div>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-900">
                  Dashboard Suggestions
                </h3>
                <button
                  onClick={() => {
                    setSaveName(response.suggestions?.[0]?.title ?? "AI Dashboard");
                    setSaveDescription("");
                    setShowSaveDialog(true);
                  }}
                  disabled={saving}
                  className="rounded-md bg-violet-600 px-3 py-1 text-xs font-medium text-white hover:bg-violet-700 disabled:opacity-50"
                >
                  Save as Dashboard
                </button>
              </div>
              {response.suggestions.map((sug, i) => (
                <div key={i} className="mb-3 rounded-md border border-slate-100 p-3">
                  <h4 className="mb-2 font-medium text-slate-800">{sug.title}</h4>
                  <div className="space-y-1">
                    {sug.widgets.map((w, j) => (
                      <div key={j} className="flex items-center gap-2 text-sm">
                        <span className="rounded bg-violet-100 px-1.5 py-0.5 text-xs font-medium text-violet-700">
                          {w.type}
                        </span>
                        <span className="text-slate-700">{w.title}</span>
                        {w.sql && (
                          <span className="ml-auto truncate text-[10px] font-mono text-slate-400" title={w.sql}>
                            {w.sql.slice(0, 60)}...
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Context summary */}
          {response.context_summary && (
            <div className="mt-3 flex gap-3 border-t border-slate-100 pt-3 text-xs text-slate-400">
              {response.request_id && <span>Request: {response.request_id.slice(0, 8)}...</span>}
              {response.model_used && <span>Model: {response.model_used}</span>}
              {Object.entries(response.context_summary).map(([k, v]) => (
                <span key={k}>
                  {k}: {v}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Save Dialog (modal overlay) */}
      {showSaveDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h2 className="mb-4 text-lg font-semibold text-slate-900">
              {activeFeature === "dashboard" && !response?.sql
                ? "Generate & Save Dashboard"
                : response?.sql
                  ? "Save Query"
                  : "Generate & Save Query"}
            </h2>

            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">Name</label>
                <input
                  type="text"
                  value={saveName}
                  onChange={(e) => setSaveName(e.target.value)}
                  placeholder={
                    activeFeature === "dashboard"
                      ? "Dashboard name..."
                      : "Query name..."
                  }
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">
                  Description (optional)
                </label>
                <textarea
                  value={saveDescription}
                  onChange={(e) => setSaveDescription(e.target.value)}
                  placeholder="Brief description..."
                  rows={2}
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              {/* Dashboard prompt if generating fresh */}
              {activeFeature === "dashboard" && !response?.suggestions?.length && (
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">
                    Dashboard prompt (optional)
                  </label>
                  <input
                    type="text"
                    value={dashboardPrompt}
                    onChange={(e) => setDashboardPrompt(e.target.value)}
                    placeholder="e.g., 'Create a sales performance dashboard'"
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
              )}

              {/* Show SQL preview for query save */}
              {response?.sql && (
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">SQL</label>
                  <pre className="max-h-32 overflow-auto rounded bg-slate-900 p-2 text-xs text-green-400">
                    {response.sql}
                  </pre>
                </div>
              )}
            </div>

            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowSaveDialog(false);
                  setSaveName("");
                  setSaveDescription("");
                }}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (activeFeature === "dashboard") {
                    if (response?.suggestions?.length) {
                      handleSaveDashboardFromSuggestion();
                    } else {
                      handleGenerateAndSaveDashboard();
                    }
                  } else if (response?.sql) {
                    handleSaveQuery();
                  } else {
                    handleGenerateAndSaveQuery();
                  }
                }}
                disabled={saving || (!response?.sql && activeFeature !== "dashboard" && !saveName.trim())}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? "Saving..." : activeFeature === "dashboard" ? "Create Dashboard" : "Save Query"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-500">Recent AI History</h3>
          <div className="space-y-2">
            {history.map((item, i) => (
              <div key={i} className="rounded-md border border-slate-100 bg-slate-50 p-2 text-sm">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                    {item.feature}
                  </span>
                  <span className="font-medium text-slate-700">{item.question}</span>
                </div>
                <p className="mt-1 truncate text-xs text-slate-500">{item.answer}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
