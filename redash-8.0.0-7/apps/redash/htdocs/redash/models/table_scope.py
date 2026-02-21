# -*- coding: utf-8 -*-
"""
Table-Scope model (Redash 8 / Python 2.7)

*NEW* — adds an explicit `user_id` column (FK → users.id) so each
        scope row is tied to the Redash user who created it.
"""
import logging
from flask_restful import abort
from sqlalchemy.exc import IntegrityError
from sqlalchemy import Column, Integer, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship

from redash.models.base import db
from redash.models.users import User
from redash.models.project import Project
from redash.models.organizations import Organization

logger = logging.getLogger(__name__)

class TableScope(db.Model):
    __tablename__ = "table_scopes"

    id = Column(Integer, primary_key=True)

    # ── tenancy ─────────────────────────────────────────────────────
    org_id     = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"),     nullable=True)
    query_id   = Column(Integer, ForeignKey("queries.id"),      nullable=False)

    # ── main payload ────────────────────────────────────────────────
    source_table  = Column(Text, nullable=False)
    source_field  = Column(Text, nullable=False)
    target_table  = Column(Text, nullable=False)
    target_field  = Column(Text, nullable=False)
    # New FK to target query
    target_query_id = Column(Integer, ForeignKey('queries.id'), nullable=True)
    target_query    = relationship('Query', foreign_keys=[target_query_id])

    # ── audit ───────────────────────────────────────────────────────
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)   # ← NEW
    created_at = Column(DateTime, default=db.func.now())

    # ── relationships (handy for joins / eager-loading) ─────────────
    organization = relationship(Organization, backref="table_scopes")
    project      = relationship(Project,      backref="table_scopes")
    query = relationship('Query', foreign_keys=[query_id], backref='table_scopes')
    user         = relationship(User,         backref="table_scopes")      # ← NEW

    # ── helpers ─────────────────────────────────────────────────────
    def to_dict(self):
        return {
            "id":            self.id,
            "org_id":        self.org_id,
            "project_id":    self.project_id,
            "query_id":      self.query_id,
            "source_table":  self.source_table,
            "source_field":  self.source_field,
            "target_table":  self.target_table,
            "target_field":  self.target_field,
            "target_query_id": self.target_query_id,
            "user_id":       self.user_id,        # ← NEW
            "created_at":    self.created_at,
        }

# ──────────────────────────────────────────────────
# Helper: delete a scope row by ID
def delete_scope(org, scope_id, acting_user):
    """Hard-delete a scope row. Returns True if a row was deleted."""
    scope = db.session.query(TableScope).filter(
        TableScope.org_id == org.id,
        TableScope.id == scope_id
    ).first()
    if scope is None:
        return False
    
    try:
        db.session.delete(scope)
        db.session.commit()
        return True
    except IntegrityError:
        db.session.rollback()
        abort(409, message="Cannot delete this scope because it is referenced by other resources.")
    except Exception as e:
        db.session.rollback()
        logger.error("Failed to delete scope for an unknown reason: %s", e)
        abort(500, message="An unexpected error occurred while trying to delete the scope.")