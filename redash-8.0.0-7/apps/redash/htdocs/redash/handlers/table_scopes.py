# -*- coding: utf-8 -*-
"""
Table-Scope REST endpoints (Redash 8 / Python 2.7).

  GET  /api/scopes                 → list scopes   (optional filters)
  POST /api/scopes                 → create scope (records user_id)
  GET  /api/scopes/<scope_id>      → retrieve one scope
  PUT  /api/scopes/<scope_id>      → update its target_table/target_field
  DELETE /api/scopes/<scope_id>    → delete a scope
  GET  /api/scopes/<query_id>      → list scopes for a single query
  GET  /api/scopes/filter          → filter rows via target table/field
"""
from __future__ import absolute_import, division, print_function

import logging
import json
import sqlparse

from flask import request, jsonify
from flask_restful import abort

from redash.handlers.base import BaseResource
from redash.permissions import require_permission
from redash.models import db, Project, Query, DataSource
from redash.models.table_scope import TableScope, delete_scope

logger = logging.getLogger(__name__)


class TableScopeResource(BaseResource):
    """
    GET    /api/scopes/<scope_id>   → retrieve one scope
    PUT    /api/scopes/<scope_id>   → update its target_table/target_field
    DELETE /api/scopes/<scope_id>   → delete a scope
    """

    @require_permission('view_query')
    def get(self, scope_id):
        scope = db.session.query(TableScope).filter_by(id=scope_id).first()
        if not scope or scope.org_id != self.current_org.id:
            abort(404, message="Scope not found.")
        return jsonify(scope.to_dict()), 200

    @require_permission('edit_query')
    def put(self, scope_id):
        data = request.get_json(force=True) or {}
        if not data.get('target_table') or not data.get('target_field'):
            abort(400, message="Both target_table and target_field are required.")

        scope = db.session.query(TableScope).filter_by(id=scope_id).first()
        if not scope or scope.org_id != self.current_org.id:
            abort(404, message="Scope not found.")

        scope.target_table = data['target_table']
        scope.target_field = data['target_field']
        if 'target_query_id' in data:
            scope.target_query_id = int(data['target_query_id'])

        try:
            db.session.commit()
            return jsonify(scope.to_dict()), 200
        except Exception as exc:
            db.session.rollback()
            abort(500, message="Database error: {}".format(exc))

    @require_permission('edit_query')
    def delete(self, scope_id):
        if not delete_scope(self.current_org, scope_id, self.current_user):
            abort(404, message="Scope not found")
        return {'status': 'deleted'}, 200


class TableScopeListResource(BaseResource):
    """
    Collection endpoint: /api/scopes

    Supports query-params:
      id=<int>           → return only the scope whose PK `id` matches
      project_id=<int>   → filter by project_id
      query_id=<int>     → filter by query_id
    """
    def get(self):
        try:
            org_id     = self.current_org.id
            id_param   = request.args.get('id',         type=int)
            project_id = request.args.get('project_id', type=int)
            query_id   = request.args.get('query_id',   type=int)

            if id_param is not None:
                scope = db.session.query(TableScope).filter_by(id=id_param).first()
                if not scope or scope.org_id != org_id:
                    abort(404, message="Scope not found.")
                return jsonify([scope.to_dict()]), 200

            q = db.session.query(TableScope).filter(TableScope.org_id == org_id)
            if project_id:
                logger.debug("Filtering scopes by project_id=%s", project_id)
                q = q.filter(TableScope.project_id == project_id)
            if query_id:
                logger.debug("Filtering scopes by query_id=%s", query_id)
                q = q.filter(TableScope.query_id == query_id)

            scopes = q.all()
            return jsonify([s.to_dict() for s in scopes]), 200

        except Exception as ex:
            logger.exception("Failed to fetch scopes")
            abort(500, message="Database error: %s" % ex)

    @require_permission('edit_query')
    def post(self):
        data = request.get_json(force=True) or {}
        required = [
            'project_id',
            'query_id',
            'source_table',
            'source_field',
            'target_table',
            'target_field',
        ]
        # Derive target_query_id
        target_qid = data.get('target_query_id')
        if not target_qid:
            q = Query.query.filter_by(name=data['target_table'], org_id=self.current_org.id).first()
            if not q:
                abort(400, message="Unknown target_table: %s" % data['target_table'])
            target_qid = q.id
        missing = [k for k in required if not data.get(k)]
        if missing:
            abort(400, message="Missing fields: %s" % ', '.join(missing))

        project_id = int(data['project_id'])
        query_id   = int(data['query_id'])
        project    = Project.query.get(project_id)
        if not project:
            abort(404, message="Project not found")

        user_id = self.current_user.id
        if project.owner_id != user_id and not any(m.user_id == user_id for m in project.members):
            abort(403, message="You don't belong to this project")

        try:
            scope = TableScope(
                org_id       = self.current_org.id,
                project_id   = project_id,
                query_id     = query_id,
                target_query_id = target_qid,
                source_table = data['source_table'],
                source_field = data['source_field'],
                target_table = data['target_table'],
                target_field = data['target_field'],
                user_id      = user_id,
            )
            db.session.add(scope)
            db.session.commit()
            return jsonify(scope.to_dict()), 201

        except Exception as exc:
            logger.exception("Failed to save scope")
            db.session.rollback()
            abort(500, message="Database error: %s" % exc)


