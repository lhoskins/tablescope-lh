"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useNotifyScopesChanged } from "@/lib/ui/scope-refresh";
import {
  IconArrowNarrowRight,
  IconArrowsExchange,
  IconChevronDown,
  IconDeviceFloppy,
  IconGripVertical,
  IconMaximize,
  IconPencil,
  IconPlus,
  IconSearch,
  IconSparkles,
  IconTrash,
  IconX,
  IconZoomIn,
  IconZoomOut,
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
const CARD_WIDTH = 320;
const HEADER_H = 52;
const ROW_H = 30;
const DOT = 12;
const MIN_ZOOM = 0.4;
const MAX_ZOOM = 1.4;

type CardRole = "source" | "target" | "added";

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
  return HEADER_H + Math.max(1, t.fields.length) * ROW_H + 10;
}

function fieldY(t: PlacedTable, field: string): number {
  const idx = Math.max(0, t.fields.indexOf(field));
  return t.y + HEADER_H + idx * ROW_H + ROW_H / 2;
}

function confidenceLabel(c: number | null): {
  text: string;
  tone: "success" | "warning" | "neutral";
} {
  if (c == null) return { text: "Medium", tone: "warning" };
  if (c >= 0.8) return { text: "High", tone: "success" };
  if (c >= 0.5) return { text: "Medium", tone: "warning" };
  return { text: "Low", tone: "neutral" };
}

function suggestionKey(s: ScopeAISuggestion): string {
  return `${s.query_id}.${s.source_field}>${s.target_query_id}.${s.target_field}`;
}

