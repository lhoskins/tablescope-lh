"""KG-32: durable capture of AI confidence vs. the human decision made on it.

One row per human accept/change/remove decision on an AI-suggested Knowledge
Graph edge (document-family curation today), recording the model's own
confidence *at the moment of that decision* alongside what the human actually
did with it. Previously this pair only ever reached ``log_family_event`` --
a log line, not a queryable table -- and the original AI confidence was
discarded the instant a decision was applied to the node/edge itself.

This is groundwork only: it makes the (confidence, outcome) pairs a future
calibration pass would need durable and queryable. It does not itself compute
any precision/recall or calibration curve -- there is no historical labeled
dataset yet to calibrate against.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AiConfidenceDecision(Base):
    __tablename__ = "ai_confidence_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_assets.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    # Which AI suggestion pipeline this decision was made on, e.g.
    # "document_family". Lets future pipelines share this table.
    source_pipeline: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # The model's own confidence in its suggestion at the moment the human
    # decided on it. None when the decision wasn't made on an AI suggestion
    # at all (e.g. removing a family the user assigned manually).
    ai_confidence_at_decision: Mapped[float | None] = mapped_column(Float, nullable=True)
    # accepted | changed | removed
    human_decision: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"AiConfidenceDecision(id={self.id}, project_id={self.project_id}, "
            f"source_pipeline={self.source_pipeline!r}, human_decision={self.human_decision!r})"
        )
