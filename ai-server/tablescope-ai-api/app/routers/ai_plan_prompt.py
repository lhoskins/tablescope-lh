"""Prompt-block builders for the intelligence plan."""


def _build_kg_hypothesis_lines(kg: dict) -> str:
    """Render the platform's Knowledge Graph digest as hypotheses to test.

    The graph's risk/gap/opportunity/warning nodes are themselves AI-derived
    from the project's documents, so the framing matters: every item is a
    HYPOTHESIS the planner should validate, quantify, or refute with real SQL
    — never assert one as a finding without a query result behind it.
    Returns "" when the graph contributes nothing, leaving the prompt
    unchanged for projects without a graph.
    """
    if not kg:
        return ""

    def _fmt(items: list | None, cap: int = 5) -> list[str]:
        lines: list[str] = []
        for it in (items or [])[:cap]:
            if not isinstance(it, dict):
                continue
            title = str(it.get("title") or "").strip()
            if not title:
                continue
            severity = str(it.get("severity") or "").strip()
            summary = str(it.get("summary") or "").strip()[:160]
            line = f"  - {title}"
            if severity:
                line += f" [{severity}]"
            if summary:
                line += f": {summary}"
            lines.append(line)
        return lines

    sections: list[str] = []
    for key, label in (
        ("risks", "Risks"),
        ("warnings", "Warnings"),
        ("gaps", "Gaps"),
        ("opportunities", "Opportunities"),
    ):
        lines = _fmt(kg.get(key))
        if lines:
            sections.append(f"{label}:\n" + "\n".join(lines))
    kpi_lines = _fmt(kg.get("recommended_kpis"))
    if kpi_lines:
        sections.append(
            "Recommended-but-unmeasured KPIs (no query or dashboard measures "
            "these yet):\n" + "\n".join(kpi_lines)
        )
    if not sections:
        return ""
    return (
        "\nKNOWLEDGE GRAPH HYPOTHESES — the project's knowledge graph "
        "surfaces the items below, derived from its documents and metadata. "
        "Treat every item as a HYPOTHESIS, not an established fact: where the "
        "allowed tables contain relevant data, plan analyses whose SQL "
        "validates, quantifies, or refutes the item against the real data — "
        "for example, measure a recommended-but-unmeasured KPI, or quantify "
        "the magnitude and trend of a flagged risk. NEVER assert a graph item "
        "as a finding without a query result behind it. Ignore items the "
        "available data cannot address.\n"
        "These hypotheses are ADDITIVE context only — they must NOT displace "
        "the required analysis mix. Still cover risks, trends, opportunities, "
        "AND relationship analyses (single-table column pairs, and multi-table "
        "joins whenever RELATIONSHIP EVIDENCE is listed). Where a hypothesis "
        "spans two related tables, prefer testing it WITH a relationship "
        "analysis. Dedicate at most half of the proposed analyses to graph "
        "hypotheses.\n"
        + "\n\n".join(sections)
        + "\n"
    )


def _build_relationship_floor_line(has_relationship_evidence: bool, granularity: int) -> str:
    """A hard floor for complex analyses so advisory context can't crowd them out.

    Relationship (and especially multi-table) analyses are the most valuable
    output of the planner and the first thing a longer prompt or extra
    advisory sections (documents, knowledge-graph hypotheses) tends to
    displace. When verified join evidence exists, make them required output
    rather than an optional extra.
    """
    if not has_relationship_evidence:
        return (
            "Always look for the single-table relationship analyses described "
            "below where the data supports them — they are part of the "
            "required mix, not an optional extra.\n"
        )
    minimum = "TWO" if granularity >= 4 else "ONE"
    return (
        "The RELATIONSHIP EVIDENCE list above is non-empty: include at least "
        f"{minimum} multi-table relationship analys"
        f"{'es' if minimum == 'TWO' else 'is'} using those verified joins, in "
        "addition to the single-table relationship analyses described below. "
        "These complex analyses are REQUIRED output whenever the data "
        "supports them — no other section of this prompt (documents, "
        "knowledge-graph hypotheses, depth guidance) may displace them. "
        "Write each one as an EXPLICIT JOIN (FROM table1 JOIN table2 ON the "
        "exact keys listed in the evidence) with every column qualified by "
        "its table name — NEVER satisfy this requirement by selecting "
        "another table's column inside a single-table query.\n"
    )


def _build_relationship_hint_lines(hints: list[dict]) -> str:
    """Render verified join candidates the platform discovered.

    Only relationships supplied here (from scope metadata or exact matching
    keys) may be joined; everything else stays single-table. Returns "" when
    there is no relationship evidence, which leaves single-table behaviour
    completely unchanged.
    """
    def _conf(h: dict) -> float:
        c = h.get("join_confidence")
        return float(c) if isinstance(c, int | float) else 0.0

    rows: list[str] = []
    # Strongest evidence first: the prompt tells the planner to prefer the
    # highest-confidence pairs, and if a response is ever truncated the
    # weakest pairs are the ones nearest the cut.
    for h in sorted(hints, key=_conf, reverse=True):
        left = h.get("left_table") or ""
        right = h.get("right_table") or ""
        lkey = h.get("left_join_key") or ""
        rkey = h.get("right_join_key") or ""
        if not (left and right and lkey and rkey):
            continue
        rel = h.get("relationship_type") or "unknown"
        reason = str(h.get("confidence_reason") or "")[:60]
        risk = h.get("row_multiplication_risk") or "unknown"
        conf_str = f"{_conf(h):.2f}" if h.get("join_confidence") is not None else "n/a"
        rows.append(
            f'  - "{left}"."{lkey}" = "{right}"."{rkey}" '
            f"(rel={rel}, conf={conf_str}, risk={risk}"
            f"{f'; {reason}' if reason else ''})"
        )
    if not rows:
        return ""
    return (
        "\nRELATIONSHIP EVIDENCE — verified joins your cross-table analyses "
        "MUST build on (the one exception to the single-table rule below):\n"
        + "\n".join(rows) + "\n"
        "Multi-table join rules:\n"
        "- JOIN a pair of tables ONLY when the exact pair and keys appear in "
        "the list above. Never invent a join or join on matching names that "
        "are not listed here.\n"
        "- At most TWO tables per analysis. Write ONE flat SELECT (no "
        "subqueries, no derived tables): JOIN the two tables directly on the "
        "listed keys, GROUP BY label columns from the entity/master side, and "
        "aggregate (SUM/AVG/COUNT) ONLY numeric columns from the detail/fact "
        "side. Never SUM or AVG a master-side numeric column after the join — "
        "the row fan-out inflates it.\n"
        '- Alias both tables and table-qualify every column (e.g. '
        'i."DefectQty", s."Region").\n'
        "- When row_multiplication_risk is high, GROUP BY the join key itself "
        "and aggregate measures from only one side — or skip the pair.\n"
        "- A join must produce a genuinely cross-table insight (e.g. "
        "high-spend suppliers with elevated defect rates, single-source "
        "dependency, concentration risk) — not a restated single-table "
        "metric.\n"
    )
