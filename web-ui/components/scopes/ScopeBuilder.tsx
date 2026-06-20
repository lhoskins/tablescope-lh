"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import {
  IconArrowNarrowRight,
  IconArrowsExchange,
  IconDeviceFloppy,
  IconPlus,
  IconSparkles,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import {
  scopesApi,
  type MatchMode,
  type ScopeAISuggestion,
  type ScopeBuilderTable,
  type ScopeDirection,
  type ScopeMap,
} from "@/lib/api/scopes";

// Canvas layout geometry (deterministic so we can draw lines without DOM reads).
const CARD_WIDTH = 230;
const HEADER_H = 38;
const ROW_H = 28;
const DOT = 9;

interface PlacedTable {
  tableKey: string;
  queryId: number;
  name: string;
  fields: string[];
  x: number;
  y: number;
}

interface Link {
  localId: string;
  sourceQueryId: number;
  sourceField: string;
  sourceTable: string | null;
  targetQueryId: number;
  targetField: string;
  targetTable: string | null;
  matchGroupId: string;
  matchMode: MatchMode;
  direction: ScopeDirection;
  enabled: boolean;
  createdByAi: boolean;
  confidence: number | null;
}

function uid(): string {
  return Math.random().toString(36).slice(2, 12);
}

function cardHeight(t: PlacedTable): number {
  return HEADER_H + t.fields.length * ROW_H + 8;
}

function fieldY(t: PlacedTable, field: string): number {
  const idx = Math.max(0, t.fields.indexOf(field));
  return t.y + HEADER_H + idx * ROW_H + ROW_H / 2;
}