class TableScopeQueryResource(BaseResource):
    """
    GET /api/scopes/<int:query_id>
    Returns all scopes for a single query_id (optional ?project_id=…).
    """

    @require_permission('view_query')
    def get(self, query_id):
        try:
            project_id = request.args.get('project_id', type=int)
            q = db.session.query(TableScope).filter(
                TableScope.org_id == self.current_org.id,
                TableScope.query_id == int(query_id),
            )
            if project_id:
                logger.debug("Filtering by project_id=%s on query_id=%s", project_id, query_id)
                q = q.filter(TableScope.project_id == project_id)

            scopes = q.all()
            return jsonify([s.to_dict() for s in scopes]), 200

        except Exception as ex:
            logger.exception("Failed to fetch scopes for query_id=%s", query_id)
            abort(500, message=str(ex))


class TableScopeFilterResource(BaseResource):
    decorators = [require_permission('execute_query')]

    def get(self):
        org_id       = self.current_org.id
        project_id   = request.args.get('project_id', type=int)
        query_id     = request.args.get('query_id',   type=int)
        target_field = request.args.get('target_field')
        value        = request.args.get('value')

        if not all((project_id, query_id, target_field, value)):
            abort(400, message="project_id, query_id, target_field & value are required")

        project = Project.query.get(project_id)
        if not project or project.org_id != org_id:
            abort(404, message="Project not found")

        uid = self.current_user.id
        if project.owner_id != uid and not any(m.user_id == uid for m in project.members):
            abort(403, message="You don't belong to this project")

        query = Query.query.get(query_id)
        if not query or query.org_id != org_id:
            abort(404, message="Query not found")

        def project_ids_of(q):
            if hasattr(q, 'projects') and q.projects is not None:
                return [r.project_id for r in q.projects]
            pj = getattr(q, 'project_id', [])
            if isinstance(pj, (list, tuple)):
                return pj
            if pj is None:
                return []
            return [int(pj)]

        if project_id not in project_ids_of(query):
            abort(400, message="Query doesn't belong to given project")

        ds = DataSource.query.get(query.data_source_id)
        if not ds:
            abort(500, message="Query has no data-source (id={})".format(query.data_source_id))

        raw_sql = query.query_text.strip().rstrip(';')
        marker = ") __src"
        while marker in raw_sql:
            try:
                end = raw_sql.lower().rfind(marker)
                start = raw_sql.rfind("(", 0, end) + 1
                raw_sql = raw_sql[start:end].strip()
            except ValueError:
                break

        has_limit = any(
            tok.ttype is sqlparse.tokens.Keyword and tok.value.upper() == 'LIMIT'
            for tok in sqlparse.parse(raw_sql)[0].tokens
        )

        dialect    = ds.type.lower()
        quote_char = '`' if dialect in ('mysql', 'athena', 'presto') else '"'

        def qi(ident):
            safe = unicode(ident).replace(quote_char, quote_char * 2)
            return u'{q}{i}{q}'.format(q=quote_char, i=safe)

        def ql(val):
            return u"'{0}'".format(unicode(val).replace("'", "''"))

        derived_sql = u"""
        SELECT *
          FROM (
                {orig}
               ) __src
         WHERE {fld} = {val}
        {limit}
        """.format(
            orig=raw_sql,
            fld = qi(target_field),
            val = ql(value),
            limit='' if has_limit else 'LIMIT 1000'
        ).strip()

        logger.debug(
            "Table-Scope SQL (query #%s on %s): %s",
            query_id, ds.name, derived_sql.replace('\n',' ')
        )

        try:
            data, error = ds.query_runner.run_query(derived_sql, self.current_user)
            if error:
                logger.error("Runner error on %s: %s", ds.name, error)
                abort(500, message=error)

            if isinstance(data, (str, unicode)):
                try:
                    data = json.loads(data)
                except Exception:
                    logger.exception("Failed to parse runner output")
                    data = {}

            result = {
                'columns': data.get('columns', []),
                'rows':    data.get('rows', []),
                'sql':     derived_sql,
            }
            return jsonify(result), 200

        except Exception as ex:
            logger.exception("filter endpoint failed")
            abort(500, message=str(ex))