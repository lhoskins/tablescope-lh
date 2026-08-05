"""Deterministic SQL shaping for planner output: join repair, qualification
and GROUP BY completion."""

import re
from typing import Any

# Table references in FROM/JOIN clauses; the negative lookahead skips function
# calls so the FROM inside EXTRACT(... FROM ...) is not counted (same pattern
# the SQL validator uses).
_SQL_TABLE_REF_RE = re.compile(r'(?:FROM|JOIN)\s+"?(\w+)"?(?![\w(])', re.IGNORECASE)


def _sql_table_count(sql: str, allowed_tables: list[str]) -> int:
    """Number of distinct allowed tables a query reads — ≥2 means cross-table."""
    allowed = {t.upper() for t in allowed_tables}
    return len(
        {m.upper() for m in _SQL_TABLE_REF_RE.findall(sql) if m.upper() in allowed}
    )


_JOIN_TYPE_RE = r'(?:LEFT(?:\s+OUTER)?|RIGHT(?:\s+OUTER)?|FULL(?:\s+OUTER)?|INNER|CROSS)'

# Match a single JOIN clause and its optional ON clause, stopping before the next
# JOIN/WHERE/GROUP/HAVING/ORDER/LIMIT or end of statement.
# Group 1 = optional join-type keyword (INNER, LEFT OUTER, ...), group 2 = table,
# group 3 = alias, group 4 = existing ON clause.
_JOIN_CLAUSE_RE = re.compile(
    rf'\b(?:({_JOIN_TYPE_RE})\s+)?JOIN\s+("?\w+"?)(?:\s+(?:AS\s+)?("?\w+"?))?\s*(?:ON\b([^,]+?))?'
    rf'(?=\s+(?:{_JOIN_TYPE_RE}\s+)?JOIN\b|WHERE\b|GROUP\s+BY\b|HAVING\b|ORDER\s+BY\b|LIMIT\b|;|$)',
    re.IGNORECASE | re.DOTALL,
)

# Declarations before the current JOIN: FROM table [alias] and JOIN table [alias].
# The last one before the JOIN is the left side of that join.  The alias group
# excludes reserved SQL keywords so ``FROM t JOIN u`` is parsed as two sources.
_SOURCE_DECL_RE = re.compile(
    r'(?:FROM|JOIN)\s+("?\w+"?)(?:\s+(?:AS\s+)?((?!(?:JOIN|ON|WHERE|GROUP|ORDER|'
    r'LIMIT|HAVING|FROM|SELECT|INNER|LEFT|RIGHT|FULL|CROSS)\b)"?\w+"?))?',
    re.IGNORECASE,
)

# A single equality in an ON clause, possibly table-qualified/quoted.
_EQ_RE = re.compile(
    r'("?\w+"?)\s*(?:\.\s*("?\w+"?))?\s*=\s*("?\w+"?)\s*(?:\.\s*("?\w+"?))?',
    re.IGNORECASE,
)


def _strip_quotes(s: str) -> str:
    return s.strip().strip('"')


def _is_inside_parens(text: str, pos: int) -> bool:
    """True if pos is inside an unclosed open parenthesis (function/subquery)."""
    return text[:pos].count("(") != text[:pos].count(")")


def _on_has_pair(on_text: str, left_col: str, right_col: str) -> bool:
    """Check whether an ON clause already contains a real cross-table equality.

    A condition like ``WorkCenterID = WorkCenterID`` (same bare column on both
    sides, or the same table qualifier on both sides) is a tautology, not a join.
    """
    want = {_strip_quotes(left_col).lower(), _strip_quotes(right_col).lower()}
    for m in _EQ_RE.finditer(on_text):
        c1 = _strip_quotes(m.group(2) or m.group(1) or "").lower()
        c2 = _strip_quotes(m.group(4) or m.group(3) or "").lower()
        if {c1, c2} != want:
            continue
        q1 = _strip_quotes(m.group(1) or "").lower() if m.group(2) else ""
        q2 = _strip_quotes(m.group(3) or "").lower() if m.group(4) else ""
        # Same bare column or same qualifier on both sides is not a cross-table join.
        if not q1 and not q2 and c1 == c2:
            continue
        if q1 and q2 and q1 == q2:
            continue
        return True
    return False