export function ScopeBuilder({
  projectId,
  scopeSetId,
}: {
  projectId: number;
  scopeSetId: number;
}) {
  const router = useRouter();
  const canvasRef = useRef<HTMLDivElement | null>(null);

  const [name, setName] = useState("Untitled Scope");
  const [enabled, setEnabled] = useState(true);
  const [available, setAvailable] = useState<ScopeBuilderTable[]>([]);
  const [tables, setTables] = useState<PlacedTable[]>([]);
  const [links, setLinks] = useState<Link[]>([]);
  const [pending, setPending] = useState<{
    queryId: number;
    field: string;
    table: string | null;
  } | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<ScopeAISuggestion[]>([]);
  const [aiBusy, setAiBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Load builder tables + existing map.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [builderTables, map] = await Promise.all([
          scopesApi.builderTables(projectId),
          scopesApi.getMap(scopeSetId),
        ]);
        if (cancelled) return;
        setAvailable(builderTables);
        hydrate(builderTables, map);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, scopeSetId]);

  const fieldsFor = useCallback(
    (queryId: number, builderTables: ScopeBuilderTable[]): string[] => {
      const t = builderTables.find((b) => b.query_id === queryId);
      return t ? t.fields : [];
    },
    [],
  );

  const hydrate = (builderTables: ScopeBuilderTable[], map: ScopeMap) => {
    setName(map.scope_set.name);
    setEnabled(map.scope_set.enabled);

    const placed: PlacedTable[] = [];
    map.tables.forEach((t, i) => {
      if (t.query_id == null) return;
      placed.push({
        tableKey: t.table_key,
        queryId: t.query_id,
        name: t.table_name ?? `Query ${t.query_id}`,
        fields: fieldsFor(t.query_id, builderTables),
        x: t.x_position || 60 + i * (CARD_WIDTH + 80),
        y: t.y_position || 60,
      });
    });
    // Ensure any query referenced by a relationship has a card.
    const ensure = (qid: number) => {
      if (placed.some((p) => p.queryId === qid)) return;
      const b = builderTables.find((bt) => bt.query_id === qid);
      placed.push({
        tableKey: b?.table_key ?? `query:${qid}`,
        queryId: qid,
        name: b?.table_name ?? `Query ${qid}`,
        fields: b?.fields ?? [],
        x: 60 + placed.length * (CARD_WIDTH + 80),
        y: 60,
      });
    };
    map.relationships.forEach((r) => {
      ensure(r.query_id);
      ensure(r.target_query_id);
    });

    setTables(placed);
    setLinks(
      map.relationships.map((r) => ({
        localId: uid(),
        sourceQueryId: r.query_id,
        sourceField: r.source_field,
        sourceTable: r.source_table,
        targetQueryId: r.target_query_id,
        targetField: r.target_field,
        targetTable: r.target_table,
        matchGroupId: r.match_group_id ?? uid(),
        matchMode: r.match_mode,
        direction: r.direction,
        enabled: r.enabled,
        createdByAi: r.created_by_ai,
        confidence: r.confidence_score,
      })),
    );
  };

  const placedIds = useMemo(
    () => new Set(tables.map((t) => t.queryId)),
    [tables],
  );

  const addTable = (b: ScopeBuilderTable) => {
    if (b.query_id == null || placedIds.has(b.query_id)) return;
    setTables((prev) => [
      ...prev,
      {
        tableKey: b.table_key,
        queryId: b.query_id as number,
        name: b.table_name,
        fields: b.fields,
        x: 60 + (prev.length % 3) * (CARD_WIDTH + 80),
        y: 60 + Math.floor(prev.length / 3) * 240,
      },
    ]);
  };

  const removeTable = (queryId: number) => {
    setTables((prev) => prev.filter((t) => t.queryId !== queryId));
    setLinks((prev) =>
      prev.filter(
        (l) => l.sourceQueryId !== queryId && l.targetQueryId !== queryId,
      ),
    );
  };

  // ── Card dragging ──────────────────────────────────────────────────────
  const dragRef = useRef<{
    queryId: number;
    offX: number;
    offY: number;
  } | null>(null);

  const onCardMouseDown = (e: React.MouseEvent, t: PlacedTable) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    dragRef.current = {
      queryId: t.queryId,
      offX: e.clientX - rect.left - t.x,
      offY: e.clientY - rect.top - t.y,
    };
  };

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const d = dragRef.current;
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!d || !rect) return;
      const x = Math.max(0, e.clientX - rect.left - d.offX);
      const y = Math.max(0, e.clientY - rect.top - d.offY);
      setTables((prev) =>
        prev.map((t) => (t.queryId === d.queryId ? { ...t, x, y } : t)),
      );
    };
    const onUp = () => {
      dragRef.current = null;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  // ── Field connecting ───────────────────────────────────────────────────
  const groupFor = (srcQ: number, tgtQ: number): string => {
    const existing = links.find(
      (l) => l.sourceQueryId === srcQ && l.targetQueryId === tgtQ,
    );
    return existing ? existing.matchGroupId : uid();
  };

  const onSourceDot = (t: PlacedTable, field: string) => {
    setPending({ queryId: t.queryId, field, table: t.name });
    setStatus(`Click a target field to connect "${field}"`);
  };

  const onTargetDot = (t: PlacedTable, field: string) => {
    if (!pending) {
      setStatus("Click a source field's right dot first, then a target field.");
      return;
    }
    if (pending.queryId === t.queryId) {
      setStatus("Source and target must be different tables.");
      setPending(null);
      return;
    }
    const gid = groupFor(pending.queryId, t.queryId);
    const dup = links.some(
      (l) =>
        l.sourceQueryId === pending.queryId &&
        l.sourceField === pending.field &&
        l.targetQueryId === t.queryId &&
        l.targetField === field,
    );
    if (dup) {
      setStatus("That field mapping already exists.");
      setPending(null);
      return;
    }
    setLinks((prev) => [
      ...prev,
      {
        localId: uid(),
        sourceQueryId: pending.queryId,
        sourceField: pending.field,
        sourceTable: pending.table,
        targetQueryId: t.queryId,
        targetField: field,
        targetTable: t.name,
        matchGroupId: gid,
        matchMode: "all",
        direction: "source_to_target",
        enabled: true,
        createdByAi: false,
        confidence: null,
      },
    ]);
    setSelectedGroup(gid);
    setPending(null);
    setStatus("Mapping added.");
  };

  // ── Grouped relationships (one per source/target table pair) ────────────
  const groups = useMemo(() => {
    const byGroup = new Map<string, Link[]>();
    for (const l of links) {
      const arr = byGroup.get(l.matchGroupId) ?? [];
      arr.push(l);
      byGroup.set(l.matchGroupId, arr);
    }
    return byGroup;
  }, [links]);

  const selectedLinks = selectedGroup ? groups.get(selectedGroup) ?? [] : [];
  const selectedHead = selectedLinks[0];

  const updateGroup = (gid: string, patch: Partial<Link>) => {
    setLinks((prev) =>
      prev.map((l) => (l.matchGroupId === gid ? { ...l, ...patch } : l)),
    );
  };

  const deleteGroup = (gid: string) => {
    setLinks((prev) => prev.filter((l) => l.matchGroupId !== gid));
    setSelectedGroup(null);
  };

  const reverseGroup = (gid: string) => {
    setLinks((prev) =>
      prev.map((l) =>
        l.matchGroupId === gid
          ? {
              ...l,
              sourceQueryId: l.targetQueryId,
              sourceField: l.targetField,
              sourceTable: l.targetTable,
              targetQueryId: l.sourceQueryId,
              targetField: l.sourceField,
              targetTable: l.sourceTable,
            }
          : l,
      ),
    );
  };

  // ── AI suggest ─────────────────────────────────────────────────────────
  const runAiSuggest = async () => {
    setAiBusy(true);
    setError(null);
    try {
      const ids = tables.map((t) => t.queryId);
      const res = await scopesApi.aiSuggest(scopeSetId, ids);
      // Hide suggestions that already exist on the canvas.
      const existing = new Set(
        links.map(
          (l) =>
            `${l.sourceQueryId}.${l.sourceField}>${l.targetQueryId}.${l.targetField}`,
        ),
      );
      setSuggestions(
        res.suggestions.filter(
          (s) =>
            !existing.has(
              `${s.query_id}.${s.source_field}>${s.target_query_id}.${s.target_field}`,
            ),
        ),
      );
      setStatus(`AI suggested ${res.suggestions.length} relationship(s).`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAiBusy(false);
    }
  };

  const acceptSuggestion = (s: ScopeAISuggestion) => {
    // Make sure both tables are on the canvas.
    [s.query_id, s.target_query_id].forEach((qid) => {
      if (!placedIds.has(qid)) {
        const b = available.find((a) => a.query_id === qid);
        if (b) addTable(b);
      }
    });
    const gid = groupFor(s.query_id, s.target_query_id);
    setLinks((prev) => [
      ...prev,
      {
        localId: uid(),
        sourceQueryId: s.query_id,
        sourceField: s.source_field,
        sourceTable: s.source_table,
        targetQueryId: s.target_query_id,
        targetField: s.target_field,
        targetTable: s.target_table,
        matchGroupId: gid,
        matchMode: s.match_mode,
        direction: "source_to_target",
        enabled: true,
        createdByAi: true,
        confidence: s.confidence_score,
      },
    ]);
    setSuggestions((prev) => prev.filter((x) => x !== s));
  };

  const acceptAll = () => {
    suggestions.forEach(acceptSuggestion);
  };

  // ── Save ───────────────────────────────────────────────────────────────
  const save = async () => {
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      await scopesApi.saveMap(scopeSetId, {
        name: name.trim() || "Untitled Scope",
        enabled,
        tables: tables.map((t) => ({
          table_key: t.tableKey,
          table_name: t.name,
          query_id: t.queryId,
          datasource_id: null,
          x_position: t.x,
          y_position: t.y,
          width: CARD_WIDTH,
          height: cardHeight(t),
        })),
        relationships: links.map((l) => ({
          query_id: l.sourceQueryId,
          source_field: l.sourceField,
          source_table: l.sourceTable,
          target_query_id: l.targetQueryId,
          target_field: l.targetField,
          target_table: l.targetTable,
          direction: l.direction,
          match_group_id: l.matchGroupId,
          match_mode: l.matchMode,
          enabled: l.enabled,
          confidence_score: l.confidence,
          created_by_ai: l.createdByAi,
        })),
      });
      setStatus("Scope saved.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const canvasWidth = Math.max(
    900,
    ...tables.map((t) => t.x + CARD_WIDTH + 80),
  );
  const canvasHeightPx = Math.max(
    560,
    ...tables.map((t) => t.y + cardHeight(t) + 60),
  );

  return (
    <div className="flex h-full min-h-[640px] flex-col">
      {/* Top bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line-tertiary pb-3">
        <div className="flex items-center gap-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="h-9 w-72 rounded-md border border-line-secondary bg-bg-primary px-3 text-[14px] font-semibold text-ink-primary focus:border-brand-500 focus:outline-none"
            placeholder="Scope name"
          />
          <button
            type="button"
            onClick={() => setEnabled((v) => !v)}
            title={enabled ? "Scope set enabled" : "Scope set disabled"}
            className="flex items-center gap-2 text-[12px] text-ink-secondary"
          >
            <span
              className={cn(
                "relative inline-flex h-5 w-9 items-center rounded-full transition-colors",
                enabled ? "bg-brand-500" : "bg-line-secondary",
              )}
            >
              <span
                className="inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform"
                style={{
                  transform: enabled ? "translateX(18px)" : "translateX(3px)",
                }}
              />
            </span>
            {enabled ? "Enabled" : "Disabled"}
          </button>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="brandSoft"
            onClick={runAiSuggest}
            disabled={aiBusy || tables.length < 2}
            title={
              tables.length < 2
                ? "Add at least two tables to the canvas"
                : "Suggest relationships with AI"
            }
          >
            <IconSparkles size={14} />
            {aiBusy ? "Suggesting…" : "AI Suggest"}
          </Button>
          <Button variant="primary" onClick={save} disabled={saving}>
            <IconDeviceFloppy size={14} />
            {saving ? "Saving…" : "Save Scope"}
          </Button>
        </div>
      </div>

      {(status || error) && (
        <div
          className={cn(
            "mt-2 rounded-md px-3 py-1.5 text-[12px]",
            error
              ? "bg-danger-bg text-danger"
              : "bg-brand-50 text-brand-700",
          )}
        >
          {error ?? status}
        </div>
      )}

      <div className="mt-3 flex min-h-0 flex-1 gap-3">
        {/* Left sidebar */}
        <aside className="w-56 shrink-0 overflow-y-auto rounded-lg border border-line-tertiary bg-bg-secondary/30 p-3">
          <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-ink-tertiary">
            Drag Tables to Canvas
          </h3>
          {available.length === 0 ? (
            <p className="text-[12px] text-ink-tertiary">
              No saved queries in this project yet.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {available
                .filter((b) => b.query_id != null)
                .map((b) => {
                  const on = placedIds.has(b.query_id as number);
                  return (
                    <li key={b.table_key}>
                      <button
                        type="button"
                        onClick={() => addTable(b)}
                        disabled={on}
                        className={cn(
                          "flex w-full items-center justify-between rounded-md border px-2.5 py-2 text-left text-[12.5px]",
                          on
                            ? "cursor-default border-line-tertiary bg-bg-secondary text-ink-tertiary"
                            : "border-line-secondary bg-bg-primary text-ink-primary hover:border-brand-500 hover:bg-brand-50",
                        )}
                      >
                        <span className="truncate">{b.table_name}</span>
                        {on ? (
                          <span className="text-[11px] text-ink-tertiary">
                            added
                          </span>
                        ) : (
                          <IconPlus size={13} className="shrink-0" />
                        )}
                      </button>
                    </li>
                  );
                })}
            </ul>
          )}
        </aside>

        {/* Canvas */}
        <div className="relative min-w-0 flex-1 overflow-auto rounded-lg border border-line-tertiary bg-[radial-gradient(circle,var(--tw-gradient-stops))] from-line-tertiary/30 to-transparent bg-bg-primary">
          <div
            ref={canvasRef}
            className="relative"
            style={{ width: canvasWidth, height: canvasHeightPx }}
            onClick={(e) => {
              if (e.target === e.currentTarget) {
                setSelectedGroup(null);
                setPending(null);
              }
            }}
          >
            {/* Relationship lines */}
            <svg
              className="pointer-events-none absolute inset-0"
              width={canvasWidth}
              height={canvasHeightPx}
            >
              <defs>
                <marker
                  id="scope-arrow"
                  markerWidth="10"
                  markerHeight="10"
                  refX="8"
                  refY="3"
                  orient="auto"
                  markerUnits="strokeWidth"
                >
                  <path d="M0,0 L8,3 L0,6 Z" fill="var(--color-brand-500, #2563eb)" />
                </marker>
              </defs>
              {links.map((l) => {
                const src = tables.find((t) => t.queryId === l.sourceQueryId);
                const tgt = tables.find((t) => t.queryId === l.targetQueryId);
                if (!src || !tgt) return null;
                const x1 = src.x + CARD_WIDTH;
                const y1 = fieldY(src, l.sourceField);
                const x2 = tgt.x;
                const y2 = fieldY(tgt, l.targetField);
                const mx = (x1 + x2) / 2;
                const selected = l.matchGroupId === selectedGroup;
                return (
                  <path
                    key={l.localId}
                    d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
                    fill="none"
                    stroke={
                      selected
                        ? "var(--color-brand-700, #1d4ed8)"
                        : "var(--color-brand-500, #2563eb)"
                    }
                    strokeWidth={selected ? 2.5 : 1.6}
                    strokeDasharray={l.createdByAi ? "5 4" : undefined}
                    opacity={l.enabled ? 1 : 0.4}
                    markerEnd="url(#scope-arrow)"
                    style={{ pointerEvents: "stroke", cursor: "pointer" }}
                    onClick={() => setSelectedGroup(l.matchGroupId)}
                  />
                );
              })}
            </svg>

            {/* Table cards */}
            {tables.map((t) => (
              <div
                key={t.queryId}
                className="absolute rounded-lg border border-line-secondary bg-bg-primary shadow-sm"
                style={{ left: t.x, top: t.y, width: CARD_WIDTH }}
              >
                <div
                  onMouseDown={(e) => onCardMouseDown(e, t)}
                  className="flex h-[38px] cursor-move items-center justify-between rounded-t-lg bg-bg-secondary px-3"
                >
                  <span className="truncate text-[12.5px] font-semibold text-ink-primary">
                    {t.name}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeTable(t.queryId)}
                    className="text-ink-tertiary hover:text-danger"
                    title="Remove from canvas"
                  >
                    <IconX size={13} />
                  </button>
                </div>
                <div>
                  {t.fields.length === 0 && (
                    <div className="px-3 py-2 text-[11px] text-ink-tertiary">
                      No fields detected
                    </div>
                  )}
                  {t.fields.map((f) => (
                    <div
                      key={f}
                      className="relative flex items-center justify-between px-3 text-[12px] text-ink-secondary"
                      style={{ height: ROW_H }}
                    >
                      {/* target (incoming) dot — left */}
                      <button
                        type="button"
                        title={`Connect into ${f}`}
                        onClick={() => onTargetDot(t, f)}
                        className="absolute -left-[5px] rounded-full border-2 border-brand-500 bg-bg-primary hover:bg-brand-500"
                        style={{
                          width: DOT,
                          height: DOT,
                          top: ROW_H / 2 - DOT / 2,
                        }}
                      />
                      <span className="truncate">{f}</span>
                      {/* source (outgoing) dot — right */}
                      <button
                        type="button"
                        title={`Start a mapping from ${f}`}
                        onClick={() => onSourceDot(t, f)}
                        className={cn(
                          "absolute -right-[5px] rounded-full border-2 border-brand-500 hover:bg-brand-500",
                          pending &&
                            pending.queryId === t.queryId &&
                            pending.field === f
                            ? "bg-brand-500"
                            : "bg-bg-primary",
                        )}
                        style={{
                          width: DOT,
                          height: DOT,
                          top: ROW_H / 2 - DOT / 2,
                        }}
                      />
                    </div>
                  ))}
                </div>
              </div>
            ))}

            {tables.length === 0 && (
              <div className="absolute inset-0 flex items-center justify-center">
                <p className="text-[13px] text-ink-tertiary">
                  Add tables from the left to start building relationships.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* AI Scope Guidance panel */}
        <aside className="w-64 shrink-0 overflow-y-auto rounded-lg border border-line-tertiary bg-bg-secondary/30 p-3">
          <h3 className="mb-2 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-ink-tertiary">
            <IconSparkles size={13} /> AI Scope Guidance
          </h3>
          {suggestions.length === 0 ? (
            <p className="text-[12px] text-ink-tertiary">
              Click “AI Suggest” to find likely field relationships between the
              tables on your canvas.
            </p>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-ink-secondary">
                  {suggestions.length} suggestion(s)
                </span>
                <button
                  type="button"
                  onClick={acceptAll}
                  className="text-[11px] font-medium text-brand-700 hover:underline"
                >
                  Accept all
                </button>
              </div>
              <ul className="space-y-2">
                {suggestions.map((s, i) => (
                  <li
                    key={`${s.query_id}-${s.source_field}-${i}`}
                    className="rounded-md border border-line-secondary bg-bg-primary p-2"
                  >
                    <div className="flex items-center gap-1 text-[12px] text-ink-primary">
                      <span className="truncate font-medium">
                        {s.source_table}.{s.source_field}
                      </span>
                      <IconArrowNarrowRight
                        size={13}
                        className="shrink-0 text-ink-tertiary"
                      />
                      <span className="truncate font-medium">
                        {s.target_table}.{s.target_field}
                      </span>
                    </div>
                    {s.confidence_score != null && (
                      <div className="mt-0.5 text-[11px] text-ink-tertiary">
                        confidence {Math.round(s.confidence_score * 100)}%
                      </div>
                    )}
                    <div className="mt-1.5 flex gap-2">
                      <button
                        type="button"
                        onClick={() => acceptSuggestion(s)}
                        className="text-[11px] font-medium text-brand-700 hover:underline"
                      >
                        Accept
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          setSuggestions((prev) =>
                            prev.filter((x) => x !== s),
                          )
                        }
                        className="text-[11px] text-ink-tertiary hover:underline"
                      >
                        Ignore
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>

      {/* Bottom properties panel */}
      {selectedHead && (
        <div className="mt-3 rounded-lg border border-line-secondary bg-bg-primary p-3">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-[13px] font-semibold text-ink-primary">
              Selected Relationship
              {selectedLinks.length > 1 && (
                <Badge tone="brand" className="ml-2">
                  {selectedLinks.length} fields
                </Badge>
              )}
            </h3>
            <button
              type="button"
              onClick={() => setSelectedGroup(null)}
              className="text-ink-tertiary hover:text-ink-primary"
            >
              <IconX size={15} />
            </button>
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-[12.5px] md:grid-cols-4">
            <Field label="Scope Set">{name}</Field>
            <Field label="Source Table">{selectedHead.sourceTable}</Field>
            <Field label="Target Table">{selectedHead.targetTable}</Field>
            <Field label="Direction">
              <span className="inline-flex items-center gap-1">
                Source <IconArrowNarrowRight size={13} /> Target
              </span>
            </Field>
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 text-[12.5px] text-ink-secondary">
              Match Mode
              <select
                value={selectedHead.matchMode}
                onChange={(e) =>
                  updateGroup(selectedHead.matchGroupId, {
                    matchMode: e.target.value as MatchMode,
                  })
                }
                className="h-8 rounded-md border border-line-secondary bg-bg-primary px-2 text-[12.5px]"
              >
                <option value="all">All fields must match</option>
                <option value="any">Any field can match</option>
              </select>
            </label>
            <label className="flex items-center gap-2 text-[12.5px] text-ink-secondary">
              <input
                type="checkbox"
                checked={selectedHead.enabled}
                onChange={(e) =>
                  updateGroup(selectedHead.matchGroupId, {
                    enabled: e.target.checked,
                  })
                }
              />
              Enabled
            </label>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => reverseGroup(selectedHead.matchGroupId)}
            >
              <IconArrowsExchange size={13} />
              Reverse Direction
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={() => deleteGroup(selectedHead.matchGroupId)}
            >
              <IconTrash size={13} />
              Delete Relationship
            </Button>
            <Button variant="primary" size="sm" onClick={save} disabled={saving}>
              <IconDeviceFloppy size={13} />
              Save
            </Button>
          </div>
        </div>
      )}

      <div className="mt-3 flex justify-end">
        <Button
          variant="ghost"
          onClick={() => router.push(`/projects/${projectId}/scopes`)}
        >
          Back to Scopes
        </Button>
      </div>

      {loading && (
        <div className="mt-2 text-[12px] text-ink-tertiary">Loading map…</div>
      )}
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-ink-tertiary">
        {label}
      </div>
      <div className="truncate text-ink-primary">{children ?? "—"}</div>
    </div>
  );
}
