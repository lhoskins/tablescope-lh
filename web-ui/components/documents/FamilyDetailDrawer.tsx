"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

type FamilyMember = { node_id: number; name: string; type?: string; summary?: string; role?: string };

type FamilyDetail = {
  family_node_id: number;
  family_name: string;
  family_type: string;
  business_domain: string;
  summary: string;
  supported_kpis: string[];
  related_processes: string[];
  suggested_dashboards: string[];
  missing_documents: string[];
  members: {
    documents: FamilyMember[];
    datasources: FamilyMember[];
    queries: FamilyMember[];
    dashboards: FamilyMember[];
    kpis: FamilyMember[];
    entities: FamilyMember[];
  };
  relationships: { from: string; relationship_type: string; to: string; confidence: number }[];
  suggested_questions: string[];
};

function MemberList({ title, items }: { title: string; items: FamilyMember[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <h4 className="text-xs font-semibold text-slate-500 uppercase mb-1">{title}</h4>
      <div className="flex flex-wrap gap-1.5">
        {items.map((m) => (
          <span
            key={`${title}-${m.node_id}`}
            className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700"
            title={m.summary || m.role || ""}
          >
            {m.name}
          </span>
        ))}
      </div>
    </div>
  );
}

export function FamilyDetailDrawer({
  projectId,
  familyNodeId,
  canEdit,
  onClose,
}: {
  projectId: number;
  familyNodeId: number;
  canEdit: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery<FamilyDetail>({
    queryKey: ["document-family", projectId, familyNodeId],
    queryFn: () => apiClient.get(`/api/projects/${projectId}/document-families/${familyNodeId}`),
  });

  const rebuild = useMutation({
    mutationFn: () =>
      apiClient.post(`/api/projects/${projectId}/document-families/${familyNodeId}/rebuild-summary`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["document-family", projectId, familyNodeId] });
      queryClient.invalidateQueries({ queryKey: ["document-families", projectId] });
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative h-full w-full max-w-lg overflow-y-auto bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white px-5 py-4">
          <div>
            <p className="text-[10px] font-semibold uppercase text-slate-400">Document Family</p>
            <h2 className="text-lg font-semibold text-slate-900">
              {data?.family_name ?? "Loading…"}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-2 py-1 text-sm text-slate-500 hover:bg-slate-100"
          >
            Close
          </button>
        </div>

        {isLoading || !data ? (
          <div className="p-5 text-sm text-slate-400">Loading family…</div>
        ) : (
          <div className="space-y-5 p-5">
            <div className="flex flex-wrap gap-4 text-sm">
              {data.family_type && (
                <div>
                  <span className="text-[10px] uppercase text-slate-400">Type</span>
                  <p className="text-slate-700">{data.family_type.replace(/_/g, " ")}</p>
                </div>
              )}
              {data.business_domain && (
                <div>
                  <span className="text-[10px] uppercase text-slate-400">Domain</span>
                  <p className="text-slate-700">{data.business_domain.replace(/_/g, " ")}</p>
                </div>
              )}
            </div>

            {data.summary && (
              <div>
                <h4 className="text-xs font-semibold text-slate-500 uppercase mb-1">Summary</h4>
                <p className="text-sm text-slate-700">{data.summary}</p>
              </div>
            )}

            <MemberList title="Documents" items={data.members.documents} />
            <MemberList title="Related Datasources" items={data.members.datasources} />
            <MemberList title="Supported KPIs" items={data.members.kpis} />
            <MemberList title="Entities" items={data.members.entities} />
            <MemberList title="Queries" items={data.members.queries} />
            <MemberList title="Dashboards" items={data.members.dashboards} />

            {data.related_processes?.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-slate-500 uppercase mb-1">Related Processes</h4>
                <div className="flex flex-wrap gap-1.5">
                  {data.related_processes.map((p, i) => (
                    <span key={i} className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">{p}</span>
                  ))}
                </div>
              </div>
            )}

            {data.suggested_dashboards?.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-slate-500 uppercase mb-1">Suggested Dashboards</h4>
                <ul className="space-y-1">
                  {data.suggested_dashboards.map((d, i) => (
                    <li key={i} className="text-xs text-slate-600 flex items-start gap-1">
                      <span className="text-slate-400">•</span>{d}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {data.missing_documents?.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-slate-500 uppercase mb-1">Possibly Missing</h4>
                <ul className="space-y-1">
                  {data.missing_documents.map((d, i) => (
                    <li key={i} className="text-xs text-amber-700 flex items-start gap-1">
                      <span className="text-amber-400">•</span>{d}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {data.relationships?.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-slate-500 uppercase mb-1">Relationships</h4>
                <div className="space-y-1">
                  {data.relationships.map((r, i) => (
                    <div key={i} className="text-xs text-slate-600">
                      <span className="font-medium">{r.from}</span>
                      <span className="mx-1 text-slate-400">{r.relationship_type.replace(/_/g, " ")}</span>
                      <span className="font-medium">{r.to}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {data.suggested_questions?.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-slate-500 uppercase mb-1">Suggested Questions</h4>
                <ul className="space-y-1">
                  {data.suggested_questions.map((q, i) => (
                    <li key={i} className="text-xs text-slate-600 flex items-start gap-1">
                      <span className="text-slate-400">•</span>{q}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {canEdit && (
              <div className="border-t border-slate-100 pt-3">
                <button
                  type="button"
                  onClick={() => rebuild.mutate()}
                  disabled={rebuild.isPending}
                  className="rounded-md bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-50"
                >
                  {rebuild.isPending ? "Rebuilding…" : "Rebuild family summary"}
                </button>
                {rebuild.isError && (
                  <p className="mt-2 text-xs text-red-600">Could not rebuild summary.</p>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