export function ScopeBuilder({
  projectId,
  scopeSetId,
}: {
  projectId: number;
  scopeSetId: number;
}) {
  const router = useRouter();
  const notifyScopesChanged = useNotifyScopesChanged();
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);

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
  const [popup, setPopup] = useState<{ gid: string; x: number; y: number } | null>(
    null,
  );
  const popupRef = useRef<HTMLDivElement>(null);
  const [popupPos, setPopupPos] = useState<{ left: number; top: number } | null>(
    null,
  );
  const [suggestions, setSuggestions] = useState<ScopeAISuggestion[]>([]);
  const [ignored, setIgnored] = useState<ScopeAISuggestion[]>([]);
  const [showIgnored, setShowIgnored] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [sourceQueryId, setSourceQueryId] = useState<number | null>(null);
  const [targetQueryId, setTargetQueryId] = useState<number | null>(null);
  const [zoom, setZoom] = useState(1);
  const [panning, setPanning] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const fieldsFor = useCallback(
    (queryId: number, builderTables: ScopeBuilderTable[]): string[] => {
      const t = builderTables.find((b) => b.query_id === queryId);
      return t ? t.fields : [];
    },
    [],
  );

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
        x: t.x_position || 40 + i * (CARD_WIDTH + 100),
        y: t.y_position || 40,
      });
    });
    const ensure = (qid: number) => {
      if (placed.some((p) => p.queryId === qid)) return;
      const b = builderTables.find((bt) => bt.query_id === qid);
      placed.push({
        tableKey: b?.table_key ?? `query:${qid}`,
        queryId: qid,
        name: b?.table_name ?? `Query ${qid}`,
        fields: b?.fields ?? [],
        x: 40 + placed.length * (CARD_WIDTH + 100),
        y: 40,
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

    // Seed the guided setup with the first relationship pair, if any.
    if (map.relationships.length > 0) {
      setSourceQueryId(map.relationships[0].query_id);
      setTargetQueryId(map.relationships[0].target_query_id);
    }
  };

  const placedIds = useMemo(
    () => new Set(tables.map((t) => t.queryId)),
    [tables],
  );

  const roleOf = useCallback(
    (queryId: number): CardRole => {
      if (queryId === sourceQueryId) return "source";
      if (queryId === targetQueryId) return "target";
      return "added";
    },
    [sourceQueryId, targetQueryId],
  );

  const placeTable = useCallback(
    (b: ScopeBuilderTable, x?: number, y?: number) => {
      if (b.query_id == null) return;
      setTables((prev) => {
        if (prev.some((t) => t.queryId === b.query_id)) return prev;
        return [
          ...prev,
          {
            tableKey: b.table_key,
            queryId: b.query_id as number,
            name: b.table_name,
            fields: b.fields,
            x: x ?? 40 + (prev.length % 3) * (CARD_WIDTH + 100),
            y: y ?? 40 + Math.floor(prev.length / 3) * 260,
          },
        ];
      });
    },
    [],
  );

  const removeTable = (queryId: number) => {
    setTables((prev) => prev.filter((t) => t.queryId !== queryId));
    setLinks((prev) =>
      prev.filter(
        (l) => l.sourceQueryId !== queryId && l.targetQueryId !== queryId,
      ),
    );
    if (queryId === sourceQueryId) setSourceQueryId(null);
    if (queryId === targetQueryId) setTargetQueryId(null);
  };

  // Auto-place source/target cards in fixed left/right slots when chosen.
  useEffect(() => {
    if (sourceQueryId == null) return;
    const b = available.find((a) => a.query_id === sourceQueryId);
    if (!b) return;
    setTables((prev) => {
      if (prev.some((t) => t.queryId === sourceQueryId)) return prev;
      return [
        ...prev,
        {
          tableKey: b.table_key,
          queryId: sourceQueryId,
          name: b.table_name,
          fields: b.fields,
          x: 40,
          y: 40,
        },
      ];
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceQueryId, available]);

  useEffect(() => {
    if (targetQueryId == null) return;
    const b = available.find((a) => a.query_id === targetQueryId);
    if (!b) return;
    setTables((prev) => {
      if (prev.some((t) => t.queryId === targetQueryId)) return prev;
      return [
        ...prev,
        {
          tableKey: b.table_key,
          queryId: targetQueryId,
          name: b.table_name,
          fields: b.fields,
          x: 40 + CARD_WIDTH + 180,
          y: 40,
        },
      ];
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetQueryId, available]);

  // ── Card dragging ──────────────────────────────────────────────────────
  const dragRef = useRef<{ queryId: number; offX: number; offY: number } | null>(
    null,
  );

  const onCardMouseDown = (e: React.MouseEvent, t: PlacedTable) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    dragRef.current = {
      queryId: t.queryId,
      offX: (e.clientX - rect.left) / zoom - t.x,
      offY: (e.clientY - rect.top) / zoom - t.y,
    };
  };

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const d = dragRef.current;
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!d || !rect) return;
      const x = Math.max(0, (e.clientX - rect.left) / zoom - d.offX);
      const y = Math.max(0, (e.clientY - rect.top) / zoom - d.offY);
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
  }, [zoom]);

  // ── Canvas panning (grab empty space to move the viewport) ──────────────
  const panRef = useRef<{
    x: number;
    y: number;
    sl: number;
    st: number;
  } | null>(null);

  const onCanvasMouseDown = (e: React.MouseEvent) => {
    // Only pan when grabbing empty canvas background, not a card/dot/label.
    if (e.target !== e.currentTarget) return;
    const vp = viewportRef.current;
    if (!vp) return;
    panRef.current = {
      x: e.clientX,
      y: e.clientY,
      sl: vp.scrollLeft,
      st: vp.scrollTop,
    };
    setPanning(true);
  };

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const p = panRef.current;
      const vp = viewportRef.current;
      if (!p || !vp) return;
      vp.scrollLeft = p.sl - (e.clientX - p.x);
      vp.scrollTop = p.st - (e.clientY - p.y);
    };
    const onUp = () => {
      if (panRef.current) {
        panRef.current = null;
        setPanning(false);
      }
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  // ── Field connecting ───────────────────────────────────────────────────
  const groupFor = useCallback(
    (srcQ: number, tgtQ: number): string => {
      const existing = links.find(
        (l) => l.sourceQueryId === srcQ && l.targetQueryId === tgtQ,
      );
      return existing ? existing.matchGroupId : uid();
    },
    [links],
  );

  const addLink = useCallback(
    (params: {
      sourceQueryId: number;
      sourceField: string;
      sourceTable: string | null;
      targetQueryId: number;
      targetField: string;
      targetTable: string | null;
      matchMode?: MatchMode;
      createdByAi?: boolean;
      confidence?: number | null;
    }): string | null => {
      const dup = links.some(
        (l) =>
          l.sourceQueryId === params.sourceQueryId &&
          l.sourceField === params.sourceField &&
          l.targetQueryId === params.targetQueryId &&
          l.targetField === params.targetField,
      );
      if (dup) return null;
      const gid = groupFor(params.sourceQueryId, params.targetQueryId);
      const groupMode =
        links.find((l) => l.matchGroupId === gid)?.matchMode ??
        params.matchMode ??
        "all";
      setLinks((prev) => [
        ...prev,
        {
          localId: uid(),
          sourceQueryId: params.sourceQueryId,
          sourceField: params.sourceField,
          sourceTable: params.sourceTable,
          targetQueryId: params.targetQueryId,
          targetField: params.targetField,
          targetTable: params.targetTable,
          matchGroupId: gid,
          matchMode: groupMode,
          direction: "source_to_target",
          enabled: true,
          createdByAi: params.createdByAi ?? false,
          confidence: params.confidence ?? null,
        },
      ]);
      return gid;
    },
    [groupFor, links],
  );

  const onSourceDot = (t: PlacedTable, field: string) => {
    setPending({ queryId: t.queryId, field, table: t.name });
    setStatus(`Connect "${field}" — now click a target field on another card.`);
  };

  const onTargetDot = (t: PlacedTable, field: string) => {
    if (!pending) {
      setStatus("Click a source field (right edge) first, then a target field.");
      return;
    }
    if (pending.queryId === t.queryId) {
      setStatus("Source and target must be different queries.");
      setPending(null);
      return;
    }
    const gid = addLink({
      sourceQueryId: pending.queryId,
      sourceField: pending.field,
      sourceTable: pending.table,
      targetQueryId: t.queryId,
      targetField: field,
      targetTable: t.name,
    });
    if (gid) {
      setSelectedGroup(gid);
      setStatus("Field match added.");
    } else {
      setStatus("That field match already exists.");
    }
    setPending(null);
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

  // Selecting a relationship drives the source/target pair (and role badges +
  // field-match grid) now that the top dropdowns are gone.
  const selSrc = selectedHead?.sourceQueryId;
  const selTgt = selectedHead?.targetQueryId;
  useEffect(() => {
    if (selSrc != null && selTgt != null) {
      setSourceQueryId(selSrc);
      setTargetQueryId(selTgt);
    }
  }, [selSrc, selTgt]);

  const updateGroup = (gid: string, patch: Partial<Link>) => {
    setLinks((prev) =>
      prev.map((l) => (l.matchGroupId === gid ? { ...l, ...patch } : l)),
    );
  };

  const deleteGroup = (gid: string) => {
    setLinks((prev) => prev.filter((l) => l.matchGroupId !== gid));
    setSelectedGroup(null);
    setPopup((p) => (p?.gid === gid ? null : p));
  };

  // Open the relationship details popup near the clicked line/label.
  const openRelationshipPopup = (gid: string, e: { clientX: number; clientY: number }) => {
    setSelectedGroup(gid);
    setPopup({ gid, x: e.clientX, y: e.clientY });
  };

  const queryDisplayName = useCallback(
    (queryId: number, fallbackTable: string | null): string => {
      const placed = tables.find((t) => t.queryId === queryId);
      if (placed) return placed.name;
      const avail = available.find((a) => a.query_id === queryId);
      if (avail) return avail.table_name;
      return fallbackTable ?? `Query ${queryId}`;
    },
    [tables, available],
  );

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

  // Close the relationship popup on Escape.
  useEffect(() => {
    if (!popup) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPopup(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [popup]);

  // Viewport-aware popup placement: measure the rendered popup and clamp it so
  // it never overflows the viewport (keeps a 16px margin from every edge),
  // flipping to the other side of the click point when there isn't room.
  useEffect(() => {
    if (!popup) {
      setPopupPos(null);
      return;
    }
    const place = () => {
      const el = popupRef.current;
      if (!el) return;
      const margin = 16;
      const gap = 8;
      const { width: w, height: h } = el.getBoundingClientRect();
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      let left = popup.x + gap;
      if (left + w + margin > vw) left = popup.x - gap - w; // flip left
      left = Math.min(Math.max(left, margin), Math.max(margin, vw - w - margin));

      let top = popup.y + gap;
      if (top + h + margin > vh) top = popup.y - gap - h; // flip above
      top = Math.min(Math.max(top, margin), Math.max(margin, vh - h - margin));

      setPopupPos({ left, top });
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [popup]);

  // ── Guided field-match grid (for the chosen source/target pair) ─────────
  const pairLinks = useMemo(
    () =>
      links.filter(
        (l) =>
          sourceQueryId != null &&
          targetQueryId != null &&
          l.sourceQueryId === sourceQueryId &&
          l.targetQueryId === targetQueryId,
      ),
    [links, sourceQueryId, targetQueryId],
  );

  const sourceFields = useMemo(
    () => available.find((a) => a.query_id === sourceQueryId)?.fields ?? [],
    [available, sourceQueryId],
  );
  const targetFields = useMemo(
    () => available.find((a) => a.query_id === targetQueryId)?.fields ?? [],
    [available, targetQueryId],
  );

  const pairMatchMode: MatchMode = pairLinks[0]?.matchMode ?? "all";

  const addFieldMatch = () => {
    if (sourceQueryId == null || targetQueryId == null) {
      setStatus("Pick a source and target query first.");
      return;
    }
    const src =
      sourceFields.find((f) => !pairLinks.some((l) => l.sourceField === f)) ??
      sourceFields[0];
    const tgt =
      targetFields.find((f) => !pairLinks.some((l) => l.targetField === f)) ??
      targetFields[0];
    if (!src || !tgt) {
      setStatus("Both queries need at least one field.");
      return;
    }
    const gid = addLink({
      sourceQueryId,
      sourceField: src,
      sourceTable:
        available.find((a) => a.query_id === sourceQueryId)?.table_name ?? null,
      targetQueryId,
      targetField: tgt,
      targetTable:
        available.find((a) => a.query_id === targetQueryId)?.table_name ?? null,
      matchMode: pairMatchMode,
    });
    if (gid) setSelectedGroup(gid);
  };

  const updatePairFields = (
    localId: string,
    patch: { sourceField?: string; targetField?: string },
  ) => {
    setLinks((prev) =>
      prev.map((l) => (l.localId === localId ? { ...l, ...patch } : l)),
    );
  };

  const removeLink = (localId: string) => {
    setLinks((prev) => prev.filter((l) => l.localId !== localId));
  };

  const setPairMatchMode = (mode: MatchMode) => {
    if (sourceQueryId == null || targetQueryId == null) return;
    setLinks((prev) =>
      prev.map((l) =>
        l.sourceQueryId === sourceQueryId && l.targetQueryId === targetQueryId
          ? { ...l, matchMode: mode }
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
      // Prefer the guided pair if both are chosen.
      const scope =
        sourceQueryId != null && targetQueryId != null
          ? [sourceQueryId, targetQueryId]
          : ids;
      const res = await scopesApi.aiSuggest(scopeSetId, scope);
      const existing = new Set(
        links.map(
          (l) =>
            `${l.sourceQueryId}.${l.sourceField}>${l.targetQueryId}.${l.targetField}`,
        ),
      );
      const ign = new Set(ignored.map(suggestionKey));
      setSuggestions(
        res.suggestions.filter(
          (s) => !existing.has(suggestionKey(s)) && !ign.has(suggestionKey(s)),
        ),
      );
      setStatus(`AI found ${res.suggestions.length} suggested relationship(s).`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAiBusy(false);
    }
  };

  const acceptSuggestion = (s: ScopeAISuggestion) => {
    [s.query_id, s.target_query_id].forEach((qid) => {
      if (!placedIds.has(qid)) {
        const b = available.find((a) => a.query_id === qid);
        if (b) placeTable(b);
      }
    });
    addLink({
      sourceQueryId: s.query_id,
      sourceField: s.source_field,
      sourceTable: s.source_table,
      targetQueryId: s.target_query_id,
      targetField: s.target_field,
      targetTable: s.target_table,
      matchMode: s.match_mode,
      createdByAi: true,
      confidence: s.confidence_score,
    });
    setSuggestions((prev) => prev.filter((x) => x !== s));
  };

  const ignoreSuggestion = (s: ScopeAISuggestion) => {
    setSuggestions((prev) => prev.filter((x) => x !== s));
    setIgnored((prev) => [...prev, s]);
  };

  const restoreIgnored = (s: ScopeAISuggestion) => {
    setIgnored((prev) => prev.filter((x) => x !== s));
    setSuggestions((prev) => [...prev, s]);
  };

  const acceptAll = () => suggestions.forEach(acceptSuggestion);
  const ignoreAll = () => {
    setIgnored((prev) => [...prev, ...suggestions]);
    setSuggestions([]);
  };

  // Suggestions that can be drawn as dashed preview lines.
  const drawableSuggestions = useMemo(
    () =>
      suggestions.filter(
        (s) => placedIds.has(s.query_id) && placedIds.has(s.target_query_id),
      ),
    [suggestions, placedIds],
  );

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
      notifyScopesChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  // ── Delete the whole scope set ─────────────────────────────────────────
  const deleteScope = async () => {
    if (
      typeof window !== "undefined" &&
      !window.confirm(
        "Delete this scope map? This will remove the scope set and all field " +
          "relationships inside it. Existing queries and data sources will not " +
          "be deleted.",
      )
    ) {
      return;
    }
    setDeleting(true);
    setError(null);
    try {
      await scopesApi.deleteScopeSet(scopeSetId);
      notifyScopesChanged();
      router.push(`/projects/${projectId}/scopes`);
    } catch (e) {
      setError((e as Error).message);
      setDeleting(false);
    }
  };

  // ── Canvas sizing + zoom controls ──────────────────────────────────────
  const contentWidth = Math.max(
    900,
    ...tables.map((t) => t.x + CARD_WIDTH + 80),
  );
  const contentHeight = Math.max(
    520,
    ...tables.map((t) => t.y + cardHeight(t) + 60),
  );

  const fitToScreen = () => {
    const vp = viewportRef.current;
    if (!vp) return;
    const z = Math.min(
      vp.clientWidth / contentWidth,
      vp.clientHeight / contentHeight,
      1,
    );
    setZoom(Math.max(MIN_ZOOM, z));
  };

  const resetLayout = () => {
    setTables((prev) =>
      prev.map((t) => {
        const role = roleOf(t.queryId);
        if (role === "source") return { ...t, x: 40, y: 40 };
        if (role === "target")
          return { ...t, x: 40 + CARD_WIDTH + 180, y: 40 };
        return t;
      }),
    );
    setZoom(1);
  };

  // ── Drag query rows from the left panel onto the canvas ─────────────────
  const onCanvasDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const qid = Number(e.dataTransfer.getData("text/scope-query"));
    if (!qid) return;
    const b = available.find((a) => a.query_id === qid);
    if (!b || placedIds.has(qid)) return;
    const rect = canvasRef.current?.getBoundingClientRect();
    const x = rect ? Math.max(0, (e.clientX - rect.left) / zoom - 40) : undefined;
    const y = rect ? Math.max(0, (e.clientY - rect.top) / zoom - 20) : undefined;
    placeTable(b, x, y);
  };

  const filteredAvailable = useMemo(() => {
    const q = search.trim().toLowerCase();
    return available
      .filter((b) => b.query_id != null)
      .filter((b) => !q || b.table_name.toLowerCase().includes(q));
  }, [available, search]);

  const roleBadge = (role: CardRole) => {
    if (role === "source")
      return <Badge tone="brand">SOURCE QUERY</Badge>;
    if (role === "target")
      return <Badge tone="success">TARGET QUERY</Badge>;
    return <Badge tone="neutral">ADDED QUERY</Badge>;
  };

  // Group label position (midpoint of the group's first link).
  const groupLabels = useMemo(() => {
    const labels: {
      gid: string;
      x: number;
      y: number;
      fields: string[];
      mode: MatchMode;
      enabled: boolean;
    }[] = [];
    for (const [gid, ls] of groups.entries()) {
      const head = ls[0];
      const src = tables.find((t) => t.queryId === head.sourceQueryId);
      const tgt = tables.find((t) => t.queryId === head.targetQueryId);
      if (!src || !tgt) continue;
      const x1 = src.x + CARD_WIDTH;
      const y1 = fieldY(src, head.sourceField);
      const x2 = tgt.x;
      const y2 = fieldY(tgt, head.targetField);
      labels.push({
        gid,
        x: (x1 + x2) / 2,
        y: (y1 + y2) / 2,
        fields: ls.map((l) => l.sourceField),
        mode: head.matchMode,
        enabled: ls.every((l) => l.enabled),
      });
    }
    return labels;
  }, [groups, tables]);

  return (
    <div className="flex h-full min-h-[680px] flex-col">
      {/* Top bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line-tertiary pb-3">
        <h1 className="text-[15px] font-semibold text-ink-primary">
          Scope Relationship Builder
        </h1>
        <div className="flex items-center gap-2">
          <Button
            variant="brandSoft"
            onClick={runAiSuggest}
            disabled={aiBusy || tables.length < 2}
            title={
              tables.length < 2
                ? "Add at least two queries to the canvas"
                : "Suggest field relationships with AI"
            }
          >
            <IconSparkles size={14} />
            {aiBusy ? "Suggesting…" : "AI Suggest Fields"}
          </Button>
          <Button variant="primary" onClick={save} disabled={saving}>
            <IconDeviceFloppy size={14} />
            {saving ? "Saving…" : "Save Scope"}
          </Button>
          <Button
            variant="danger"
            onClick={deleteScope}
            disabled={deleting}
            title="Delete this scope map"
          >
            <IconTrash size={14} />
            {deleting ? "Deleting…" : "Delete Scope"}
          </Button>
        </div>
      </div>

      {(status || error) && (
        <div
          className={cn(
            "mt-2 rounded-md px-3 py-1.5 text-[12px]",
            error ? "bg-danger-bg text-danger" : "bg-brand-50 text-brand-700",
          )}
        >
          {error ?? status}
        </div>
      )}

      {/* Relationship Setup panel */}
      <div className="mt-3 rounded-lg border border-line-secondary bg-bg-secondary/30 p-3">
        <div className="flex items-center justify-between">
          <h2 className="text-[13px] font-semibold text-ink-primary">
            Relationship Setup
          </h2>
          <button
            type="button"
            onClick={() => setEnabled((v) => !v)}
            title={enabled ? "Scope enabled" : "Scope disabled"}
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

        <div className="mt-2 grid grid-cols-1 gap-3">
          <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wide text-ink-tertiary">
            Scope Name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="h-9 rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] font-medium normal-case text-ink-primary focus:border-brand-500 focus:outline-none"
              placeholder="e.g. Customer → Orders"
            />
          </label>
          <p className="text-[12px] normal-case tracking-normal text-ink-tertiary">
            Drag queries from the left onto the canvas, then connect a source
            field (right edge) to a target field (left edge) to build a
            relationship. Select a relationship to edit its field matches below.
          </p>
        </div>

        {/* Field Match grid for the selected relationship */}
        {sourceQueryId != null && targetQueryId != null && selectedGroup && (
          <div className="mt-3">
            <div className="mb-1 flex items-center justify-between">
              <h3 className="text-[12px] font-semibold text-ink-secondary">
                Field Matches
                {selectedHead && (
                  <span className="ml-1.5 font-normal text-ink-tertiary">
                    · {selectedHead.sourceTable ?? "Source"} →{" "}
                    {selectedHead.targetTable ?? "Target"}
                  </span>
                )}
              </h3>
              <label className="flex items-center gap-2 text-[12px] text-ink-secondary">
                Match Mode
                <select
                  value={pairMatchMode}
                  onChange={(e) => setPairMatchMode(e.target.value as MatchMode)}
                  className="h-7 rounded-md border border-line-secondary bg-bg-primary px-2 text-[12px]"
                >
                  <option value="all">All fields must match</option>
                  <option value="any">Any field can match</option>
                </select>
              </label>
            </div>
            <div className="overflow-hidden rounded-md border border-line-tertiary">
              <table className="w-full text-[12.5px]">
                <thead>
                  <tr className="bg-bg-secondary text-left text-[11px] uppercase tracking-wide text-ink-tertiary">
                    <th className="px-2 py-1.5 font-medium">Source Field</th>
                    <th className="px-2 py-1.5 font-medium">Target Field</th>
                    <th className="px-2 py-1.5 font-medium">Match Type</th>
                    <th className="px-2 py-1.5" />
                  </tr>
                </thead>
                <tbody>
                  {pairLinks.length === 0 && (
                    <tr>
                      <td
                        colSpan={4}
                        className="px-2 py-3 text-center text-ink-tertiary"
                      >
                        No field matches yet. Use “AI Suggest Fields” or “Add
                        Field Match”.
                      </td>
                    </tr>
                  )}
                  {pairLinks.map((l) => (
                    <tr key={l.localId} className="border-t border-line-tertiary">
                      <td className="px-2 py-1">
                        <select
                          value={l.sourceField}
                          onChange={(e) =>
                            updatePairFields(l.localId, {
                              sourceField: e.target.value,
                            })
                          }
                          className="h-7 w-full rounded border border-line-secondary bg-bg-primary px-1.5"
                        >
                          {sourceFields.map((f) => (
                            <option key={f} value={f}>
                              {f}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-2 py-1">
                        <select
                          value={l.targetField}
                          onChange={(e) =>
                            updatePairFields(l.localId, {
                              targetField: e.target.value,
                            })
                          }
                          className="h-7 w-full rounded border border-line-secondary bg-bg-primary px-1.5"
                        >
                          {targetFields.map((f) => (
                            <option key={f} value={f}>
                              {f}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-2 py-1 text-ink-secondary">
                        Exact
                        {l.createdByAi && (
                          <Badge tone="ai" className="ml-1.5">
                            AI
                          </Badge>
                        )}
                      </td>
                      <td className="px-2 py-1 text-right">
                        <button
                          type="button"
                          onClick={() => removeLink(l.localId)}
                          className="text-ink-tertiary hover:text-danger"
                          title="Remove field match"
                        >
                          <IconTrash size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-2 flex gap-2">
              <Button variant="secondary" size="sm" onClick={addFieldMatch}>
                <IconPlus size={13} />
                Add Field Match
              </Button>
              <Button
                variant="brandSoft"
                size="sm"
                onClick={runAiSuggest}
                disabled={aiBusy}
              >
                <IconSparkles size={13} />
                AI Suggest Fields
              </Button>
            </div>
          </div>
        )}
      </div>

      <div className="mt-3 flex min-h-0 flex-1 gap-3">
        {/* Left sidebar — query list */}
        <aside className="flex w-[320px] shrink-0 flex-col overflow-hidden rounded-lg border border-line-tertiary bg-bg-secondary/30">
          <div className="border-b border-line-tertiary p-3">
            <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-ink-tertiary">
              Drag Queries to Canvas
            </h3>
            <div className="flex items-center gap-2 rounded-md border border-line-secondary bg-bg-primary px-2.5">
              <IconSearch size={14} className="shrink-0 text-ink-tertiary" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search queries…"
                className="h-8 w-full bg-transparent text-[12.5px] text-ink-primary placeholder:text-ink-tertiary focus:outline-none"
              />
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            {filteredAvailable.length === 0 ? (
              <p className="text-[12px] text-ink-tertiary">
                {available.length === 0
                  ? "No saved queries in this project yet."
                  : "No queries match your search."}
              </p>
            ) : (
              <ul className="space-y-1.5">
                {filteredAvailable.map((b) => {
                  const on = placedIds.has(b.query_id as number);
                  return (
                    <li key={b.table_key}>
                      <div
                        draggable={!on}
                        onDragStart={(e) =>
                          e.dataTransfer.setData(
                            "text/scope-query",
                            String(b.query_id),
                          )
                        }
                        title={b.table_name}
                        className={cn(
                          "flex items-start gap-2 rounded-md border px-2 py-2 text-[12.5px]",
                          on
                            ? "border-line-tertiary bg-bg-secondary"
                            : "cursor-grab border-line-secondary bg-bg-primary hover:border-brand-500 hover:bg-brand-50 active:cursor-grabbing",
                        )}
                      >
                        <IconGripVertical
                          size={15}
                          className={cn(
                            "mt-0.5 shrink-0",
                            on ? "text-ink-tertiary/40" : "text-ink-tertiary",
                          )}
                        />
                        <span
                          className={cn(
                            "line-clamp-2 flex-1 leading-snug",
                            on ? "text-ink-secondary" : "text-ink-primary",
                          )}
                        >
                          {b.table_name}
                        </span>
                        {on && (
                          <span className="mt-0.5 shrink-0 text-[11px] font-medium text-ink-tertiary">
                            added
                          </span>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </aside>

        {/* Canvas */}
        <div className="relative flex min-w-0 flex-1 flex-col rounded-lg border border-line-tertiary bg-bg-primary">
          {/* Canvas controls */}
          <div className="flex items-center justify-between border-b border-line-tertiary px-2 py-1.5">
            <div className="flex items-center gap-3 text-[11px] text-ink-tertiary">
              <LegendItem label="Suggested" dashed />
              <LegendItem label="Accepted / Manual" />
              <LegendItem label="Disabled" faded />
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setZoom((z) => Math.max(MIN_ZOOM, z - 0.1))}
                className="rounded p-1 text-ink-secondary hover:bg-bg-secondary"
                title="Zoom out"
              >
                <IconZoomOut size={15} />
              </button>
              <span className="w-10 text-center text-[11px] text-ink-tertiary">
                {Math.round(zoom * 100)}%
              </span>
              <button
                type="button"
                onClick={() => setZoom((z) => Math.min(MAX_ZOOM, z + 0.1))}
                className="rounded p-1 text-ink-secondary hover:bg-bg-secondary"
                title="Zoom in"
              >
                <IconZoomIn size={15} />
              </button>
              <button
                type="button"
                onClick={fitToScreen}
                className="rounded p-1 text-ink-secondary hover:bg-bg-secondary"
                title="Fit to screen"
              >
                <IconMaximize size={15} />
              </button>
              <button
                type="button"
                onClick={resetLayout}
                className="rounded px-2 py-1 text-[11px] text-ink-secondary hover:bg-bg-secondary"
                title="Reset layout"
              >
                Reset
              </button>
            </div>
          </div>

          <div
            ref={viewportRef}
            className="relative min-h-[460px] flex-1 overflow-auto"
            onDragOver={(e) => e.preventDefault()}
            onDrop={onCanvasDrop}
          >
            <div
              style={{
                width: contentWidth * zoom,
                height: contentHeight * zoom,
              }}
            >
              <div
                ref={canvasRef}
                className={cn(
                  "relative origin-top-left",
                  panning ? "cursor-grabbing" : "cursor-grab",
                )}
                style={{
                  width: contentWidth,
                  height: contentHeight,
                  transform: `scale(${zoom})`,
                }}
                onMouseDown={onCanvasMouseDown}
                onClick={(e) => {
                  if (e.target === e.currentTarget) {
                    setSelectedGroup(null);
                    setPopup(null);
                    setPending(null);
                  }
                }}
              >
                {/* Relationship lines */}
                <svg
                  className="pointer-events-none absolute inset-0"
                  width={contentWidth}
                  height={contentHeight}
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
                      <path
                        d="M0,0 L8,3 L0,6 Z"
                        fill="var(--color-brand-500, #2563eb)"
                      />
                    </marker>
                    <marker
                      id="scope-arrow-dashed"
                      markerWidth="10"
                      markerHeight="10"
                      refX="8"
                      refY="3"
                      orient="auto"
                      markerUnits="strokeWidth"
                    >
                      <path d="M0,0 L8,3 L0,6 Z" fill="#9ca3af" />
                    </marker>
                  </defs>

                  {/* Saved/accepted/manual links (solid) */}
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
                    const d = `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
                    return (
                      <g key={l.localId}>
                        {/* Wide invisible hit area for easier clicking. */}
                        <path
                          d={d}
                          fill="none"
                          stroke="transparent"
                          strokeWidth={16}
                          style={{ pointerEvents: "stroke", cursor: "pointer" }}
                          onClick={(e) =>
                            openRelationshipPopup(l.matchGroupId, e)
                          }
                        />
                        <path
                          d={d}
                          fill="none"
                          stroke={
                            selected
                              ? "var(--color-brand-700, #1d4ed8)"
                              : "var(--color-brand-500, #2563eb)"
                          }
                          strokeWidth={selected ? 3 : 1.8}
                          opacity={l.enabled ? 1 : 0.35}
                          markerEnd="url(#scope-arrow)"
                          style={{ pointerEvents: "none" }}
                        />
                      </g>
                    );
                  })}

                  {/* Suggested (dashed preview) */}
                  {drawableSuggestions.map((s, i) => {
                    const src = tables.find((t) => t.queryId === s.query_id);
                    const tgt = tables.find(
                      (t) => t.queryId === s.target_query_id,
                    );
                    if (!src || !tgt) return null;
                    const x1 = src.x + CARD_WIDTH;
                    const y1 = fieldY(src, s.source_field);
                    const x2 = tgt.x;
                    const y2 = fieldY(tgt, s.target_field);
                    const mx = (x1 + x2) / 2;
                    return (
                      <path
                        key={`sug-${i}`}
                        d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
                        fill="none"
                        stroke="#9ca3af"
                        strokeWidth={1.6}
                        strokeDasharray="5 4"
                        markerEnd="url(#scope-arrow-dashed)"
                      />
                    );
                  })}
                </svg>

                {/* Relationship labels */}
                {groupLabels.map((g) => (
                  <button
                    key={g.gid}
                    type="button"
                    onClick={(e) => openRelationshipPopup(g.gid, e)}
                    className={cn(
                      "absolute -translate-x-1/2 -translate-y-1/2 rounded-md border px-1.5 py-0.5 text-[10.5px] shadow-sm",
                      g.gid === selectedGroup
                        ? "border-brand-500 bg-brand-50 text-brand-700"
                        : "border-line-secondary bg-bg-primary text-ink-secondary",
                      !g.enabled && "opacity-50",
                    )}
                    style={{ left: g.x, top: g.y }}
                  >
                    {g.fields.length > 1
                      ? `${g.fields.join(" + ")} · ${
                          g.mode === "all" ? "all match" : "any match"
                        }`
                      : g.fields[0]}
                  </button>
                ))}

                {/* Table cards */}
                {tables.map((t) => {
                  const role = roleOf(t.queryId);
                  return (
                    <div
                      key={t.queryId}
                      className={cn(
                        "absolute rounded-lg border bg-bg-primary shadow-sm",
                        role === "source"
                          ? "border-brand-300"
                          : role === "target"
                            ? "border-success/40"
                            : "border-line-secondary",
                      )}
                      style={{ left: t.x, top: t.y, width: CARD_WIDTH }}
                    >
                      <div
                        onMouseDown={(e) => onCardMouseDown(e, t)}
                        className="cursor-move rounded-t-lg bg-bg-secondary px-3 py-1.5"
                      >
                        <div className="flex items-center justify-between">
                          {roleBadge(role)}
                          <button
                            type="button"
                            onClick={() => removeTable(t.queryId)}
                            className="text-ink-tertiary hover:text-danger"
                            title="Remove from canvas"
                          >
                            <IconX size={14} />
                          </button>
                        </div>
                        <div
                          className="mt-0.5 truncate text-[13px] font-semibold text-ink-primary"
                          title={t.name}
                        >
                          {t.name}
                        </div>
                      </div>
                      <div>
                        {t.fields.length === 0 && (
                          <div className="px-3 py-2 text-[11px] text-ink-tertiary">
                            No fields detected
                          </div>
                        )}
                        {t.fields.map((f) => {
                          const isPendingSource =
                            pending &&
                            pending.queryId === t.queryId &&
                            pending.field === f;
                          return (
                            <div
                              key={f}
                              className="group/field relative flex items-center justify-between px-3 text-[12px] text-ink-secondary hover:bg-bg-secondary/60"
                              style={{ height: ROW_H }}
                            >
                              {/* target (incoming) hit area — left */}
                              <button
                                type="button"
                                title="Connect to this field"
                                onClick={() => onTargetDot(t, f)}
                                className="absolute -left-2 flex items-center justify-center"
                                style={{ width: 18, height: ROW_H, top: 0 }}
                              >
                                <span
                                  className="rounded-full border-2 border-brand-500 bg-bg-primary group-hover/field:bg-brand-200"
                                  style={{ width: DOT, height: DOT }}
                                />
                              </button>
                              <span className="truncate pl-1">{f}</span>
                              {/* source (outgoing) hit area — right */}
                              <button
                                type="button"
                                title="Connect from this field"
                                onClick={() => onSourceDot(t, f)}
                                className="absolute -right-2 flex items-center justify-center"
                                style={{ width: 18, height: ROW_H, top: 0 }}
                              >
                                <span
                                  className={cn(
                                    "rounded-full border-2 border-brand-500 group-hover/field:bg-brand-200",
                                    isPendingSource
                                      ? "bg-brand-500"
                                      : "bg-bg-primary",
                                  )}
                                  style={{ width: DOT, height: DOT }}
                                />
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}

                {tables.length === 0 && (
                  <div className="absolute inset-0 flex items-center justify-center p-8">
                    <p className="max-w-md text-center text-[13px] text-ink-tertiary">
                      Drag queries from the left panel onto the canvas, then
                      connect a source field (right edge) to a target field (left
                      edge). AI can suggest matching fields automatically.
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* AI suggestion panel */}
        <aside className="flex w-72 shrink-0 flex-col overflow-hidden rounded-lg border border-line-tertiary bg-bg-secondary/30">
          <div className="border-b border-line-tertiary p-3">
            <h3 className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-ink-tertiary">
              <IconSparkles size={13} /> AI Suggestions
            </h3>
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            {suggestions.length === 0 ? (
              <p className="text-[12px] text-ink-tertiary">
                Click “AI Suggest Fields” to find likely field relationships
                between the queries on your canvas.
              </p>
            ) : (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-medium text-ink-secondary">
                    AI found {suggestions.length} suggestion
                    {suggestions.length === 1 ? "" : "s"}
                  </span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={acceptAll}
                      className="text-[11px] font-medium text-brand-700 hover:underline"
                    >
                      Accept all
                    </button>
                    <button
                      type="button"
                      onClick={ignoreAll}
                      className="text-[11px] text-ink-tertiary hover:underline"
                    >
                      Ignore all
                    </button>
                  </div>
                </div>
                <ul className="space-y-2">
                  {suggestions.map((s, i) => {
                    const conf = confidenceLabel(s.confidence_score);
                    const key = `${suggestionKey(s)}-${i}`;
                    return (
                      <li
                        key={key}
                        className="rounded-md border border-line-secondary bg-bg-primary p-2"
                      >
                        <div className="text-[11px] text-ink-tertiary">
                          {s.source_table} → {s.target_table}
                        </div>
                        <div className="mt-0.5 flex items-center gap-1 text-[12px] text-ink-primary">
                          <span className="truncate font-medium">
                            {s.source_field}
                          </span>
                          <IconArrowNarrowRight
                            size={13}
                            className="shrink-0 text-ink-tertiary"
                          />
                          <span className="truncate font-medium">
                            {s.target_field}
                          </span>
                        </div>
                        <div className="mt-1 flex items-center gap-1.5">
                          <span className="text-[11px] text-ink-tertiary">
                            Confidence
                          </span>
                          <Badge tone={conf.tone}>{conf.text}</Badge>
                        </div>
                        {expanded === key && (
                          <div className="mt-1.5 space-y-0.5 rounded bg-bg-secondary/60 p-1.5 text-[11px] text-ink-secondary">
                            {s.rationale && <div>Reason: {s.rationale}</div>}
                            <div>
                              Match mode:{" "}
                              {s.match_mode === "all"
                                ? "all fields"
                                : "any field"}
                            </div>
                            {s.confidence_score != null && (
                              <div>
                                Score: {Math.round(s.confidence_score * 100)}%
                              </div>
                            )}
                          </div>
                        )}
                        <div className="mt-1.5 flex flex-wrap gap-2">
                          <button
                            type="button"
                            onClick={() => acceptSuggestion(s)}
                            className="text-[11px] font-medium text-brand-700 hover:underline"
                          >
                            Accept
                          </button>
                          <button
                            type="button"
                            onClick={() => ignoreSuggestion(s)}
                            className="text-[11px] text-ink-tertiary hover:underline"
                          >
                            Ignore
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              setExpanded((cur) => (cur === key ? null : key))
                            }
                            className="text-[11px] text-ink-tertiary hover:underline"
                          >
                            {expanded === key ? "Hide details" : "View details"}
                          </button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}

            {ignored.length > 0 && (
              <div className="mt-3 border-t border-line-tertiary pt-2">
                <button
                  type="button"
                  onClick={() => setShowIgnored((v) => !v)}
                  className="flex items-center gap-1 text-[11px] text-ink-tertiary hover:text-ink-secondary"
                >
                  <IconChevronDown
                    size={13}
                    className={cn(
                      "transition-transform",
                      showIgnored && "rotate-180",
                    )}
                  />
                  {showIgnored ? "Hide" : "Show"} ignored suggestions (
                  {ignored.length})
                </button>
                {showIgnored && (
                  <ul className="mt-2 space-y-1.5">
                    {ignored.map((s, i) => (
                      <li
                        key={`ign-${suggestionKey(s)}-${i}`}
                        className="flex items-center justify-between gap-2 rounded border border-line-tertiary bg-bg-primary/60 p-1.5 text-[11px]"
                      >
                        <span className="truncate text-ink-secondary">
                          {s.source_field} → {s.target_field}
                        </span>
                        <button
                          type="button"
                          onClick={() => restoreIgnored(s)}
                          className="shrink-0 font-medium text-brand-700 hover:underline"
                        >
                          Restore
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
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
              <Badge
                tone={selectedHead.createdByAi ? "ai" : "neutral"}
                className="ml-1.5"
              >
                {selectedHead.createdByAi ? "Accepted (AI)" : "Manual"}
              </Badge>
              {!selectedHead.enabled && (
                <Badge tone="warning" className="ml-1.5">
                  Disabled
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
            <Field label="Source Table">{selectedHead.sourceTable}</Field>
            <Field label="Target Table">{selectedHead.targetTable}</Field>
            <Field label="Direction">
              <span className="inline-flex items-center gap-1">
                Source <IconArrowNarrowRight size={13} /> Target
              </span>
            </Field>
            <Field label="Fields">
              {selectedLinks
                .map((l) => `${l.sourceField} → ${l.targetField}`)
                .join(", ")}
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

      {popup &&
        (() => {
          const popupLinks = groups.get(popup.gid) ?? [];
          const head = popupLinks[0];
          if (!head) return null;
          const conf = confidenceLabel(head.confidence);
          const sourceName = queryDisplayName(
            head.sourceQueryId,
            head.sourceTable,
          );
          const targetName = queryDisplayName(
            head.targetQueryId,
            head.targetTable,
          );
          return (
            <>
              {/* Outside-click backdrop (closes popup, then releases pointer). */}
              <div
                className="fixed inset-0 z-40"
                onClick={() => setPopup(null)}
                onMouseDown={() => setPopup(null)}
              />
              <div
                ref={popupRef}
                role="dialog"
                aria-label="Relationship details"
                className="fixed z-50 rounded-lg border border-line-secondary bg-bg-primary p-3 shadow-lg"
                style={{
                  left: popupPos?.left ?? popup.x + 8,
                  top: popupPos?.top ?? popup.y + 8,
                  visibility: popupPos ? "visible" : "hidden",
                  minWidth: 360,
                  maxWidth: "min(720px, calc(100vw - 48px))",
                  maxHeight: "calc(100vh - 32px)",
                  overflowY: "auto",
                }}
                onClick={(e) => e.stopPropagation()}
                onMouseDown={(e) => e.stopPropagation()}
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <h3 className="text-[13px] font-semibold text-ink-primary">
                    Relationship
                    {popupLinks.length > 1 && (
                      <Badge tone="brand" className="ml-1.5">
                        {popupLinks.length} fields
                      </Badge>
                    )}
                  </h3>
                  <button
                    type="button"
                    onClick={() => setPopup(null)}
                    className="text-ink-tertiary hover:text-ink-primary"
                    aria-label="Close"
                  >
                    <IconX size={15} />
                  </button>
                </div>

                <div className="space-y-2 text-[12px]">
                  <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
                    <Field label="Source">{sourceName}</Field>
                    <Field label="Target">{targetName}</Field>
                  </div>

                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-ink-tertiary">
                      Field mappings
                    </div>
                    <ul className="mt-0.5 space-y-0.5">
                      {popupLinks.map((l) => (
                        <li
                          key={l.localId}
                          className="flex items-center gap-1 text-ink-primary"
                        >
                          <span className="min-w-0 break-words font-medium [overflow-wrap:anywhere]">
                            {l.sourceField}
                          </span>
                          <IconArrowNarrowRight
                            size={13}
                            className="shrink-0 text-ink-tertiary"
                          />
                          <span className="min-w-0 break-words font-medium [overflow-wrap:anywhere]">
                            {l.targetField}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
                    <Field label="Match Mode">
                      {head.matchMode === "all"
                        ? "All fields must match"
                        : "Any field can match"}
                    </Field>
                    <Field label="Direction">
                      <span className="inline-flex items-center gap-1">
                        Source <IconArrowNarrowRight size={13} /> Target
                      </span>
                    </Field>
                    <Field label="Status">
                      {head.enabled ? "Enabled" : "Disabled"}
                    </Field>
                    <Field label="Origin">
                      <span className="inline-flex items-center gap-1.5">
                        {head.createdByAi ? "AI-generated" : "Manual"}
                        {head.createdByAi && (
                          <Badge tone={conf.tone}>{conf.text}</Badge>
                        )}
                      </span>
                    </Field>
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => {
                      setSelectedGroup(popup.gid);
                      setPopup(null);
                    }}
                  >
                    <IconPencil size={13} />
                    Edit
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => reverseGroup(popup.gid)}
                  >
                    <IconArrowsExchange size={13} />
                    Reverse Direction
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => deleteGroup(popup.gid)}
                  >
                    <IconTrash size={13} />
                    Delete Relationship
                  </Button>
                </div>
              </div>
            </>
          );
        })()}

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
      <div className="whitespace-normal break-words text-ink-primary [overflow-wrap:anywhere]">
        {children ?? "—"}
      </div>
    </div>
  );
}

function LegendItem({
  label,
  dashed,
  faded,
}: {
  label: string;
  dashed?: boolean;
  faded?: boolean;
}) {
  return (
    <span className="flex items-center gap-1">
      <svg width="20" height="6" className={cn(faded && "opacity-40")}>
        <line
          x1="0"
          y1="3"
          x2="20"
          y2="3"
          stroke={dashed ? "#9ca3af" : "var(--color-brand-500, #2563eb)"}
          strokeWidth="2"
          strokeDasharray={dashed ? "4 3" : undefined}
        />
      </svg>
      {label}
    </span>
  );
}