def _join_conditions_for_hint(
    hint: dict[str, Any], left_qual: str, right_qual: str
) -> list[str]:
    """Build ON equality terms from a relationship hint's composite key pairs."""
    pairs: list[tuple[str, str]] = []
    join_key_pairs = hint.get("join_key_pairs")
    if isinstance(join_key_pairs, list):
        for p in join_key_pairs:
            if not isinstance(p, dict):
                continue
            # Skip period equality for weekly/monthly mismatched pairs.
            if hint.get("grain_mismatch") and p.get("is_period"):
                continue
            lcol = p.get("left")
            rcol = p.get("right")
            if lcol and rcol:
                pairs.append((lcol, rcol))
    if not pairs and hint.get("left_join_key") and hint.get("right_join_key"):
        pairs.append((hint["left_join_key"], hint["right_join_key"]))
    return [f'{left_qual}."{lcol}" = {right_qual}."{rcol}"' for (lcol, rcol) in pairs]


def _qualify_shared_columns(
    sql: str, left_qual: str, right_qual: str, hint: dict[str, Any]
) -> str:
    """Prefix unqualified shared column references with the left table qualifier.

    When two joined tables share a column name (e.g. WorkCenterID or WeekStart),
    unqualified references in SELECT/GROUP BY/ORDER BY/WHERE are ambiguous.  This
    is a deterministic rewrite; it assumes the left side of the join owns the
    reference, which is safe because the ON clause enforces equality.
    """
    pairs = hint.get("join_key_pairs") or []
    if not isinstance(pairs, list):
        pairs = []
    shared = set()
    for p in pairs:
        if isinstance(p, dict) and p.get("left") == p.get("right"):
            shared.add(str(p["left"]))
    if not shared and hint.get("left_join_key") == hint.get("right_join_key"):
        shared.add(str(hint["left_join_key"]))
    if not shared:
        return sql

    out = sql
    for col in sorted(shared, key=len, reverse=True):
        # Replace bare column references that are not already table-qualified or
        # inside a quoted identifier.  Use a function to avoid lookbehind length
        # limits across Python versions.
        pattern = re.compile(rf'(?<![\w."]){re.escape(col)}(?![\w."])', re.IGNORECASE)

        def _repl(m: re.Match[str]) -> str:
            # Double-check the char before the match is not a dot or quote.
            start = m.start()
            if start > 0 and out[m.start() - 1] in '."':
                return m.group(0)
            return f'{left_qual}."{col}"'

        out = pattern.sub(_repl, out)
    return out


