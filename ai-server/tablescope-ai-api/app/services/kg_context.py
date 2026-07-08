"""Render the platform's Knowledge Graph context into an LLM prompt block.

The platform-api collects a compact, authorized Knowledge Graph summary
(``collect_knowledge_graph_ai_context``) and sends it on AI requests as
``knowledge_graph_context``. This module turns that structured dict into a
prioritized, human-readable block the dashboard/query prompts can embed so
generation targets the validated risks, gaps, measured KPIs, and governing
documents the graph surfaces — instead of merely summarizing tables.

Priority order (most decision-critical first) follows the plan:
risks -> gaps -> opportunities -> measured KPIs -> recommended KPIs ->
governing documents -> reference guidance -> processes/entities -> lineage.

Reference Library guidance is rendered as guidance only and explicitly marked
as *not* a queryable data source.
"""

from __future__ import annotations

from typing import Any


def _as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return []


def _clean(text: Any, limit: int = 240) -> str:
    s = str(text or "").strip().replace("\n", " ")
    return s[:limit]


def _related_suffix(item: dict[str, Any]) -> str:
    """Compact '(KPIs: a, b | docs: c)' suffix from a finding's relations."""
    parts: list[str] = []
    kpis = [str(k) for k in (item.get("related_kpis") or []) if k]
    docs = [str(d) for d in (item.get("related_documents") or []) if d]
    ds = [str(d) for d in (item.get("related_datasources") or []) if d]
    if kpis:
        parts.append("KPIs: " + ", ".join(kpis[:4]))
    if docs:
        parts.append("docs: " + ", ".join(docs[:3]))
    if ds:
        parts.append("data: " + ", ".join(ds[:3]))
    return f" ({' | '.join(parts)})" if parts else ""


def _finding_lines(items: list[dict[str, Any]], cap: int) -> list[str]:
    lines: list[str] = []
    for it in items[:cap]:
        title = _clean(it.get("title"), 120)
        if not title:
            continue
        sev = str(it.get("severity") or "").strip()
        sev_tag = f"[{sev}] " if sev else ""
        summary = _clean(it.get("summary"), 220)
        summary_part = f" — {summary}" if summary else ""
        lines.append(f"  - {sev_tag}{title}{summary_part}{_related_suffix(it)}")
    return lines


def format_knowledge_graph_context(kg: dict[str, Any] | None, *, cap: int = 8) -> str:
    """Return a prioritized prompt block for a KG context dict, or "" if empty.

    ``cap`` limits how many items are rendered per section to keep the prompt
    bounded; the platform has already ranked each list highest-confidence first.
    """
    if not isinstance(kg, dict):
        return ""

    sections: list[str] = []

    def add(label: str, key: str, *, kpi: bool = False) -> None:
        items = _as_list(kg.get(key))
        if not items:
            return
        if kpi:
            lines = []
            for it in items[:cap]:
                title = _clean(it.get("title"), 120)
                if not title:
                    continue
                measured_by = [str(m) for m in (it.get("measured_by") or []) if m]
                mb = (
                    f" (measured by: {', '.join(measured_by[:3])})"
                    if measured_by
                    else ""
                )
                summary = _clean(it.get("summary"), 180)
                sp = f" — {summary}" if summary else ""
                lines.append(f"  - {title}{sp}{mb}{_related_suffix(it)}")
        else:
            lines = _finding_lines(items, cap)
        if lines:
            sections.append(f"{label}:\n" + "\n".join(lines))

    # Context priority (most decision-critical first).
    add("Validated RISKS to monitor", "risks")
    add("GAPS / missing coverage (create gap widgets; never invent SQL)", "gaps")
    add("OPPORTUNITIES", "opportunities")
    add("WARNINGS / anomalies", "warnings")
    add("MEASURED KPIs (have a query/dashboard — visualize these)", "measured_kpis", kpi=True)
    add(
        "RECOMMENDED KPIs (no measuring query yet — surface as gap/recommendation, "
        "do NOT fabricate SQL)",
        "recommended_kpis",
        kpi=True,
    )
    add("GOVERNING documents / policies", "governing_documents")

    # Reference guidance — explicitly guidance only, never a data source.
    ref = _as_list(kg.get("reference_guidance"))
    if ref:
        lines = []
        for it in ref[:cap]:
            title = _clean(it.get("title"), 120)
            if not title:
                continue
            summary = _clean(it.get("summary"), 160)
            sp = f" — {summary}" if summary else ""
            lines.append(f"  - {title}{sp}")
        if lines:
            sections.append(
                "REFERENCE LIBRARY guidance (authoritative standards — NOT a "
                "queryable data source; use only as target lines/benchmarks when "
                "the value is explicit):\n" + "\n".join(lines)
            )

    # Processes & entities (relationship context).
    for label, key in (
        ("Key PROCESSES", "processes"),
        ("Key ENTITIES", "entities"),
    ):
        items = _as_list(kg.get(key))
        names = [_clean(it.get("title"), 80) for it in items[:cap] if it.get("title")]
        if names:
            sections.append(f"{label}: " + ", ".join(names))

    # Lineage — how existing queries/dashboards already measure things.
    ql = _as_list(kg.get("query_lineage"))
    if ql:
        lines = []
        for it in ql[:cap]:
            q = _clean(it.get("query"), 80)
            tgt = _clean(it.get("target"), 80)
            rel = _clean(it.get("relationship"), 40) or "relates to"
            if q and tgt:
                lines.append(f"  - {q} {rel} {tgt}")
        if lines:
            sections.append("QUERY lineage (existing measurement):\n" + "\n".join(lines))

    dl = _as_list(kg.get("dashboard_lineage"))
    if dl:
        lines = []
        for it in dl[:cap]:
            d = _clean(it.get("dashboard"), 80)
            tgt = _clean(it.get("target"), 80)
            rel = _clean(it.get("relationship"), 40) or "visualizes"
            if d and tgt:
                lines.append(f"  - {d} {rel} {tgt}")
        if lines:
            sections.append("DASHBOARD lineage (existing visualization):\n" + "\n".join(lines))

    if not sections:
        return ""

    return (
        "Knowledge Graph context (validated, project-authorized evidence — use "
        "this to decide WHAT matters before choosing charts/SQL; prioritize "
        "risks, gaps, opportunities and measured KPIs; treat Reference Library "
        "as guidance only, never as a data source):\n\n"
        + "\n\n".join(sections)
    )
