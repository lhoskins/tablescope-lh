# -*- coding: utf-8 -*-
"""
Column‑Layout REST endpoints – per‑query version (Option A).

  GET  /<org_slug>/api/column_layouts?query_id=<id>
        → returns the layout for current user & org (404 if none)

  POST /<org_slug>/api/column_layouts
        Body → { query_id: 68, columns: [{field,hide,order}, ...] }
        • Creates new or REPLACES existing row for that (org_id,user_id,query_id).
"""

from __future__ import absolute_import, division, print_function

import logging
import json

from flask import request, jsonify
from flask_restful import abort

from redash.handlers.base import BaseResource
from redash.permissions import require_permission
from redash.models import db, Query
from redash.models.column_layout import ColumnLayout

logger = logging.getLogger(__name__)


class ColumnLayoutListResource(BaseResource):
    def get(self, org_slug=None):
        """
        Retrieves the column layout for a given query.
        
        Permission logic: Any authenticated user can retrieve their own column layouts
        """
        try:
            qid = int(request.args.get('query_id', ''))
        except (TypeError, ValueError):
            qid = None

        if not qid:
            abort(400, message="Missing ?query_id=<int> parameter")

        layout = (
            db.session.query(ColumnLayout)
            .filter(
                ColumnLayout.org_id == self.current_org.id,
                ColumnLayout.user_id == self.current_user.id,
                ColumnLayout.query_id == qid,
            )
            .first()
        )

        if not layout:
            abort(404, message="Layout not found")

        return jsonify(layout.to_dict()), 200

    def post(self, org_slug=None):
        """
        Creates or updates the column layout for a given query.
        """
        data = request.get_json(force=True) or {}
        try:
            qid = int(data.get('query_id'))
        except (TypeError, ValueError):
            qid = None
        columns = data.get('columns', [])

        if not qid or not isinstance(columns, list):
            abort(400, message="Both 'query_id' (int) and 'columns' (list) are required")

        # Ensure query exists & belongs to org
        query_obj = Query.get_by_id_and_org(qid, self.current_org)
        if query_obj is None:
            abort(404, message="Query not found")

        existing = (
            db.session.query(ColumnLayout)
            .filter(
                ColumnLayout.org_id == self.current_org.id,
                ColumnLayout.user_id == self.current_user.id,
                ColumnLayout.query_id == qid,
            )
            .first()
        )
        try:
            if existing:
                existing.columns_json = json.dumps(columns)
                layout = existing
            else:
                layout = ColumnLayout(
                    org_id       = self.current_org.id,
                    user_id      = self.current_user.id,
                    query_id     = qid,
                    columns_json = json.dumps(columns),
                )
            db.session.add(layout)
            db.session.commit()
            return jsonify(layout.to_dict()), 201

        except Exception as exc:
            logger.exception("Failed to save column layout")
            db.session.rollback()
            abort(500, message="Database error: %s" % exc)
