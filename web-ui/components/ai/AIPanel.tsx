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

type Props = {
  projectId: number;
};

/* ---------- Component ---------- */

export function AIPanel({ projectId }: Props) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [activeFeature, setActiveFeature] = useState<
    "ask" | "sql" | "relationships" | "dashboard"
  >("ask");
  const [response, setResponse] = useState<AIResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<
    Array<{ question: string; answer: string; feature: string }>
  >([]);

  const callAI = useCallback(
    async (feature: string, body: Record<string, unknown>) => {
      setLoading(true);
      setError(null);
      setResponse(null);
      try {
        const endpoints: Record<string, string> = {
          ask: "/api/ai/ask",
          sql: "/api/ai/query/generate",
          relationships: "/api/ai/project/relationships/generate",
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

  const handleDashboardSuggest = () => {
    callAI("dashboard", { project_id: projectId });
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
            { key: "dashboard", label: "Suggest Dashboard" },
          ] as const
        ).map((f) => (
          <button
            key={f.key}
            onClick={() => setActiveFeature(f.key)}
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

      {/* Input area */}
      {(activeFeature === "ask" || activeFeature === "sql") && (
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
            disabled={loading}
          />
          <button
            onClick={handleAsk}
            disabled={loading || !question.trim()}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? "Thinking..." : activeFeature === "ask" ? "Ask" : "Generate"}
          </button>
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

      {activeFeature === "dashboard" && (
        <button
          onClick={handleDashboardSuggest}
          disabled={loading}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Generating..." : "Suggest Dashboard Widgets"}
        </button>
      )}

      {/* Loading indicator */}
      {loading && (
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          Processing with tenant-isolated AI...
        </div>
      )}

      {/* Error display */}
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
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
              <h3 className="mb-2 text-sm font-semibold text-slate-900">Generated SQL</h3>
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
                    <span className="text-slate-400">→</span>
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

          {/* Dashboard suggestions */}
          {response.suggestions && response.suggestions.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-900">
                Dashboard Suggestions
              </h3>
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
