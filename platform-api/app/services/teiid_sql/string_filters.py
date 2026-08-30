
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file_source_meta import FileSourceMeta


async def project_table_schema(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
) -> list[dict[str, Any]]:
    """Build the exact per-source column schema for SQL repair/normalization.

    Shape: ``[{"table": view, "columns": [{"name", "type"}]}]`` — the same
    contract the AI server's ``repair-sql-step`` endpoint consumes.
    """
    rows = (
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.project_id == project_id,
                FileSourceMeta.tenant_id == tenant_id,
                FileSourceMeta.archived.is_(False),
            )
        )
    ).all()
    schema: list[dict[str, Any]] = []
    for ds in rows:
        columns = [
            {
                "name": str(c.get("field") or c.get("name")),
                "type": str(c.get("type") or ""),
            }
            for c in (ds.column_types or [])
            if isinstance(c, dict) and c.get("name")
        ]
        schema.append({"table": ds.view_name, "columns": columns})
    return schema


async def project_source_label_map(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
) -> dict[str, str]:
    """Return a mapping from source/display column label to SQL-safe field name.

    For Google Sheets the stored ``column_types`` ``name`` is the raw header
    (e.g. ``"Tablescope MVP List"``) while ``field`` is the sanitized Teiid
    identifier (e.g. ``"Tablescope_MVP_List"``).  Rewriting user-facing saved
    queries with this map lets existing queries continue to work after the view
    columns are registered with sanitized names.
    """
    rows = (
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.project_id == project_id,
                FileSourceMeta.tenant_id == tenant_id,
                FileSourceMeta.archived.is_(False),
            )
        )
    ).all()
    mapping: dict[str, str] = {}
    for ds in rows:
        for c in (ds.column_types or []):
            if not isinstance(c, dict):
                continue
            label = c.get("name")
            field = c.get("field") or label
            if label and field and label != field:
                mapping[str(label)] = str(field)
    return mapping


def _split_top_level(text: str, delimiter: str = ",") -> list[str]:
    """Split ``text`` by ``delimiter`` respecting nested parentheses and strings."""
    parts: list[str] = []
    current = ""
    depth = 0
    in_str = False
    quote = ""
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if not in_str and ch in ("'", '"'):
            in_str = True
            quote = ch
        elif in_str:
            # Handle escaped quotes inside SQL string literals.
            escapes = 0
            j = i - 1
            while j >= 0 and text[j] == "\\":
                escapes += 1
                j -= 1
            if ch == quote and escapes % 2 == 0:
                in_str = False
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == delimiter and depth == 0:
            parts.append(current)
            current = ""
            i += 1
            continue
        current += ch
        i += 1
    parts.append(current)
    return parts


def _fix_string_literal_columns(sql: str, names: set[str]) -> str:
    """Replace string literals that are actually column names inside functions.

    The AI sometimes emits ``CAST('LaborCostUSD' AS double)`` or
    ``PARSETIMESTAMP('Month', 'M/d/yyyy')`` because it mis-quotes the column.
    This rewrites those string-literal placeholders to double-quoted
    identifiers when the literal matches a real column/table name in the
    schema, but only inside function argument positions where a column/expression
    is expected (not in ``WHERE Status = 'At Risk'`` comparisons).
    """
    if not sql or not names:
        return sql

    lower_names = {n.lower(): n for n in names}
    func_positions: dict[str, list[int]] = {
        "cast": [0],
        "parsetimestamp": [0],
        "parsedate": [0],
        "formatdate": [0],
        "formattimestamp": [0],
        "sum": [0],
        "avg": [0],
        "min": [0],
        "max": [0],
        "count": [0],
        "timestampdiff": [1, 2],
    }
    funcs = "|".join(re.escape(f) for f in func_positions)
    func_pattern = re.compile(rf"\b({funcs})\s*\(", re.IGNORECASE)

    def _quoted_if_name(text: str) -> str:
        stripped = text.strip()
        if (
            len(stripped) >= 2
            and stripped.startswith("'")
            and stripped.endswith("'")
        ):
            inner = stripped[1:-1].replace("''", "'")
            if inner.lower() in lower_names:
                return f'"{lower_names[inner.lower()]}"'
        return text

    def _process_segment(text: str) -> str:
        out: list[str] = []
        i = 0
        n = len(text)
        while i < n:
            m = func_pattern.search(text, i)
            if not m:
                out.append(text[i:])
                break
            out.append(text[i : m.start()])
            func = m.group(1).lower()
            # Find the matching closing parenthesis, respecting nested
            # parentheses and string literals.
            depth = 1
            j = m.end()
            in_str = False
            quote = ""
            while j < n and depth > 0:
                ch = text[j]
                if in_str:
                    if ch == quote and (j == 0 or text[j - 1] != "\\"):
                        in_str = False
                else:
                    if ch in ("'", '"'):
                        in_str = True
                        quote = ch
                    elif ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                j += 1
            if depth != 0:
                out.append(text[m.start() : j])
                i = j
                continue
            args_str = _process_segment(text[m.end() : j - 1])
            args = _split_top_level(args_str)
            allowed = func_positions[func]
            new_args: list[str] = []
            for idx, arg in enumerate(args):
                if idx in allowed:
                    if func == "cast":
                        # The first argument of CAST is the expression, followed
                        # by ``AS <type>``. Only rewrite the expression part.
                        as_match = re.search(r"\bAS\b", arg, flags=re.IGNORECASE)
                        if as_match:
                            expr = arg[: as_match.start()].strip()
                            suffix = arg[as_match.start() :]
                            new_expr = _quoted_if_name(expr)
                            if new_expr is not expr:
                                arg = f"{new_expr} {suffix.strip()}"
                                arg = _quoted_if_name(arg)
                        else:
                            arg = _quoted_if_name(arg)
                    else:
                        arg = _quoted_if_name(arg)
                new_args.append(arg)
            out.append(f"{m.group(1)}({', '.join(new_args)})")
            i = j
        return "".join(out)

    return _process_segment(sql)


