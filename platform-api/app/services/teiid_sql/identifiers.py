
from __future__ import annotations

import re
from typing import Any

from .string_filters import _fix_string_literal_columns, _split_top_level

# Teiid reserved words that the model often uses as aliases.  They must be
# quoted when emitted as column/output aliases (``AS Year``, ``AS Quarter``).
# Most of these are EXTRACT datetime fields; SYSTEM is unrelated but confirmed
# live -- a query aliasing a real "System" column as an unquoted ``AS System``
# hit a hard TEIID31100 parser error at exactly that token
# (``SELECT "System" AS [*]System[*]``), the same failure shape this set
# exists to prevent for the date fields below.
_TEIID_RESERVED_ALIASES = {
    "YEAR", "MONTH", "DAY", "HOUR", "MINUTE", "SECOND", "QUARTER", "WEEK",
    "YEAROFERA", "MONTHOFYEAR", "WEEKOFYEAR", "DAYOFWEEK", "DAYOFMONTH",
    "DAYOFYEAR", "EPOCH", "MILLISECOND", "NANOSECOND", "SYSTEM",
}


def normalize_teiid_identifiers(
    sql: str,
    table_schema: list[dict[str, Any]],
) -> str:
    """Quote bare table/column identifiers that conflict with Teiid reserved words.

    Uses the project schema so only real table/column names are quoted.  Tokens
    immediately after an ``AS`` alias clause are left unquoted unless the alias
    is a Teiid reserved word, and tokens inside string literals are ignored.
    """
    if not sql or not table_schema:
        return sql

    names: set[str] = set()
    for entry in table_schema:
        table = entry.get("table")
        if table:
            names.add(str(table))
        for col in entry.get("columns", []):
            if isinstance(col, dict):
                cname = col.get("name")
            else:
                cname = col
            if cname:
                names.add(str(cname))
    if not names:
        return sql

    # Fix the common AI mistake of using a single-quoted string literal where a
    # column identifier was intended (e.g. CAST('Month' AS date)).
    sql = _fix_string_literal_columns(sql, names)

    # Longest first so multi-word names match before their substrings.
    sorted_names = sorted(names, key=len, reverse=True)
    pattern = re.compile(
        r'(?<![\w"])(' + "|".join(re.escape(n) for n in sorted_names) + r')(?![\w("])',
        re.IGNORECASE,
    )

    def _escaped(text: str, pos: int) -> bool:
        escapes = 0
        i = pos - 1
        while i >= 0 and text[i] == "\\":
            escapes += 1
            i -= 1
        return escapes % 2 == 1

    def _in_string(text: str, end: int) -> bool:
        in_str = False
        quote = ""
        i = 0
        while i < end:
            ch = text[i]
            if not in_str:
                if ch in ("'", '"'):
                    in_str = True
                    quote = ch
            else:
                if ch == quote and not _escaped(text, i):
                    in_str = False
            i += 1
        return in_str

    out: list[str] = []
    prev = 0
    for m in pattern.finditer(sql):
        start = m.start()
        if _in_string(sql, start):
            # Append the segment up to and including this match unchanged.
            out.append(sql[prev : m.end()])
            prev = m.end()
            continue
        out.append(sql[prev:start])
        token = m.group(1)
        prefix = sql[:start]
        if re.search(r"\bAS\s+$", prefix, re.IGNORECASE) and token.upper() not in _TEIID_RESERVED_ALIASES:
            out.append(token)
        else:
            out.append(f'"{token}"')
        prev = m.end()
    out.append(sql[prev:])
    sql = "".join(out)

    # Final pass: quote any remaining reserved-word aliases and their uses in
    # GROUP BY / ORDER BY.  The schema-name pass above skips tokens not present
    # in the project schema, so aliases like ``AS Year`` or ``GROUP BY Year``
    # (common model output) must be handled explicitly.  Skip tokens that are
    # actually function calls (``GROUP BY QUARTER(...)``) so we do not split the
    # expression.
    alias_re = re.compile(
        r'\b(AS|GROUP\s+BY|ORDER\s+BY)\s+([A-Za-z_]\w*)(?!\s*\()',
        re.IGNORECASE,
    )

    def _quote_alias_ref(m: re.Match[str]) -> str:
        token = m.group(2)
        if token.upper() in _TEIID_RESERVED_ALIASES:
            return f'{m.group(1)} "{token}"'
        return m.group(0)

    return alias_re.sub(_quote_alias_ref, sql)


