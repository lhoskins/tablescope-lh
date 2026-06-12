"use client";

export type DrilldownState = {
  open: boolean;
  loading: boolean;
  error: string | null;
  title: string;
  targetQueryName: string | null;
  columns: string[];
  rows: Array<Record<string, unknown>>;
};

type Props = {
  state: DrilldownState;
  onClose: () => void;
};

/**
 * Right-hand side panel showing drilldown result rows for a clicked chart
 * element. Reuses the existing query-scope filter results.
 */
export function DrilldownPanel({ state, onClose }: Props) {
  if (!state.open) return null;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-slate-900/20" onClick={onClose} />
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-2xl flex-col border-l border-slate-200 bg-white shadow-2xl">
        <div className="flex items-start justify-between border-b border-slate-200 bg-slate-800 px-4 py-3">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-bold text-white">{state.title}</h3>
            {state.targetQueryName && (
              <p className="mt-0.5 truncate text-[11px] text-slate-300">
                Target query: {state.targetQueryName}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="ml-3 rounded p-1 text-slate-300 hover:bg-slate-700 hover:text-white"
            title="Close"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-auto p-4">
          {state.loading ? (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">
              Loading drilldown…
            </div>
          ) : state.error ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
              {state.error}
            </div>
          ) : state.rows.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">
              No matching records.
            </div>
          ) : (
            <div className="overflow-auto rounded-lg border border-slate-200">
              <table className="min-w-full text-left text-[11px]">
                <thead className="bg-slate-50">
                  <tr>
                    {state.columns.map((col) => (
                      <th key={col} className="border-b border-slate-200 px-3 py-2 font-semibold uppercase tracking-wide text-slate-500">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {state.rows.map((row, i) => (
                    <tr key={i} className="even:bg-slate-50/50">
                      {state.columns.map((col) => (
                        <td key={col} className="border-b border-slate-100 px-3 py-1.5 text-slate-700">
                          {row[col] === null || row[col] === undefined ? "" : String(row[col])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {!state.loading && !state.error && state.rows.length > 0 && (
          <div className="border-t border-slate-200 px-4 py-2 text-[11px] text-slate-500">
            {state.rows.length} row{state.rows.length !== 1 ? "s" : ""}
          </div>
        )}
      </div>
    </>
  );
}