def normalize_teiid_string_filters(
    sql: str,
    table_schema: list[dict[str, Any]],
) -> str:
    """Wrap string-column equality filters in LOWER() so natural-language values
    match stored values regardless of capitalization.

    Only rewrites comparisons where the column is known to be a string/text type
    in the project schema and the literal is a single-quoted string.
    """
    if not sql or not table_schema:
        return sql

    string_types = {"string", "text", "varchar", "char", "clob", "nstring"}
    string_cols: set[str] = set()
    for entry in table_schema:
        for col in entry.get("columns", []) or []:
            ctype = ""
            cname = ""
            if isinstance(col, dict):
                ctype = str(col.get("type") or "").lower()
                cname = str(col.get("name") or "").strip().strip('"')
            elif isinstance(col, str):
                cname = col.strip().strip('"')
            if cname and (ctype in string_types or not ctype):
                string_cols.add(cname.lower())
    if not string_cols:
        return sql

    col_token = r'"(?:[^"]|"")*"|[A-Za-z_][A-Za-z0-9_]*'
    lit_token = r"'(?:[^']|'')*'"

    def col_name(token: str) -> str | None:
        name = token.strip().strip('"')
        if name.lower() in string_cols:
            return token
        return None

    def _quoted_col(token: str) -> str:
        name = token.strip().strip('"')
        return f'"{name}"'

    # Equality / inequality: "Column" = 'value' or Column = 'value'
    eq_re = re.compile(
        rf"(?<![\w\"'])({col_token})\s*(=|!=|<>|<=|>=)\s*({lit_token})",
        re.IGNORECASE,
    )

    def _eq_replace(m: re.Match[str]) -> str:
        col = m.group(1)
        op = m.group(2)
        val = m.group(3)
        if not col_name(col):
            return m.group(0)
        # Only rewrite equality/inequality operators, not range operators.
        if op in ("<=", ">="):
            return m.group(0)
        return f"LOWER({_quoted_col(col)}) {op} LOWER({val})"

    sql = eq_re.sub(_eq_replace, sql)

    # IN list: "Column" IN ('a','b','c')
    in_re = re.compile(
        rf"(?<![\w\"'])({col_token})\s+IN\s*\(((?:\s*{lit_token}\s*,?)+)\)",
        re.IGNORECASE,
    )

    def _in_replace(m: re.Match[str]) -> str:
        col = m.group(1)
        values_block = m.group(2)
        if not col_name(col):
            return m.group(0)
        lit_re = re.compile(lit_token)
        new_values = lit_re.sub(r"LOWER(\g<0>)", values_block)
        return f"LOWER({_quoted_col(col)}) IN ({new_values})"

    return in_re.sub(_in_replace, sql)
