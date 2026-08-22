"""AI-discovered primary dimensions for the Operational Insight dashboard
designer.

A "primary dimension" is a categorical field (e.g. Business Unit, Customer
Segment) discovered from the AI-proposed dashboard's already-executed chart
previews -- not a manually typed Site/Region label. Three tables cover the
full lifecycle:

- ``DashboardPrimaryDimension``: the reusable, project-scoped field
  definition (one row per distinct field discovered in a project, so the
  same field is recognized and reused across dashboards instead of
  rediscovered and duplicated every time).
- ``DashboardPrimaryDimensionAssignment``: which dashboard has which
  dimension assigned, its dashboard-specific editable label, and whether
  it's the dashboard's currently active dimension (a dashboard can have more
  than one full-coverage dimension assigned; exactly one is active at a
  time, toggled by the header's switch icon).
- ``DashboardPrimaryDimensionBinding``: which widget on the dashboard is
  filterable by an assignment, and which column of that widget's query
  result to filter on -- this is both the coverage record (how "N/M charts"
  is computed and re-verified at apply time) and the runtime wiring used to
  filter every retained chart when a dimension value is selected.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DashboardPrimaryDimension(TimestampMixin, Base):
    __tablename__ = "dashboard_primary_dimensions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "project_id", "source_view", "field",
            name="uq_dashboard_primary_dimension_field",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    # The governed source view/table the field was discovered on, and the
    # field's real column name within it -- together these are what let a
    # later discovery pass recognize "this is the same dimension" instead of
    # creating a duplicate row for what a user would see as one field.
    source_view: Mapped[str] = mapped_column(String(255), nullable=False)
    field: Mapped[str] = mapped_column(String(255), nullable=False)
    # AI-generated starting label (e.g. "business_unit" -> "Business Unit").
    # Dashboard-specific overrides live on the assignment, not here.
    default_label: Mapped[str] = mapped_column(String(255), nullable=False)


class DashboardPrimaryDimensionAssignment(TimestampMixin, Base):
    __tablename__ = "dashboard_primary_dimension_assignments"
    __table_args__ = (
        UniqueConstraint(
            "dashboard_id", "dimension_id",
            name="uq_dashboard_primary_dimension_assignment",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    dashboard_id: Mapped[int] = mapped_column(
        ForeignKey("dashboards.id", ondelete="CASCADE"), index=True,
    )
    dimension_id: Mapped[int] = mapped_column(
        ForeignKey("dashboard_primary_dimensions.id", ondelete="CASCADE"), index=True,
    )
    # Dashboard-specific editable label shown in the header and switcher --
    # starts from the dimension's default_label but is independently
    # renamable per dashboard without renaming the reusable field elsewhere.
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class DashboardPrimaryDimensionBinding(TimestampMixin, Base):
    __tablename__ = "dashboard_primary_dimension_bindings"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id", "widget_id",
            name="uq_dashboard_primary_dimension_binding_widget",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("dashboard_primary_dimension_assignments.id", ondelete="CASCADE"), index=True,
    )
    # Widgets live inside Dashboard.config JSON, not their own table, so this
    # references a widget's "id" string from that JSON rather than a FK.
    widget_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # The column in that widget's query result the dimension value filters
    # on -- kept per-binding since two widgets can alias the same underlying
    # field differently.
    column_name: Mapped[str] = mapped_column(String(255), nullable=False)
