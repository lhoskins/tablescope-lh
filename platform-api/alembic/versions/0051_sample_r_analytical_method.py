"""Add a sample R-backed analytical method to the active catalog.

Revision ID: 0051
Revises: 0050
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


_METHOD_ID = "r_descriptive_profile"
_INTENT = "r_descriptive_profile"


def upgrade() -> None:
    conn = op.get_bind()

    # Locate the active catalog version for tablescope_analytical_methods.
    version_row = conn.execute(
        sa.text(
            """
            SELECT v.id
            FROM method_catalog_versions v
            JOIN method_catalogs c ON c.id = v.catalog_id
            WHERE c.catalog_key = 'tablescope_analytical_methods'
              AND c.is_active = true
              AND v.status = 'active'
            ORDER BY v.id DESC
            LIMIT 1
            """
        )
    ).first()
    if version_row is None:
        return
    version_id = version_row[0]

    # Insert the sample R method if it does not already exist.
    existing = conn.execute(
        sa.text(
            "SELECT id FROM analytical_methods WHERE method_id = :method_id AND catalog_version_id = :version_id"
        ),
        {"method_id": _METHOD_ID, "version_id": version_id},
    ).first()
    if existing is None:
        conn.execute(
            sa.text(
                """
                INSERT INTO analytical_methods (
                    catalog_version_id, method_id, display_name, category, subcategory,
                    tier, status, summary, applicability_condition, supported_intents,
                    selection_rules, rejection_rules, required_checks, fallback_methods,
                    output_contract, method_card, llm_guardrails, executor_key,
                    execution_engine, is_executable
                ) VALUES (
                    :version_id, :method_id, :display_name, :category, :subcategory,
                    :tier, :status, :summary, :applicability_condition, :supported_intents,
                    :selection_rules, :rejection_rules, :required_checks, :fallback_methods,
                    :output_contract, :method_card, :llm_guardrails, :executor_key,
                    :execution_engine, :is_executable
                )
                """
            ),
            {
                "version_id": version_id,
                "method_id": _METHOD_ID,
                "display_name": "R descriptive profile",
                "category": "Data Profiling and Descriptive Statistics",
                "subcategory": "Dataset-level profiling",
                "tier": 1,
                "status": "active",
                "summary": "Descriptive statistics computed by the R analytics runtime",
                "applicability_condition": "Exactly one numeric field requested",
                "supported_intents": '["r_descriptive_profile"]',
                "selection_rules": '["Exactly one numeric field requested"]',
                "rejection_rules": '["No numeric field present"]',
                "required_checks": '["n count", "null rate"]',
                "fallback_methods": "[]",
                "output_contract": '{"fields": ["n", "mean", "median", "std", "min", "max", "quantiles"]}',
                "method_card": '{"use_when": ["A single numeric field needs summarizing"], "do_not_use_when": ["The field is categorical or an identifier"], "required_checks": ["n count", "null rate", "distribution shape"], "fallback": [], "output": ["mean", "median", "std", "quantiles"]}',
                "llm_guardrails": '["Do not choose the statistical method; explain the method Tablescope selected.", "Never invent statistical outputs; report only values present in the envelope.", "Do not use causal wording unless the method causal gates pass.", "Always report effect size and confidence interval alongside any p-value."]',
                "executor_key": "describe_numeric",
                "execution_engine": "r",
                "is_executable": True,
            },
        )

    # Add a selection-matrix row so the method is reachable.
    matrix_row = conn.execute(
        sa.text(
            """
            SELECT id FROM method_selection_matrix
            WHERE catalog_version_id = :version_id AND analysis_intent = :intent
            """
        ),
        {"version_id": version_id, "intent": _INTENT},
    ).first()
    if matrix_row is None:
        conn.execute(
            sa.text(
                """
                INSERT INTO method_selection_matrix (
                    catalog_version_id, analysis_intent, primary_method_id,
                    alternative_method_ids, priority
                ) VALUES (
                    :version_id, :intent, :method_id, '[]', 100
                )
                """
            ),
            {"version_id": version_id, "intent": _INTENT, "method_id": _METHOD_ID},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM method_selection_matrix
            WHERE analysis_intent = :intent AND catalog_version_id IN (
                SELECT v.id
                FROM method_catalog_versions v
                JOIN method_catalogs c ON c.id = v.catalog_id
                WHERE c.catalog_key = 'tablescope_analytical_methods'
            )
            """
        ),
        {"intent": _INTENT},
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM analytical_methods
            WHERE method_id = :method_id AND catalog_version_id IN (
                SELECT v.id
                FROM method_catalog_versions v
                JOIN method_catalogs c ON c.id = v.catalog_id
                WHERE c.catalog_key = 'tablescope_analytical_methods'
            )
            """
        ),
        {"method_id": _METHOD_ID},
    )
