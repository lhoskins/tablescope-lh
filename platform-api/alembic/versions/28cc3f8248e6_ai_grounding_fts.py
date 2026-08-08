"""ai_grounding_fts

Revision ID: 28cc3f8248e6
Revises: 90c125550b42
Create Date: 2026-08-08 06:20:03.932733

"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "28cc3f8248e6"
down_revision: str | None = "90c125550b42"
branch_labels: str | list[str] | None = None
depends_on: str | list[str] | None = None


def upgrade() -> None:
    # Project document chunks: full-text index over chunk_text.
    op.execute(
        """
        ALTER TABLE ai_document_chunks
        ADD COLUMN IF NOT EXISTS chunk_tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('english', COALESCE(chunk_text, ''))) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ai_document_chunks_chunk_tsv
        ON ai_document_chunks USING GIN (chunk_tsv)
        """
    )

    # Reference documents: full-text index over title + AI summary.
    op.execute(
        """
        ALTER TABLE reference_documents
        ADD COLUMN IF NOT EXISTS tsv tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(ai_summary, ''))
        ) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reference_documents_tsv
        ON reference_documents USING GIN (tsv)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ai_document_chunks_chunk_tsv")
    op.execute("ALTER TABLE ai_document_chunks DROP COLUMN IF EXISTS chunk_tsv")
    op.execute("DROP INDEX IF EXISTS idx_reference_documents_tsv")
    op.execute("ALTER TABLE reference_documents DROP COLUMN IF EXISTS tsv")
