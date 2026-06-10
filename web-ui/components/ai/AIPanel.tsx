"use client";

import { useState, useCallback } from "react";
import { apiClient } from "@/lib/api-client";

/* ---------- Helpers ---------- */

/** Convert an AI prompt into a short, clean title (mirrors backend _shorten_ai_name). */
function shortenAiName(prompt: string): string {
  let s = prompt.trim().replace(/\.$/, "");
  s = s.replace(
    /^(?:generate|create|show|build|make|give me|write|produce)\s+(?:a\s+)?(?:query|dashboard|report|chart|table|widget|view)?\s*(?:showing|with|for|of|that shows|to show|displaying)?\s*/i,
    "",
  ).trim();
  if (/^SELECT\b/i.test(s)) s = "Custom SQL Query";
  if (!s) s = "Query";
  const small = new Set(["by", "of", "and", "the", "in", "for", "with", "to", "a"]);
  s = s
    .split(/\s+/)
    .map((w, i) => (i > 0 && small.has(w.toLowerCase())) ? w.toLowerCase() : w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
  return `AI - ${s}`;
}

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
    source_query_id?: number;
    target_query_id?: number;
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

type QuerySuggestion = {
  title: string;
  description: string;
  sql?: string;
};

type DashboardSuggestion = {
  title: string;
  description: string;
  widgets?: Array<{ type: string; title: string; sql: string }>;
};

type InsightItem = {
  title: string;
  description: string;
  action?: string;
  action_type?: "create" | "run";
  action_params?: Record<string, unknown>;
};

type SuggestionResponse = {
  query_suggestions?: QuerySuggestion[];
  dashboard_suggestions?: DashboardSuggestion[];
  insights?: InsightItem[];
  answer?: string;
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

export function AIPanel({ projectId, onQuerySaved, onDashboardSaved }: Props) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [activeFeature, setActiveFeature] = useState<"ask" | "suggestions">("ask");
  const [response, setResponse] = useState<AIResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saveResult, setSaveResult] = useState<SaveResult | null>(null);
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saveDescription, setSaveDescription] = useState("");
  const [history, setHistory] = useState<
    Array<{ question: string; answer: string; feature: string }>
  >([]);

  // Suggestion state
  const [suggestionType, setSuggestionType] = useState<"queries" | "dashboards" | "insights" | null>(null);
  const [querySuggestions, setQuerySuggestions] = useState<QuerySuggestion[]>([]);
  const [dashboardSuggestions, setDashboardSuggestions] = useState<DashboardSuggestion[]>([]);
  const [insights, setInsights] = useState<InsightItem[]>([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [creatingSuggestion, setCreatingSuggestion] = useState<number | null>(null);
  const [runningInsight, setRunningInsight] = useState<number | null>(null);

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
    callAI("ask", {
      project_id: projectId,
      question: question.trim(),
      prompt: question.trim(),
    });
  };

  /* ---------- Suggestion Actions ---------- */

  const fetchQuerySuggestions = async () => {
    setSuggestionType("queries");
    setLoadingSuggestions(true);
    setError(null);
    setQuerySuggestions([]);
    try {
      const resp = await apiClient.post<SuggestionResponse>("/api/ai/ask", {
        project_id: projectId,
        question: "Suggest 5 useful SQL queries I could create for this project's data sources. For each suggestion provide a title, description, and the actual SQL query. Return your answer as JSON with a 'query_suggestions' array where each item has 'title', 'description', and 'sql' fields.",
      });
      if (resp.answer) {
        try {
          const parsed = JSON.parse(resp.answer);
          setQuerySuggestions(parsed.query_suggestions || []);
        } catch {
          // Try to extract JSON from markdown code blocks
          const jsonMatch = resp.answer.match(/```(?:json)?\s*([\s\S]*?)```/);
          if (jsonMatch) {
            try {
              const parsed = JSON.parse(jsonMatch[1]);
              setQuerySuggestions(parsed.query_suggestions || parsed || []);
            } catch {
              setQuerySuggestions([{ title: "AI Response", description: resp.answer }]);
            }
          } else {
            setQuerySuggestions([{ title: "AI Response", description: resp.answer }]);
          }
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to get query suggestions");
    } finally {
      setLoadingSuggestions(false);
    }
  };

  const fetchDashboardSuggestions = async () => {
    setSuggestionType("dashboards");
    setLoadingSuggestions(true);
    setError(null);
    setDashboardSuggestions([]);
    try {
      const resp = await apiClient.post<SuggestionResponse>("/api/ai/ask", {
        project_id: projectId,
        question: "Suggest 3 useful dashboards I could create for this project's data sources. For each suggestion provide a title and description of what the dashboard would show. Return your answer as JSON with a 'dashboard_suggestions' array where each item has 'title' and 'description' fields.",
      });
      if (resp.answer) {
        try {
          const parsed = JSON.parse(resp.answer);
          setDashboardSuggestions(parsed.dashboard_suggestions || []);
        } catch {
          const jsonMatch = resp.answer.match(/```(?:json)?\s*([\s\S]*?)```/);
          if (jsonMatch) {
            try {
              const parsed = JSON.parse(jsonMatch[1]);
              setDashboardSuggestions(parsed.dashboard_suggestions || parsed || []);
            } catch {
              setDashboardSuggestions([{ title: "AI Response", description: resp.answer }]);
            }
          } else {
            setDashboardSuggestions([{ title: "AI Response", description: resp.answer }]);
          }
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to get dashboard suggestions");
    } finally {
      setLoadingSuggestions(false);
    }
  };

  const fetchInsights = async () => {
    setSuggestionType("insights");
    setLoadingSuggestions(true);
    setError(null);
    setInsights([]);
    try {
      const resp = await apiClient.post<SuggestionResponse>("/api/ai/ask", {
        project_id: projectId,
        question: "Analyze this project's data sources and provide insights and opportunities. For each insight, provide a title, description, and optionally an action the user can take (such as creating a query or running an analysis). Return your answer as JSON with an 'insights' array where each item has 'title', 'description', and optionally 'action' (text description of what to do), 'action_type' ('create' or 'run'), and 'action_params' (object with any parameters needed).",
      });
      if (resp.answer) {
        try {
          const parsed = JSON.parse(resp.answer);
          setInsights(parsed.insights || []);
        } catch {
          const jsonMatch = resp.answer.match(/```(?:json)?\s*([\s\S]*?)```/);
          if (jsonMatch) {
            try {
              const parsed = JSON.parse(jsonMatch[1]);
              setInsights(parsed.insights || parsed || []);
            } catch {
              setInsights([{ title: "AI Insight", description: resp.answer }]);
            }
          } else {
            setInsights([{ title: "AI Insight", description: resp.answer }]);
          }
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to get insights");
    } finally {
      setLoadingSuggestions(false);
    }
  };

  const handleCreateQueryFromSuggestion = async (suggestion: QuerySuggestion, index: number) => {
    if (!suggestion.sql) return;
    setCreatingSuggestion(index);
    setError(null);
    try {
      const result = await apiClient.post<SaveResult>("/api/ai/actions/save-query", {
        project_id: projectId,
        name: shortenAiName(suggestion.title),
        description: suggestion.description,
        sql_text: suggestion.sql,
      });
      setSaveResult(result);
      onQuerySaved?.();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create query");
    } finally {
      setCreatingSuggestion(null);
    }
  };

  const handleCreateDashboardFromSuggestion = async (suggestion: DashboardSuggestion, index: number) => {
    setCreatingSuggestion(index);
    setError(null);
    try {
      const result = await apiClient.post<SaveResult>("/api/ai/actions/generate-and-save-dashboard", {
        project_id: projectId,
        prompt: suggestion.description,
        name: shortenAiName(suggestion.title),
        description: suggestion.description,
      });
      setSaveResult(result);
      onDashboardSaved?.();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create dashboard");
    } finally {
      setCreatingSuggestion(null);
    }
  };

  const handleRunInsightAction = async (insight: InsightItem, index: number) => {
    if (!insight.action) return;
    setRunningInsight(index);
    setError(null);
    try {
      if (insight.action_type === "create") {
        // Create a query from the insight's action
        const result = await apiClient.post<SaveResult>("/api/ai/actions/generate-and-save-query", {
          project_id: projectId,
          prompt: insight.action,
          name: shortenAiName(insight.title),
        });
        setSaveResult(result);
        onQuerySaved?.();
      } else {
        // Run/execute the action as an AI question
        const resp = await apiClient.post<AIResponse>("/api/ai/ask", {
          project_id: projectId,
          question: insight.action,
        });
        setResponse(resp);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to execute action");
    } finally {
      setRunningInsight(null);
    }
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

      {/* Feature tabs — only Ask AI and Make Suggestions */}
      <div className="flex gap-1 rounded-lg bg-slate-100 p-1">
        {(
          [
            { key: "ask", label: "Ask AI" },
            { key: "suggestions", label: "Make Suggestions" },
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

      {/* Ask AI input */}
      {activeFeature === "ask" && (
        <div className="space-y-2">
          <div className="flex gap-2">
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAsk()}
              placeholder="Ask a question about this project..."
              className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              disabled={loading || saving}
            />
            <button
              onClick={handleAsk}
              disabled={loading || !question.trim()}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? "Thinking..." : "Ask"}
            </button>
          </div>

          {question.trim() && (
            <button
              onClick={() => {
                setSaveName(shortenAiName(question.trim()));
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

      {/* Make Suggestions tab */}
      {activeFeature === "suggestions" && (
        <div className="space-y-4">
          {/* Three action buttons */}
          <div className="grid grid-cols-3 gap-3">
            <button
              onClick={fetchQuerySuggestions}
              disabled={loadingSuggestions}
              className={`rounded-lg border-2 p-4 text-left transition-colors ${
                suggestionType === "queries"
                  ? "border-blue-500 bg-blue-50"
                  : "border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50/50"
              }`}
            >
              <div className="mb-1 text-sm font-semibold text-slate-900">New Query Suggestions</div>
              <p className="text-xs text-slate-500">AI suggests useful queries for your data</p>
            </button>
            <button
              onClick={fetchDashboardSuggestions}
              disabled={loadingSuggestions}
              className={`rounded-lg border-2 p-4 text-left transition-colors ${
                suggestionType === "dashboards"
                  ? "border-violet-500 bg-violet-50"
                  : "border-slate-200 bg-white hover:border-violet-300 hover:bg-violet-50/50"
              }`}
            >
              <div className="mb-1 text-sm font-semibold text-slate-900">New Dashboard Suggestions</div>
              <p className="text-xs text-slate-500">AI suggests dashboards to visualize your data</p>
            </button>
            <button
              onClick={fetchInsights}
              disabled={loadingSuggestions}
              className={`rounded-lg border-2 p-4 text-left transition-colors ${
                suggestionType === "insights"
                  ? "border-amber-500 bg-amber-50"
                  : "border-slate-200 bg-white hover:border-amber-300 hover:bg-amber-50/50"
              }`}
            >
              <div className="mb-1 text-sm font-semibold text-slate-900">Insights &amp; Opportunities</div>
              <p className="text-xs text-slate-500">AI analyzes your data for actionable insights</p>
            </button>
          </div>

          {/* Loading */}
          {loadingSuggestions && (
            <div className="flex items-center gap-2 py-4 text-sm text-slate-500">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
              Generating suggestions...
            </div>
          )}

          {/* Query Suggestions */}
          {suggestionType === "queries" && querySuggestions.length > 0 && !loadingSuggestions && (
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-slate-900">Query Suggestions</h3>
              {querySuggestions.map((sug, i) => (
                <div key={i} className="flex items-start gap-3 rounded-lg border border-slate-200 bg-white p-3">
                  <div className="min-w-0 flex-1">
                    <h4 className="text-sm font-medium text-slate-900">{sug.title}</h4>
                    <p className="mt-0.5 text-xs text-slate-500">{sug.description}</p>
                    {sug.sql && (
                      <pre className="mt-2 max-h-20 overflow-auto rounded bg-slate-900 p-2 text-[10px] text-green-400">
                        {sug.sql}
                      </pre>
                    )}
                  </div>
                  {sug.sql && (
                    <button
                      onClick={() => handleCreateQueryFromSuggestion(sug, i)}
                      disabled={creatingSuggestion === i}
                      className="shrink-0 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                    >
                      {creatingSuggestion === i ? "Creating..." : "Create"}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Dashboard Suggestions */}
          {suggestionType === "dashboards" && dashboardSuggestions.length > 0 && !loadingSuggestions && (
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-slate-900">Dashboard Suggestions</h3>
              {dashboardSuggestions.map((sug, i) => (
                <div key={i} className="flex items-start gap-3 rounded-lg border border-slate-200 bg-white p-3">
                  <div className="min-w-0 flex-1">
                    <h4 className="text-sm font-medium text-slate-900">{sug.title}</h4>
                    <p className="mt-0.5 text-xs text-slate-500">{sug.description}</p>
                  </div>
                  <button
                    onClick={() => handleCreateDashboardFromSuggestion(sug, i)}
                    disabled={creatingSuggestion === i}
                    className="shrink-0 rounded-md bg-violet-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-violet-700 disabled:opacity-50"
                  >
                    {creatingSuggestion === i ? "Creating..." : "Create"}
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Insights & Opportunities */}
          {suggestionType === "insights" && insights.length > 0 && !loadingSuggestions && (
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-slate-900">Insights &amp; Opportunities</h3>
              {insights.map((insight, i) => (
                <div key={i} className="flex items-start gap-3 rounded-lg border border-slate-200 bg-white p-3">
                  <div className="min-w-0 flex-1">
                    <h4 className="text-sm font-medium text-slate-900">{insight.title}</h4>
                    <p className="mt-0.5 text-xs text-slate-500">{insight.description}</p>
                    {insight.action && (
                      <p className="mt-1 text-xs text-blue-600">
                        Action: {insight.action}
                      </p>
                    )}
                  </div>
                  {insight.action && (
                    <button
                      onClick={() => handleRunInsightAction(insight, i)}
                      disabled={runningInsight === i}
                      className={`shrink-0 rounded-md px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 ${
                        insight.action_type === "create"
                          ? "bg-emerald-600 hover:bg-emerald-700"
                          : "bg-amber-600 hover:bg-amber-700"
                      }`}
                    >
                      {runningInsight === i
                        ? "Running..."
                        : insight.action_type === "create"
                          ? "Create"
                          : "Run"}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
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
              <span>Query saved: {saveResult.name} (ID: {saveResult.query_id})</span>
            )}
            {saveResult.action === "generate_and_save_query" && (
              <span>Query generated &amp; saved: {saveResult.name} (ID: {saveResult.query_id})</span>
            )}
            {saveResult.action === "generate_and_save_dashboard" && (
              <span>
                Dashboard &quot;{saveResult.dashboard_name}&quot; created with {saveResult.widgets_created} widget(s)
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-emerald-600">
            {saveResult.query_id && "View in the Queries tab."}
            {saveResult.dashboard_id && "View in the Dashboards tab."}
          </p>
        </div>
      )}

      {/* Response display (Ask AI responses) */}
      {response && !error && activeFeature === "ask" && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          {response.answer && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-900">AI Response</h3>
              <p className="whitespace-pre-wrap text-sm text-slate-700">{response.answer}</p>
            </div>
          )}

          {response.sql && (
            <div>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-900">Generated SQL</h3>
                <button
                  onClick={() => {
                    setSaveName(shortenAiName(question.trim()));
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
              {response?.sql ? "Save Query" : "Generate & Save Query"}
            </h2>

            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">Name</label>
                <input
                  type="text"
                  value={saveName}
                  onChange={(e) => setSaveName(e.target.value)}
                  placeholder="Query name..."
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
                  if (response?.sql) {
                    handleSaveQuery();
                  } else {
                    handleGenerateAndSaveQuery();
                  }
                }}
                disabled={saving || (!response?.sql && !saveName.trim())}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? "Saving..." : "Save Query"}
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
