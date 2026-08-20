"""Prompt-block builders for the intelligence plan."""

from app.core.config import settings


def _fit_plan_prompt(
    prompt: str,
    system_prompt: str,
    *,
    max_model_len: int | None = None,
    max_tokens: int = 2048,
    chars_per_token: float = 3.5,
) -> str:
    """Trim the front of the user prompt so system + prompt + output fit vLLM.

    ai-server has no tokenizer, so this is a conservative character-based
    estimate, not an exact count -- chars_per_token errs low (English text is
    typically ~4 chars/token) so the trim is never too small. Reserves room
    for both the system prompt and ``max_tokens`` of output; callers must
    pass the SAME ``max_tokens`` to ``llm_client.generate`` so the reserved
    budget is actually honored request-side, not just assumed here.

    Shared by every planner prompt (single-table/relationship analyses,
    dashboard suggestion) that can grow large enough on a big project to
    starve a reasoning model of room to answer -- confirmed live: a project
    with an inflated context (many saved queries/dashboards/scopes/junk
    datasources) filled vLLM's whole context window with prompt, leaving a
    reasoning model ~120 completion tokens -- enough for its reasoning
    channel but none for its actual answer, silently returning 0 results
    every time.
    """
    max_model_len = max_model_len or settings.vllm_max_model_len
    reserve_tokens = max_tokens + int(len(system_prompt) / chars_per_token) + 40
    token_budget = max(0, max_model_len - reserve_tokens)
    char_budget = int(token_budget * chars_per_token)
    if len(prompt) <= char_budget:
        return prompt
    # Keep the instruction/output-format tail and drop excess context from the front.
    truncated = prompt[-char_budget:]
    idx = truncated.find("\n")
    if idx != -1 and idx < 120:
        truncated = truncated[idx + 1 :]
    return "[context truncated for length]\n\n" + truncated


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
        # find_relationship_candidates enriches every candidate with
        # join_key_pairs -- the entity key PLUS any shared reporting-period
        # column (e.g. AccountNumber AND Month). Rendering only the single
        # left_join_key/right_join_key pair here, as this used to, silently
        # dropped the period equality: the LLM would join on the entity key
        # alone and fan every month's rows out against every other month for
        # the same entity. Falls back to the singular fields for hints that
        # were never enriched (e.g. hand-built test fixtures).
        raw_pairs = h.get("join_key_pairs") or []
        key_pairs = [
            (str(p["left"]), str(p["right"]))
            for p in raw_pairs
            if isinstance(p, dict) and p.get("left") and p.get("right")
        ]
        if not key_pairs:
            lkey = h.get("left_join_key") or ""
            rkey = h.get("right_join_key") or ""
            if lkey and rkey:
                key_pairs = [(lkey, rkey)]
        if not (left and right and key_pairs):
            continue
        rel = h.get("relationship_type") or "unknown"
        reason = str(h.get("confidence_reason") or "")[:60]
        risk = h.get("row_multiplication_risk") or "unknown"
        conf_str = f"{_conf(h):.2f}" if h.get("join_confidence") is not None else "n/a"
        on_clause = " AND ".join(
            f'"{left}"."{lk}" = "{right}"."{rk}"' for lk, rk in key_pairs
        )
        compound_note = (
            " -- compound key, join on ALL of these together"
            if len(key_pairs) > 1
            else ""
        )
        rows.append(
            f"  - {on_clause} "
            f"(rel={rel}, conf={conf_str}, risk={risk}"
            f"{f'; {reason}' if reason else ''}){compound_note}"
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
        "- When a pair's evidence lists more than one equality (marked "
        "'compound key'), the JOIN's ON clause MUST include ALL of them "
        "together with AND, never just one. Dropping one (e.g. joining on an "
        "entity key alone when a shared period column is also listed) fans "
        "each row out across every value of the omitted key instead of "
        "aligning them.\n"
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