def _qualify_bare_shared_columns(
    sql: str, table_schema: list[dict] | None = None
) -> str:
    """Qualify unqualified shared columns in a single-join query.

    After the ON clause has been injected, the SELECT/GROUP BY/ORDER BY/WHERE
    clauses may still contain bare references to columns that exist on both sides
    of the join (e.g. WeekStart, WorkCenterID, SiteID).  Teiid rejects those as
    ambiguous.  This function finds the one FROM ... JOIN ... ON ... block,
    determines the left and right qualifiers, and prefixes any unqualified shared
    columns with the left qualifier.  It is safe because the ON clause enforces
    equality.
    """
    # Locate the FROM ... JOIN ... ON ... block, stopping at the next major
    # clause keyword or end of statement.
    m = re.search(
        r'\bFROM\b\s*(.+?)\s*\bJOIN\b\s*(.+?)\s*\bON\b\s*(.+?)'
        r'(?=\s+\b(?:WHERE|GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT)\b|;|$)',
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return sql

    from_part = m.group(1)
    join_part = m.group(2)
    on_part = m.group(3)

    # Resolve qualifiers from the source declarations.
    from_sources = list(_SOURCE_DECL_RE.finditer("FROM " + from_part))
    join_sources = list(_SOURCE_DECL_RE.finditer("JOIN " + join_part))
    if not from_sources or not join_sources:
        return sql

    left_match = from_sources[-1]
    left_raw = left_match.group(2) or left_match.group(1) or ""
    left_table = _strip_quotes(left_match.group(1) or "")
    right_match = join_sources[-1]
    right_table = _strip_quotes(right_match.group(1) or "")
    left_qual = _strip_quotes(left_raw)

    # Discover shared column names from the ON clause equalities.
    shared: set[str] = set()
    for eq in _EQ_RE.finditer(on_part):
        c1 = _strip_quotes(eq.group(2) or eq.group(1) or "")
        c2 = _strip_quotes(eq.group(4) or eq.group(3) or "")
        if c1.lower() == c2.lower():
            shared.add(c1)

    # Also include any column that exists in both tables according to the
    # supplied schema.  This catches shared keys the model uses in SELECT/GROUP
    # BY but did not place in the ON clause.
    if table_schema:
        cols_by_table: dict[str, set[str]] = {}
        for entry in table_schema:
            t = _strip_quotes(str(entry.get("table") or "")).lower()
            cols = entry.get("columns") or []
            if t not in cols_by_table:
                cols_by_table[t] = set()
            for col in cols:
                name = _strip_quotes(str(col.get("name") or ""))
                if name:
                    cols_by_table[t].add(name.lower())
        left_cols = cols_by_table.get(left_table.lower(), set())
        right_cols = cols_by_table.get(right_table.lower(), set())
        shared.update(
            c
            for c in left_cols & right_cols
            if c
        )

    if not shared:
        return sql

    def _inside_single_quotes(text: str, pos: int) -> bool:
        """True when pos is inside an unclosed single-quoted string literal."""
        count = 0
        for i, ch in enumerate(text[:pos]):
            if ch == "'" and (i == 0 or text[i - 1] != "\\"):
                count += 1
        return count % 2 == 1

    def _prev_token_is_as(text: str, pos: int) -> bool:
        """True when the token immediately before pos is ``AS`` (an alias)."""
        return bool(re.search(r"\bAS\s+$", text[:pos], re.IGNORECASE))

    def _rewrite(text: str) -> str:
        out = text
        for col in sorted(shared, key=len, reverse=True):
            # Match bare identifiers or double-quoted identifiers that are not
            # already table-qualified.  Shared columns inside string literals or
            # ``AS`` aliases are left unchanged.
            pattern = re.compile(
                rf'(?<![\w.])"{re.escape(col)}"(?![\w.])|'
                rf'(?<![\w."]){re.escape(col)}(?![\w."])',
                re.IGNORECASE,
            )

            def _repl(match: re.Match[str]) -> str:
                start = match.start()
                if _inside_single_quotes(out, start) or _prev_token_is_as(out, start):
                    return match.group(0)
                return f'{left_qual}."{col}"'

            out = pattern.sub(_repl, out)
        return out

    return _rewrite(sql)


def _split_select_expressions(select_body: str) -> list[str]:
    """Split a SELECT list on top-level commas, respecting parentheses."""
    depth = 0
    parts: list[str] = []
    current: list[str] = []
    for ch in select_body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    parts.append("".join(current).strip())
    return parts


def _normalize_expr(expr: str) -> str:
    """Lowercase and remove double quotes for comparison."""
    return re.sub(r'"', "", expr).strip().lower()


def _ensure_group_by(sql: str) -> str:
    """Make sure every non-aggregate SELECT expression appears in GROUP BY.

    The small model frequently emits aggregate queries that group by only the
    first dimension (e.g. ``GROUP BY WeekStart``) while also selecting
    ``WorkCenterID`` and ``SiteID``.  Teiid rejects the ungrouped columns.
    We extend or replace the GROUP BY list with all non-aggregate SELECT items.
    """
    has_group_by = re.search(r"\bGROUP\s+BY\b", sql, re.IGNORECASE) is not None
    if (
        not re.search(r"\b(?:AVG|SUM|COUNT|MIN|MAX)\s*\(", sql, re.IGNORECASE)
        and not has_group_by
    ):
        return sql

    select_match = re.search(
        r"SELECT\s+(.*?)\s+FROM\s", sql, re.IGNORECASE | re.DOTALL
    )
    if not select_match:
        return sql
    select_body = select_match.group(1)
    parts = _split_select_expressions(select_body)

    agg_re = re.compile(r"\b(?:AVG|SUM|COUNT|MIN|MAX)\s*\(", re.IGNORECASE)
    required_exprs: list[str] = []
    for part in parts:
        if agg_re.search(part):
            continue
        expr = re.sub(r'\s+AS\s+["\[]?\w+["\]]?\s*$', "", part, flags=re.IGNORECASE).strip()
        if expr and expr != "*":
            required_exprs.append(expr)

    if not required_exprs:
        return sql

    # Existing GROUP BY, if any.
    group_match = re.search(
        r"\bGROUP\s+BY\b(.+?)(?=\s+\b(?:HAVING|ORDER\s+BY|LIMIT)\b|;|$)",
        sql,
        re.IGNORECASE | re.DOTALL,
    )

    existing: list[str] = []
    if group_match:
        existing = _split_select_expressions(group_match.group(1).strip())

    existing_norm = {_normalize_expr(e) for e in existing}
    missing = [
        e
        for e in required_exprs
        if _normalize_expr(e) not in existing_norm
        and not (e.strip().isdigit() and int(e.strip()) <= len(parts))
    ]

    # If the GROUP BY is only positional (e.g. ``GROUP BY 1``), replace it with
    # the full expression list. Otherwise extend it with any missing columns.
    if existing and all(e.strip().isdigit() for e in existing):
        new_group = required_exprs
    else:
        new_group = existing + missing

    if not new_group:
        new_group = ["1"]

    group_clause = ", ".join(new_group)
    if group_match:
        start = group_match.start()
        end = group_match.end()
        sql = sql[:start] + f"GROUP BY {group_clause}" + sql[end:]
    else:
        order_match = re.search(r"\s+\bORDER\s+BY\b", sql, re.IGNORECASE)
        if order_match:
            sql = (
                sql[: order_match.start()]
                + f" GROUP BY {group_clause}"
                + sql[order_match.start() :]
            )
        else:
            sql = sql + f" GROUP BY {group_clause}"
    return sql


def _ensure_join_on_clause(
    sql: str, relationship_hints: list[dict], allowed_tables: list[str]
) -> str:
    """Inject or correct ON clauses for joins that use a listed evidence pair.

    The platform's relationship evidence already contains the exact join keys
    (including shared period columns for time-series joins).  When a planned
    join references two allowed tables and a hint exists for that pair, the SQL
    is rewritten so its ON clause contains every key pair from the evidence.
    """
    if not relationship_hints or _sql_table_count(sql, allowed_tables) < 2:
        return sql

    allowed_upper = {t.upper() for t in allowed_tables}
    hint_by_pair: dict[frozenset[str], dict] = {}
    for h in relationship_hints:
        lt = h.get("left_table") or ""
        rt = h.get("right_table") or ""
        if not lt or not rt:
            continue
        if lt.upper() not in allowed_upper or rt.upper() not in allowed_upper:
            continue
        hint_by_pair[frozenset({lt.upper(), rt.upper()})] = h
    if not hint_by_pair:
        return sql

    def _replace_join(m: re.Match[str]) -> str:
        prefix = (m.group(1) or "").strip()
        if prefix.upper() == "CROSS":
            return m.group(0)
        right_raw = m.group(2)
        right_table = _strip_quotes(right_raw)
        right_alias_raw = m.group(3) or ""

        # The left table is the last source declared before this JOIN.
        prefix_text = m.string[:m.start()]
        sources = [
            sm
            for sm in _SOURCE_DECL_RE.finditer(prefix_text)
            if not _is_inside_parens(prefix_text, sm.start())
        ]
        if not sources:
            return m.group(0)
        left_table_raw = sources[-1].group(1) or ""
        left_alias_raw = sources[-1].group(2) or ""
        left_table = _strip_quotes(left_table_raw)

        pair = frozenset({left_table.upper(), right_table.upper()})
        hint = hint_by_pair.get(pair)
        if not hint:
            return m.group(0)

        # Use the exact qualifier text (quoted or unquoted) as it appears so the
        # injected ON clause matches the source declaration's case/quoting.
        left_qual = left_alias_raw if left_alias_raw else left_table_raw
        right_qual = right_alias_raw if right_alias_raw else right_raw

        conds = _join_conditions_for_hint(hint, left_qual, right_qual)
        if not conds:
            return m.group(0)

        existing_on = (m.group(4) or "").strip()
        if existing_on:
            join_key_pairs = hint.get("join_key_pairs") or []
            if isinstance(join_key_pairs, list):
                required = [
                    (p.get("left"), p.get("right"))
                    for p in join_key_pairs
                    if isinstance(p, dict) and p.get("left") and p.get("right")
                    and not (hint.get("grain_mismatch") and p.get("is_period"))
                ]
                if not required:
                    required = [(hint.get("left_join_key"), hint.get("right_join_key"))]
            else:
                required = [(hint.get("left_join_key"), hint.get("right_join_key"))]
            missing = [
                c for (lcol, rcol), c in zip(required, conds)
                if lcol and rcol and not _on_has_pair(existing_on, lcol, rcol)
            ]
            if not missing:
                return m.group(0)
            # If none of the required cross-table equalities are present, the ON
            # clause is bogus (e.g. ``WorkCenterID = WorkCenterID``).  Replace it
            # entirely with the qualified conditions.  Otherwise append missing keys.
            if len(missing) == len(required):
                new_on = " AND ".join(conds)
            else:
                new_on = existing_on + ("" if existing_on.endswith("(") else " AND ") + " AND ".join(missing)
        else:
            new_on = " AND ".join(conds)

        alias_part = f" {right_alias_raw}" if right_alias_raw else ""
        replacement = f'{prefix + " " if prefix else ""}JOIN {right_raw}{alias_part} ON {new_on}'
        # The lookahead can consume the whitespace separating the ON clause from
        # the next keyword; add it back when missing so the SQL stays valid.
        tail = m.string[m.end():]
        if tail and not tail[0].isspace() and not tail.startswith(";"):
            replacement += " "
        return replacement

    return _JOIN_CLAUSE_RE.sub(_replace_join, sql)


def _join_tables_are_evidence_backed(
    sql: str, relationship_hints: list[dict[str, Any]]
) -> tuple[bool, frozenset[str] | None, dict[str, Any] | None]:
    """Return whether every top-level JOIN pair is listed in the evidence hints.

    Also returns the first pair and its hint so callers can check grain-mismatch
    or other hint-level constraints.  Subqueries and function parentheses are
    ignored.
    """
    allowed_pairs: dict[frozenset[str], dict[str, Any]] = {}
    for h in relationship_hints:
        lt = h.get("left_table") or ""
        rt = h.get("right_table") or ""
        if not lt or not rt:
            continue
        allowed_pairs[frozenset({str(lt), str(rt)})] = h

    if not allowed_pairs:
        # No evidence -> multi-table joins are not authorized.
        return (_sql_table_count(sql, []) < 2, None, None)

    tables = [
        m.group(1)
        for m in _SQL_TABLE_REF_RE.finditer(sql)
        if not _is_inside_parens(sql, m.start())
    ]
    if len(tables) < 2:
        return (True, None, None)

    for i in range(len(tables) - 1):
        pair = frozenset({tables[i], tables[i + 1]})
        if pair not in allowed_pairs:
            return (False, pair, None)
    first_pair = frozenset({tables[0], tables[1]})
    return (True, first_pair, allowed_pairs.get(first_pair))