def collapse_bare_following_parens(sql: str) -> str:
    """Remove spurious ``) ( ... )`` sequences the small model sometimes emits.

    In valid SQL a closing parenthesis is never immediately followed by an
    opening parenthesis without an operator or comma.  The LLM occasionally
    hallucinates constructions like
    ``GROUP BY QUARTER(PARSETIMESTAMP(...))(PARSETIMESTAMP(...))``; this
    collapses the trailing bare paren group so the expression is valid.
    String literals and SQL comments are left untouched.
    """
    if not sql:
        return sql

    out: list[str] = []
    i = 0
    n = len(sql)
    in_str = False
    quote = ""
    in_line_comment = False
    in_block_comment = False

    while i < n:
        ch = sql[i]

        if in_line_comment:
            out.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            out.append(ch)
            if ch == "*" and i + 1 < n and sql[i + 1] == "/":
                out.append(sql[i + 1])
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if in_str:
            out.append(ch)
            if ch == quote:
                in_str = False
            i += 1
            continue

        if ch == "'" or ch == '"':
            out.append(ch)
            in_str = True
            quote = ch
            i += 1
            continue

        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            out.append(ch)
            in_line_comment = True
            i += 1
            continue

        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            out.append(ch)
            in_block_comment = True
            i += 1
            continue

        if ch == ")":
            j = i + 1
            while j < n and sql[j].isspace():
                j += 1
            if j < n and sql[j] == "(":
                depth = 1
                j += 1
                while j < n and depth > 0:
                    if sql[j] == "(":
                        depth += 1
                    elif sql[j] == ")":
                        depth -= 1
                    if depth == 0:
                        break
                    j += 1
                out.append(")")
                i = j + 1
                continue

        out.append(ch)
        i += 1

    return "".join(out)


_AGGREGATE_NAMES = frozenset({"AVG", "COUNT", "MAX", "MIN", "SUM"})


def _is_aggregate_expression(expr: str) -> bool:
    """Return True when ``expr``'s outermost function is an aggregate."""
    expr = expr.strip()
    while len(expr) >= 2 and expr[0] == "(" and expr[-1] == ")":
        inner = expr[1:-1].strip()
        depth = 0
        balanced = True
        for ch in inner:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if depth < 0:
                balanced = False
                break
        if not balanced or depth != 0:
            break
        expr = inner

    m = re.match(r"^\s*([A-Za-z_]\w*)\s*\(", expr)
    return bool(m and m.group(1).upper() in _AGGREGATE_NAMES)


def _strip_output_alias(select_item: str) -> tuple[str, str | None]:
    """Remove a trailing ``AS alias`` from a SELECT item.

    Returns ``(expression, alias)``. ``alias`` is ``None`` when no alias is
    present.
    """
    m = re.search(
        r'\s+AS\s+(?:"([^"]+)"|\[([^\]]+)\]|([A-Za-z_]\w*))\s*$',
        select_item,
        re.IGNORECASE,
    )
    if not m:
        return select_item.strip(), None
    expr = select_item[: m.start()].strip()
    alias = m.group(1) or m.group(2) or m.group(3)
    return expr, alias


def _top_level_keyword_index(sql: str, start: int, keyword: str) -> int | None:
    """Find the first ``keyword`` at paren-depth 0, outside any quoted string,
    starting the search at ``start``. Returns its start index, or ``None``.

    A plain ``re.search`` for a clause keyword like ``FROM`` matches the
    *first* occurrence anywhere in the string -- including one nested inside
    the SELECT list itself, e.g. ``EXTRACT(QUARTER FROM "Month")``. That
    truncated the SELECT-list extraction in ``rebuild_group_by_from_select``
    at EXTRACT's own ``FROM``, well before the query's real FROM clause,
    silently corrupting the rebuilt GROUP BY (or dropping it) for any query
    combining an aggregate with an EXTRACT(... FROM ...) expression -- one of
    the most common shapes for a "revenue by quarter" style question.
    """
    pattern = re.compile(r"\b" + keyword + r"\b", re.IGNORECASE)
    depth = 0
    in_quote: str | None = None
    i = start
    n = len(sql)
    while i < n:
        ch = sql[i]
        if in_quote:
            if ch == in_quote:
                in_quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            in_quote = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth -= 1
            i += 1
            continue
        if depth == 0 and pattern.match(sql, i):
            return i
        i += 1
    return None


def _next_clause_position(sql: str, after: int) -> int | None:
    """Return the earliest position of a following SQL clause, or None."""
    positions: list[int] = []
    for pattern in (r"\bORDER\s+BY\b", r"\bHAVING\b", r"\bLIMIT\b", r"\bOFFSET\b"):
        m = re.compile(pattern, re.IGNORECASE).search(sql, after)
        if m:
            positions.append(m.start())
    return min(positions) if positions else None


