"""Chunk extracted document text for embedding and vector indexing."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Target ~800 tokens ≈ ~3200 chars; overlap ~125 tokens ≈ ~500 chars.
CHUNK_SIZE = 3200
CHUNK_OVERLAP = 500


def chunk_document(extraction: dict[str, Any]) -> list[dict[str, Any]]:
    """Split extracted document into overlapping chunks.

    Returns a list of chunk dicts with:
      chunk_index, chunk_text, section_type, section_number, token_count, content_hash
    """
    sections = extraction.get("sections", [])
    if not sections:
        text = extraction.get("document_text", "")
        if text:
            sections = [{"section_type": "text", "section_number": 1, "text": text}]

    chunks: list[dict[str, Any]] = []
    idx = 0

    for section in sections:
        text = section.get("text", "")
        if not text.strip():
            continue

        section_type = section.get("section_type", "text")
        section_number = section.get("section_number", 1)

        # If the section fits in one chunk, keep it whole
        if len(text) <= CHUNK_SIZE:
            chunks.append(_make_chunk(idx, text, section_type, section_number))
            idx += 1
            continue

        # Split long sections with overlap
        start = 0
        while start < len(text):
            end = start + CHUNK_SIZE
            chunk_text = text[start:end]

            # Try to break at sentence boundary
            if end < len(text):
                last_period = chunk_text.rfind(".")
                last_newline = chunk_text.rfind("\n")
                break_at = max(last_period, last_newline)
                if break_at > CHUNK_SIZE // 2:
                    chunk_text = chunk_text[: break_at + 1]
                    end = start + break_at + 1

            chunks.append(_make_chunk(idx, chunk_text.strip(), section_type, section_number))
            idx += 1
            start = end - CHUNK_OVERLAP
            if start < 0:
                start = 0
            if end >= len(text):
                break

    return chunks


def _make_chunk(
    idx: int, text: str, section_type: str, section_number: int,
) -> dict[str, Any]:
    return {
        "chunk_index": idx,
        "chunk_text": text,
        "section_type": section_type,
        "section_number": section_number,
        "token_count": len(text.split()),
        "content_hash": hashlib.sha256(text.encode()).hexdigest()[:16],
    }
