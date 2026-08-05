
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_RESERVED = {
    "select", "from", "where", "table", "view", "model", "user", "group",
    "order", "by", "join", "on", "as", "and", "or", "not", "null",
}


def sanitize_identifier(value: str) -> str:
    """Make an arbitrary string safe for use as a Teiid identifier.

    Strips spaces, hyphens and special characters, collapses repeats, ensures
    it starts with a letter/underscore, and avoids reserved SQL words.
    """
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = "ds"
    if not re.match(r"^[A-Za-z_]", cleaned):
        cleaned = f"_{cleaned}"
    if cleaned.lower() in _RESERVED:
        cleaned = f"{cleaned}_"
    return cleaned


def generate_teiid_names(*, data_source_id: int, db_type: str, table_name: str) -> dict:
    """Deterministic, collision-resistant Teiid names for a data source."""
    safe_table = sanitize_identifier(table_name)
    return {
        "model_name": f"ds_{data_source_id}_src",
        "jndi_name": f"java:/ds_{data_source_id}_{db_type}",
        "ds_name": f"ds_{data_source_id}_{db_type}",
        "teiid_table_name": safe_table,
    }


def generate_view_name(*, display_name: str, db_type: str) -> str:
    """A friendly, unique view name surfaced to the query builder."""
    base = sanitize_identifier(display_name)
    suffix = db_type.upper()
    return f"{base}_{suffix}"
