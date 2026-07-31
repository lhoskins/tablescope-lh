"""Business Context: metric success_criterion_id, source match status, risk rating version.

Revision ID: 0074
Revises: 0073
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0074"
down_revision: Union[str, None] = "0073"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── ProjectMetric parent success criterion and source-matching columns ───
    op.add_column(
        "project_metrics",
        sa.Column("success_criterion_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_project_metrics_success_criterion_id",
        "project_metrics",
        "project_goals",
        ["success_criterion_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_project_metrics_success_criterion_id",
        "project_metrics",
        ["success_criterion_id"],
    )

    op.add_column(
        "project_metrics",
        sa.Column("source_match_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "project_metrics",
        sa.Column("latest_value", sa.Numeric(19, 6), nullable=True),
    )
    op.add_column(
        "project_metrics",
        sa.Column("latest_value_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Backfill success_criterion_id where a metric has exactly one goal link.
    # Ambiguous (>1 link) or unlinked (0 links) metrics are left as NULL.
    op.execute(
        sa.text(
            """
            UPDATE project_metrics AS m
            SET success_criterion_id = link.goal_id
            FROM (
                SELECT l.metric_id, l.goal_id
                FROM project_goal_metric_links AS l
                WHERE l.metric_id IN (
                    SELECT metric_id
                    FROM project_goal_metric_links
                    GROUP BY metric_id
                    HAVING COUNT(*) = 1
                )
            ) AS link
            WHERE m.id = link.metric_id
            """
        )
    )

    # ── ProjectRisk authoritative rating version ─────────────────────────────
    op.add_column(
        "project_risks",
        sa.Column("rating_matrix_version", sa.Integer(), nullable=True),
    )

    # Recompute severity from likelihood x impact where both are present.
    # The formula is the same one used by app.services.risk_rating so existing
    # rows remain internally consistent after the server becomes authoritative.
    if op.get_context().dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                WITH scored AS (
                    SELECT id,
                        (
                            CASE likelihood
                                WHEN 'rare' THEN 1
                                WHEN 'unlikely' THEN 2
                                WHEN 'possible' THEN 3
                                WHEN 'likely' THEN 4
                                WHEN 'almost_certain' THEN 5
                            END::numeric / 5.0
                        ) * (
                            CASE impact
                                WHEN 'negligible' THEN 1
                                WHEN 'insignificant' THEN 2
                                WHEN 'minor' THEN 3
                                WHEN 'moderate' THEN 4
                                WHEN 'major' THEN 5
                                WHEN 'severe' THEN 6
                                WHEN 'catastrophic' THEN 7
                            END::numeric / 7.0
                        ) AS score
                    FROM project_risks
                    WHERE likelihood IS NOT NULL AND impact IS NOT NULL
                )
                UPDATE project_risks AS r
                SET
                    severity = CASE
                        WHEN s.score < 0.20 THEN 'low'
                        WHEN s.score < 0.45 THEN 'medium'
                        WHEN s.score < 0.70 THEN 'high'
                        ELSE 'critical'
                    END,
                    rating_matrix_version = 1
                FROM scored AS s
                WHERE r.id = s.id
                """
            )
        )
    else:
        # Non-PostgreSQL test databases: stamp the version for rows that have
        # both inputs so the column is not left entirely null, but avoid SQL
        # dialect-specific casts.
        op.execute(
            sa.text(
                """
                UPDATE project_risks
                SET rating_matrix_version = 1
                WHERE likelihood IS NOT NULL AND impact IS NOT NULL
                """
            )
        )

    # Drop the now-disused legacy severity check constraint if it exists.
    # The client can no longer set severity directly.
    if op.get_context().dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE project_risks DROP CONSTRAINT IF EXISTS ck_project_risks_severity"
        )


def downgrade() -> None:
    op.drop_column("project_risks", "rating_matrix_version")
    op.drop_column("project_metrics", "latest_value_at")
    op.drop_column("project_metrics", "latest_value")
    op.drop_column("project_metrics", "source_match_status")
    op.drop_index("ix_project_metrics_success_criterion_id", table_name="project_metrics")
    op.drop_constraint(
        "fk_project_metrics_success_criterion_id",
        "project_metrics",
        type_="foreignkey",
    )
    op.drop_column("project_metrics", "success_criterion_id")
