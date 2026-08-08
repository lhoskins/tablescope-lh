#!/usr/bin/env python3
"""Consolidate duplicate Business/Project Insight conversations.

For every (tenant, user, surface, project_id) group where surface is an
Insight surface, keep the oldest conversation as the canonical thread,
move all turns into it, and mark the duplicates ``status = 'merged'`` with
``merged_into_conversation_id`` pointing to the canonical row.

Use ``--dry-run`` to preview changes without writing anything. Run after the
``9ef39057749a`` migration has added ``canonical_key`` and the merge fields.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.models import AnalyticsConversation, AnalyticsConversationTurn, Project

logger = logging.getLogger(__name__)


def _canonical_key_for(surface: str, project_id: int | None) -> str:
    if surface == "business_insights":
        return "business_insights"
    if surface == "project_insights":
        return f"project_insights:{project_id}"
    raise ValueError(f"Unsupported insight surface: {surface}")


def _canonical_title_for(surface: str, project_name: str | None) -> str:
    if surface == "business_insights":
        return "Business Insights"
    if surface == "project_insights":
        return f"Project Insights — {project_name or 'Unknown'}"
    raise ValueError(f"Unsupported insight surface: {surface}")


async def _merge_group(
    session: AsyncSession,
    rows: Sequence[AnalyticsConversation],
    surface: str,
    project_id: int | None,
    dry_run: bool,
) -> dict[str, Any]:
    if not rows:
        return {"merged": 0, "moved_turns": 0}

    target = rows[0]
    duplicates = rows[1:]

    # Determine canonical metadata.
    project_name: str | None = None
    if project_id is not None:
        project = await session.get(Project, project_id)
        project_name = project.name if project else None

    canonical_key = _canonical_key_for(surface, project_id)
    canonical_title = _canonical_title_for(surface, project_name)

    if not dry_run:
        target.canonical_key = canonical_key
        target.title = canonical_title
        target.status = "active"
        await session.flush()

    moved_turns = 0
    last_successful_turn_id: int | None = target.last_successful_turn_id

    for duplicate in duplicates:
        # Load turns in stable order.
        turns_result = await session.execute(
            select(AnalyticsConversationTurn).where(
                AnalyticsConversationTurn.conversation_id == duplicate.id
            ).order_by(AnalyticsConversationTurn.sequence)
        )
        turns = list(turns_result.scalars().all())

        if turns and not dry_run:
            # Find current max sequence on the target.
            max_seq = await session.scalar(
                select(func.max(AnalyticsConversationTurn.sequence)).where(
                    AnalyticsConversationTurn.conversation_id == target.id
                )
            ) or 0

            for i, turn in enumerate(turns):
                turn.conversation_id = target.id
                turn.sequence = int(max_seq) + i + 1
                if turn.status == "success":
                    last_successful_turn_id = turn.id
            await session.flush()

        moved_turns += len(turns)

        if not dry_run:
            duplicate.status = "merged"
            duplicate.merged_into_conversation_id = target.id
            duplicate.canonical_key = None
            await session.flush()

    if last_successful_turn_id is not None and not dry_run:
        target.last_successful_turn_id = last_successful_turn_id
        target.updated_at = datetime.now(UTC)
        await session.flush()

    return {
        "target_id": target.id,
        "merged": len(duplicates),
        "moved_turns": moved_turns,
        "canonical_key": canonical_key,
        "title": canonical_title,
    }


async def consolidate(dry_run: bool = False) -> dict[str, Any]:
    """Consolidate duplicate Insight conversations."""
    insight_surfaces = ("business_insights", "project_insights")
    stats: dict[str, Any] = {"dry_run": dry_run, "groups": 0, "merged": 0, "moved_turns": 0}

    async with SessionLocal() as session:
        async with session.begin() if not dry_run else session.begin():
            if dry_run:
                # A dry run still needs a transaction for reads.
                pass

            # Group active Insight conversations by (tenant, user, surface, project).
            result = await session.execute(
                select(AnalyticsConversation)
                .where(
                    AnalyticsConversation.surface.in_(insight_surfaces),
                    AnalyticsConversation.status != "merged",
                )
                .order_by(
                    AnalyticsConversation.tenant_id,
                    AnalyticsConversation.user_id,
                    AnalyticsConversation.surface,
                    AnalyticsConversation.project_id,
                    AnalyticsConversation.id,
                )
            )
            conversations = list(result.scalars().all())

            groups: dict[tuple[int, int, str, int | None], list[AnalyticsConversation]] = {}
            for c in conversations:
                key = (c.tenant_id, c.user_id, c.surface, c.project_id)
                groups.setdefault(key, []).append(c)

            for (tenant_id, user_id, surface, project_id), rows in groups.items():
                if len(rows) <= 1:
                    # Still mark single rows with the canonical key and title.
                    if not dry_run:
                        group_stats = await _merge_group(
                            session, rows, surface, project_id, dry_run=True
                        )
                        project_name = group_stats["title"].split(" — ", 1)[1] if " — " in group_stats["title"] else None
                        rows[0].canonical_key = group_stats["canonical_key"]
                        rows[0].title = group_stats["title"]
                        await session.flush()
                    continue

                group_stats = await _merge_group(
                    session, rows, surface, project_id, dry_run
                )
                stats["groups"] += 1
                stats["merged"] += group_stats["merged"]
                stats["moved_turns"] += group_stats["moved_turns"]
                logger.info(
                    "tenant=%s user=%s surface=%s project=%s target=%s merged=%s moved_turns=%s title=%r",
                    tenant_id,
                    user_id,
                    surface,
                    project_id,
                    group_stats["target_id"],
                    group_stats["merged"],
                    group_stats["moved_turns"],
                    group_stats["title"],
                )

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate Insight conversations")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(consolidate(dry_run=args.dry_run))
    logger.info("Consolidation result: %s", result)


if __name__ == "__main__":
    main()
