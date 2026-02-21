
# -*- coding: utf-8 -*-
"""
Column‑Layout model (Redash 8 / Python 2.7)

Persists column order + visibility per user **per saved query** (option A).

    • org_id   (FK → organizations.id)
    • user_id  (FK → users.id)
    • query_id (FK → queries.id)
    • columns_json – JSON array of {field, hide, order}

Unique per (org_id, user_id, query_id).
"""

from __future__ import absolute_import, division, print_function

import json

from sqlalchemy import Column, Integer, Text, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship

from redash.models.base import db
from redash.models.users import User
from redash.models.organizations import Organization
from redash.models import Query


class ColumnLayout(db.Model):
    __tablename__ = "column_layouts"

    id = Column(Integer, primary_key=True)

    # ── tenancy ────────────────────────
    org_id  = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"),        nullable=False)

    # ── target query ───────────────────
    query_id = Column(Integer, ForeignKey("queries.id"), nullable=False)

    # ── payload ────────────────────────
    columns_json = Column(Text, nullable=False)  # raw JSON list

    # ── audit ──────────────────────────
    created_at = Column(DateTime, default=db.func.now())
    updated_at = Column(DateTime, default=db.func.now(), onupdate=db.func.now())

    # ── constraints ────────────────────
    __table_args__ = (
        UniqueConstraint('org_id', 'user_id', 'query_id', name='uniq_user_query_layout'),
    )

    # ── relationships ──────────────────
    organization = relationship(Organization, backref="column_layouts")
    user         = relationship(User,         backref="column_layouts")
    query        = relationship(Query,        backref="column_layouts")

    # ── helpers ────────────────────────
    @property
    def columns(self):
        try:
            return json.loads(self.columns_json)
        except Exception:
            return []

    def to_dict(self):
        return {
            "id":         self.id,
            "org_id":     self.org_id,
            "user_id":    self.user_id,
            "query_id":   self.query_id,
            "columns":    self.columns,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