def rebuild_group_by_from_select(sql: str) -> str:
    """Rebuild the ``GROUP BY`` clause from the non-aggregate ``SELECT`` items.

    Teiid requires every ``GROUP BY`` expression to exactly repeat a
    non-aggregate ``SELECT`` expression. Generated SQL frequently violates this
    by either grouping on an aggregate (``SUM(...)``) or by wrapping the
    ``SELECT`` expression differently (``PARSETIMESTAMP(PARSETIMESTAMP(...))``).

    The repair is deterministic:

    1. Parse the ``SELECT`` list.
    2. Classify each item as aggregate or non-aggregate.
    3. Replace ``GROUP BY`` with the exact text of the non-aggregate ``SELECT``
       expressions, in order. If there are no non-aggregate items, remove the
       ``GROUP BY`` entirely.
    4. ``ORDER BY`` is left alone when each item references a ``SELECT`` alias
       or a non-aggregate ``SELECT`` expression; otherwise it is rewritten with
       the same normalized references.
    """
    if not sql:
        return sql

    select_kw = re.search(r"\bSELECT\b", sql, re.IGNORECASE)
    if not select_kw:
        return sql
    from_idx = _top_level_keyword_index(sql, select_kw.end(), "FROM")
    if from_idx is None:
        return sql

    select_body = sql[select_kw.end():from_idx]
    select_items = [item.strip() for item in _split_top_level(select_body)]

    non_aggregate_exprs: list[str] = []
    aliases: dict[str, str] = {}
    for item in select_items:
        expr, alias = _strip_output_alias(item)
        expr = expr.strip()
        if alias:
            aliases[alias.upper()] = expr
        if not _is_aggregate_expression(expr):
            non_aggregate_exprs.append(expr)

    group_match = re.search(r"\bGROUP\s+BY\b", sql, re.IGNORECASE)
    order_match = re.search(r"\bORDER\s+BY\b", sql, re.IGNORECASE)

    # Build the new ORDER BY clause, normalizing alias/expression references.
    new_order_by: str | None = None
    if order_match:
        order_end = _next_clause_position(sql, order_match.end()) or len(sql)
        order_body = sql[order_match.end() : order_end].strip().rstrip(";")
        order_parts = [p.strip() for p in _split_top_level(order_body)]
        normalized_orders: list[str] = []
        for part in order_parts:
            # Split optional trailing ASC/DESC / NULLS FIRST/LAST.
            suffix_match = re.search(
                r"\s*(?:ASC|DESC)?(?:\s+NULLS\s+(?:FIRST|LAST))?\s*$",
                part,
                re.IGNORECASE,
            )
            suffix = suffix_match.group(0) if suffix_match else ""
            core = part[: -len(suffix)].strip() if suffix else part.strip()
            suffix = suffix.strip()

            core_upper = core.upper()
            if core_upper in aliases:
                # References a SELECT alias — leave it (Teiid supports aliases
                # in ORDER BY).
                normalized_orders.append(part)
                continue

            # Exact non-aggregate SELECT expression match (case-sensitive to
            # preserve string-literal casing).
            if core in non_aggregate_exprs:
                normalized_orders.append(part)
                continue

            # Otherwise try to map a bare alias that may have different casing.
            for alias_upper, expr in aliases.items():
                if core_upper == alias_upper:
                    normalized_orders.append(part.replace(core, expr, 1))
                    break
            else:
                normalized_orders.append(part)

        new_order_by = f"ORDER BY {', '.join(normalized_orders)}"

    # Build the new GROUP BY clause. If the SELECT contains no aggregates at
    # all the GROUP BY is unnecessary and is often a model mistake, so remove
    # it. Otherwise group on the non-aggregate SELECT expressions verbatim.
    has_aggregates = any(_is_aggregate_expression(_strip_output_alias(item)[0]) for item in select_items)
    if not non_aggregate_exprs or not has_aggregates:
        new_group_by: str | None = None
    else:
        new_group_by = f"GROUP BY {', '.join(non_aggregate_exprs)}"

    if group_match:
        group_end = _next_clause_position(sql, group_match.end()) or len(sql)
        before_group = sql[: group_match.start()].rstrip()
        after_group = sql[group_end:]

        # If ORDER BY immediately follows GROUP BY, normalize it in place.
        if (
            order_match
            and group_match.end() <= order_match.start() < group_end
            and new_order_by
        ):
            order_end = _next_clause_position(sql, order_match.end()) or len(sql)
            after_order = sql[order_end:]
            order_tail = f" {new_order_by}{after_order}"
        else:
            order_tail = after_group

        if new_group_by:
            return f"{before_group} {new_group_by}{order_tail}"
        # No group by needed; remove it and swallow trailing whitespace.
        return f"{before_group} {order_tail.lstrip()}".strip()

    if new_group_by:
        # Insert GROUP BY before ORDER BY / HAVING / LIMIT / OFFSET or at end.
        if order_match and new_order_by:
            order_end = _next_clause_position(sql, order_match.end()) or len(sql)
            before = sql[: order_match.start()].rstrip()
            after = sql[order_end:]
            return f"{before} {new_group_by} {new_order_by}{after}".strip()
        limit_or_offset = re.search(r"\b(LIMIT|OFFSET)\b", sql, re.IGNORECASE)
        if limit_or_offset:
            before = sql[: limit_or_offset.start()].rstrip()
            after = sql[limit_or_offset.start():]
            return f"{before} {new_group_by} {after}".strip()
        return f"{sql.rstrip()} {new_group_by}".strip()

    if order_match and new_order_by:
        # No GROUP BY needed but ORDER BY can be normalized in place.
        order_end = _next_clause_position(sql, order_match.end()) or len(sql)
        before = sql[: order_match.start()].rstrip()
        after = sql[order_end:]
        return f"{before} {new_order_by}{after}".strip()

    return sql
