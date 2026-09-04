"""KG-07: audit trail of Knowledge Graph evidence used by AI-generated
answers.

One row per KG context collection, recording exactly which authorized
evidence (node/document/query ids, and the active KG version they came from)
informed a given AI Assistant/dashboard/query/insight surface's answer for a
given user -- so an administrator can reconstruct, after the fact, precisely
what evidence a specific answer was grounded in.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

_JSON = JSONB().with_variant(JSON(), "sqlite")


class KnowledgeGraphEvidenceAccess(Base):
    __tablename__ = "knowledge_graph_evidence_access"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    # business_insights | project_insights | dashboard_generation |
    # query_generation | scope_analysis -- which feature this evidence
    # collection informed.
    surface: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    kg_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    node_ids: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    document_ids: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    query_ids: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"KnowledgeGraphEvidenceAccess(id={self.id}, project_id={self.project_id}, "
            f"surface={self.surface!r})"
        )
