# -*- coding: utf-8 -*-
import sqlparse
from flask import jsonify, request, url_for, render_template, abort
from flask_login import login_required
from flask_restful import abort
from sqlalchemy.orm.exc import StaleDataError, NoResultFound
from sqlalchemy.exc import SQLAlchemyError
from funcy import partial
from sqlalchemy import cast, types

from redash.models import Project, ProjectMember, ProjectDataSource, DataSource, DataSourceApproval, User, db,Query

from redash import models, settings
from redash.authentication.org_resolving import current_org
from redash.handlers.base import (BaseResource, filter_by_tags, get_object_or_404,
                                  org_scoped_rule, paginate, routes, order_results as _order_results)
from redash.handlers.query_results import run_query
from redash.permissions import (can_modify, not_view_only, require_access,
                                require_admin_or_owner,
                                require_object_modify_permission,
                                require_permission, view_only)
from redash.handlers.permissions import require_resource_access
from redash.services.access_control import AccessControl
from redash.utils import collect_parameters_from_request
from redash.serializers import QuerySerializer
from redash.models.parameterized_query import ParameterizedQuery
import logging


logger = logging.getLogger(__name__)


# Ordering map for relationships
order_map = {
    'name': 'lowercase_name',
    '-name': '-lowercase_name',
    'created_at': 'created_at',
    '-created_at': '-created_at',
    'schedule': 'schedule',
    '-schedule': '-schedule',
    'runtime': 'query_results-runtime',
    '-runtime': '-query_results-runtime',
    'executed_at': 'query_results-retrieved_at',
    '-executed_at': '-query_results-retrieved_at',
    'created_by': 'users-name',
    '-created_by': '-users-name',
}

order_results = partial(
    _order_results,
    default_order='-created_at',
    allowed_orders=order_map,
)


@routes.route(org_scoped_rule('/api/queries/format'), methods=['POST'])
@login_required
def format_sql_query(org_slug=None):
    """
    Formats an SQL query using the Python ``sqlparse`` formatter.

    :<json string query: The SQL text to format
    :>json string query: Formatted SQL text
    """
    arguments = request.get_json(force=True)
    query = arguments.get("query", "")

    return jsonify({'query': sqlparse.format(query, **settings.SQLPARSE_FORMAT_OPTIONS)})


class QuerySearchResource(BaseResource):
    @require_permission('view_query')
    def get(self):
        """
        Search query text, names, and descriptions.

        :qparam string q: Search term
        :qparam number include_drafts: Whether to include draft in results

        Responds with a list of :ref:`query <query-response-label>` objects.
        """
        term = request.args.get('q', '')
        if not term:
            return []

        include_drafts = request.args.get('include_drafts') is not None

        self.record_event({
            'action': 'search',
            'object_type': 'query',
            'term': term,
        })

        # this redirects to the new query list API that is aware of search
        new_location = url_for(
            'queries',
            q=term,
            org_slug=current_org.slug,
            drafts='true' if include_drafts else 'false',
        )
        return {}, 301, {'Location': new_location}


class QueryRecentResource(BaseResource):
    @require_permission('view_query')
    def get(self):
        """
        Retrieve up to 10 queries recently modified by the user.
        
        :qparam string project_ids: Comma-separated list of project IDs to filter by (optional)

        Responds with a list of :ref:`query <query-response-label>` objects.
        """
        results = models.Query.by_user(self.current_user).order_by(models.Query.updated_at.desc())
        
        # Filter by project IDs if provided
        project_ids_param = request.args.get('project_ids', '')
        if project_ids_param:
            try:
                project_ids = [int(pid.strip()) for pid in project_ids_param.split(',') if pid.strip()]
                if project_ids:
                    # When dashboard has projects, ONLY show queries from those projects
                    # Explicitly exclude queries with NULL or empty project_id
                    results = results.filter(
                        models.Query.project_id.overlap(project_ids),
                        models.Query.project_id != None,
                        models.Query.project_id != []
                    )
            except ValueError:
                logger.warning("Invalid project_ids parameter: %s", project_ids_param)
        
        results = results.limit(10)
        return QuerySerializer(results, with_last_modified_by=False, with_user=False).serialize()


class BaseQueryListResource(BaseResource):

    def get_queries(self, search_term):
        # Use AccessControl to get only accessible queries for the user
        # This filters by ownership and project membership
        accessible_queries = AccessControl.get_accessible_queries(
            self.current_user, 
            self.current_org
        )
        
        # Filter by project IDs if provided
        project_ids_param = request.args.get('project_ids', '')
        if project_ids_param:
            try:
                project_ids = [int(pid.strip()) for pid in project_ids_param.split(',') if pid.strip()]
                if project_ids:
                    # When dashboard has projects, ONLY show queries from those projects
                    # Explicitly exclude queries with NULL or empty project_id
                    accessible_queries = accessible_queries.filter(
                        models.Query.project_id.overlap(project_ids),
                        models.Query.project_id != None,
                        models.Query.project_id != []
                    )
            except ValueError:
                logger.warning("Invalid project_ids parameter: %s", project_ids_param)
        
        if search_term:
            # Apply search filter on top of accessible queries
            results = accessible_queries.filter(
                models.Query.query_text.ilike('%{}%'.format(search_term)) |
                models.Query.name.ilike('%{}%'.format(search_term)) |
                models.Query.description.ilike('%{}%'.format(search_term))
            )
        else:
            results = accessible_queries
        
        return filter_by_tags(results, models.Query.tags)

    @require_permission('view_query')
    def get(self):
        """
        Retrieve a list of queries.

        :qparam number page_size: Number of queries to return per page
        :qparam number page: Page number to retrieve
        :qparam number order: Name of column to order by
        :qparam number q: Full text search term
        :qparam string project_ids: Comma-separated list of project IDs to filter by (optional)

        Responds with an array of :ref:`query <query-response-label>` objects.
        Includes ownership information and project assignments.
        
        Requirements: 10.2, 10.5
        """
        # See if we want to do full-text search or just regular queries
        search_term = request.args.get('q', '')

        queries = self.get_queries(search_term)

        results = filter_by_tags(queries, models.Query.tags)

        # order results according to passed order parameter,
        # special-casing search queries where the database
        # provides an order by search rank
        ordered_results = order_results(results, fallback=not bool(search_term))

        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 25, type=int)

        response = paginate(
            ordered_results,
            page=page,
            page_size=page_size,
            serializer=QuerySerializer,
            with_stats=True,
            with_last_modified_by=False
        )
        
        # Add can_edit flag to each query in the list
        for query_dict in response['results']:
            # Get the actual query object to check permissions
            query_obj = models.Query.get_by_id_and_org(query_dict['id'], self.current_org)
            if query_obj:
                can_edit = AccessControl.check_query_access(self.current_user, query_obj, 'edit')
                query_dict['can_edit'] = can_edit

        if search_term:
            self.record_event({
                'action': 'search',
                'object_type': 'query',
                'term': search_term,
            })
        else:
            self.record_event({
                'action': 'list',
                'object_type': 'query',
            })

        return response


def require_access_to_dropdown_queries(user, query_def):
    parameters = query_def.get('options', {}).get('parameters', [])
    dropdown_query_ids = set([str(p['queryId']) for p in parameters if p['type'] == 'query'])

    if dropdown_query_ids:
        groups = models.Query.all_groups_for_query_ids(dropdown_query_ids)

        if len(groups) < len(dropdown_query_ids):
            abort(400, message="You are trying to associate a dropdown query that does not have a matching group. "
                               "Please verify the dropdown query id you are trying to associate with this query.")

        require_access(dict(groups), user, view_only)


class QueryListResource(BaseQueryListResource):
    def post(self):
        """
        Create a new query.
        
        Permission logic:
        - Organization admins can create queries
        - Any project member (owner, admin, designer, member) can create queries
        - Users who are not members of any project cannot create queries

        :<json number data_source_id: The ID of the data source this query will run on
        :<json string query: Query text
        :<json string name:
        :<json string description:
        :<json string schedule: Schedule interval, in seconds, for repeated execution of this query
        :<json object options: Query options

        .. _query-response-label:

        :>json number id: Query ID
        :>json number latest_query_data_id: ID for latest output data from this query
        :>json string name:
        :>json string description:
        :>json string query: Query text
        :>json string query_hash: Hash of query text
        :>json string schedule: Schedule interval, in seconds, for repeated execution of this query
        :>json string api_key: Key for public access to this query's results.
        :>json boolean is_archived: Whether this query is displayed in indexes and search results or not.
        :>json boolean is_draft: Whether this query is a draft or not
        :>json string updated_at: Time of last modification, in ISO format
        :>json string created_at: Time of creation, in ISO format
        :>json number data_source_id: ID of the data source this query will run on
        :>json object options: Query options
        :>json number version: Revision version (for update conflict avoidance)
        :>json number user_id: ID of query creator
        :>json number last_modified_by_id: ID of user who last modified this query
        :>json string retrieved_at: Time when query results were last retrieved, in ISO format (may be null)
        :>json number runtime: Runtime of last query execution, in seconds (may be null)
        
        Requirements: 1.3, 1.6 - Automatically sets owner to current user
        """
        # Check if user has permission to create queries
        # Allow if: user is org admin OR user is a member of at least one project
        has_permission = False
        
        # Check if user is org admin or has create_query permission
        if self.current_user.has_permission('admin') or self.current_user.has_permission('create_query'):
            has_permission = True
            logger.info("User %s is org admin, allowing query creation", self.current_user.id)
        else:
            # Check if user is a member of any project (any role: owner, admin, designer, member)
            user_projects = ProjectMember.query.filter(
                ProjectMember.user_id == self.current_user.id
            ).first()
            
            if user_projects:
                has_permission = True
                logger.info("User %s is project member (role: %s), allowing query creation", 
                           self.current_user.id, user_projects.role)
        
        if not has_permission:
            abort(403, message="Insufficient permissions to create query. You must be an organization admin or a member of at least one project.")
        
        query_def = request.get_json(force=True)
        data_source = models.DataSource.get_by_id_and_org(query_def.pop('data_source_id'), self.current_org)
        
        # Check datasource access using new RBAC system
        # Allow if: user is owner of datasource OR user is member of project that has this datasource
        has_datasource_access = False
        
        # Check if user is owner of the datasource
        if hasattr(data_source, 'owner') and data_source.owner == self.current_user.id:
            has_datasource_access = True
            logger.info("User %s is owner of datasource %s", self.current_user.id, data_source.id)
        # Check if user is org admin
        elif self.current_user.has_permission('admin'):
            has_datasource_access = True
            logger.info("User %s is org admin, has access to datasource %s", self.current_user.id, data_source.id)
        else:
            # Check if datasource is assigned to any project the user is a member of
            user_project_ids = [pm.project_id for pm in ProjectMember.query.filter(
                ProjectMember.user_id == self.current_user.id
            ).all()]
            
            if user_project_ids:
                datasource_projects = ProjectDataSource.query.filter(
                    ProjectDataSource.data_source_id == data_source.id,
                    ProjectDataSource.project_id.in_(user_project_ids)
                ).first()
                
                if datasource_projects:
                    has_datasource_access = True
                    logger.info("User %s has access to datasource %s through project membership", 
                               self.current_user.id, data_source.id)
        
        if not has_datasource_access:
            logger.warning("User %s does not have access to datasource %s", self.current_user.id, data_source.id)
            abort(403, message="You don't have access to this datasource. The datasource must be assigned to one of your projects.")
        
        require_access_to_dropdown_queries(self.current_user, query_def)

        for field in ['id', 'created_at', 'api_key', 'visualizations', 'latest_query_data', 'last_modified_by', 'owner']:
            query_def.pop(field, None)

        query_def['query_text'] = query_def.pop('query')
        query_def['user'] = self.current_user
        query_def['data_source'] = data_source
        query_def['org'] = self.current_org
        query_def['is_draft'] = True
        query = models.Query.create(**query_def)
        
        # Set owner to current user automatically (Requirement 1.6)
        query.owner = self.current_user.id
        
        # Set query.is_shared to match datasource.is_shared for correct VDB routing
        # This ensures queries route to the correct VDB (shared vs user)
        if hasattr(data_source, 'is_shared') and data_source.is_shared:
            query.is_shared = True
            logger.info("Setting query.is_shared=TRUE for query on shared datasource %s", data_source.id)
        else:
            query.is_shared = False
        
        models.db.session.add(query)
        models.db.session.commit()
        
        # Trigger lifecycle hook for query save
        try:
            from redash.services.vdb_lifecycle_hooks import on_query_saved
            on_query_saved(query)
        except Exception as e:
            logger.error('Failed to execute query save hook: {}'.format(str(e)))
        
        # Auto-execute the query once on creation to populate the first result cache
        try:
            logger.info("CACHE DEBUG: Auto-executing query on creation - query_id=%s, query_hash=%s", 
                       query.id, query.query_hash)
            parameterized_query = ParameterizedQuery(query.query_text, org=self.current_org)
            # Trigger a background execution identical to pressing the "Execute" button
            result = run_query(parameterized_query, {}, data_source, query.id)
            logger.info("CACHE DEBUG: Auto-execution result for query %s: %s", query.id, result)
        except Exception as e:
            logger.exception('Failed to enqueue first run for query %s: %s', query.id, e)

        self.record_event({
            'action': 'create',
            'object_id': query.id,
            'object_type': 'query'
        })

        return QuerySerializer(query, with_visualizations=True).serialize()


class QueryArchiveResource(BaseQueryListResource):

    def get_queries(self, search_term):
        if search_term:
            return models.Query.search(
                search_term,
                self.current_user.group_ids,
                self.current_user.id,
                include_drafts=False,
                include_archived=True,
                multi_byte_search=current_org.get_setting('multi_byte_search_enabled'),
            )
        else:
            return models.Query.all_queries(
                self.current_user.group_ids,
                self.current_user.id,
                include_drafts=False,
                include_archived=True,
            )


class MyQueriesResource(BaseResource):
    @require_permission('view_query')
    def get(self):
        """
        Retrieve a list of queries created by the current user.

        :qparam number page_size: Number of queries to return per page
        :qparam number page: Page number to retrieve
        :qparam number order: Name of column to order by
        :qparam number search: Full text search term

        Responds with an array of :ref:`query <query-response-label>` objects.
        """
        search_term = request.args.get('q', '')
        if search_term:
            results = models.Query.search_by_user(search_term, self.current_user)
        else:
            results = models.Query.by_user(self.current_user)

        results = filter_by_tags(results, models.Query.tags)

        # order results according to passed order parameter,
        # special-casing search queries where the database
        # provides an order by search rank
        ordered_results = order_results(results, fallback=not bool(search_term))

        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 25, type=int)
        return paginate(
            ordered_results,
            page,
            page_size,
            QuerySerializer,
            with_stats=True,
            with_last_modified_by=False,
        )


class QueryResource(BaseResource):
    @require_resource_access('query', 'edit', 'query_id')
    def post(self, query_id, query_obj=None):
        """
        Modify a query.

        :param query_id: ID of query to update
        :<json number data_source_id: The ID of the data source this query will run on
        :<json string query: Query text
        :<json string name:
        :<json string description:
        :<json string schedule: Schedule interval, in seconds, for repeated execution of this query
        :<json object options: Query options
        :<json number project_id: The ID of the project associated with the query

        Responds with the updated :ref:`query <query-response-label>` object.
        
        Requirements: 1.7, 3.2, 6.4-6.8 - Validates ownership, designer role, or organization admin permission
        """
        # query_obj is provided by the decorator after access validation
        query = query_obj if query_obj else get_object_or_404(models.Query.get_by_id_and_org, query_id, self.current_org)
        query_def = request.get_json(force=True)

        # Access already validated by decorator
        require_access_to_dropdown_queries(self.current_user, query_def)

        for field in ['id', 'created_at', 'api_key', 'visualizations', 'latest_query_data', 'user', 'last_modified_by', 'org']:
            query_def.pop(field, None)

        if 'query' in query_def:
            query_def['query_text'] = query_def.pop('query')

        if 'tags' in query_def:
            query_def['tags'] = filter(None, query_def['tags'])

        # Track if project_id is being updated for auto-add datasource logic
        old_project_ids = set(query.project_id or [])
        new_project_ids = set()
        
        if 'project_id' in query_def:
            new_project_ids = set(query_def['project_id'] if isinstance(query_def['project_id'], list) else [query_def['project_id']])
            query.project_id = query_def['project_id']  # Update project_id field

        query_def['last_modified_by'] = self.current_user
        query_def['changed_by'] = self.current_user

        # SQLAlchemy handles the case where a concurrent transaction beats us
        # to the update. But we still have to make sure that we're not starting
        # out behind.
        if 'version' in query_def and query_def['version'] != query.version:
            abort(409)

        try:
            self.update_model(query, query_def)
            
            # Sync query.is_shared with datasource.is_shared for correct VDB routing
            # This ensures queries route to the correct VDB when datasource changes
            if query.data_source_id:
                data_source = models.DataSource.query.get(query.data_source_id)
                if data_source and hasattr(data_source, 'is_shared'):
                    if data_source.is_shared and not query.is_shared:
                        query.is_shared = True
                        logger.info("Updated query.is_shared=TRUE for query %s on shared datasource %s", 
                                   query.id, data_source.id)
                    elif not data_source.is_shared and query.is_shared:
                        query.is_shared = False
                        logger.info("Updated query.is_shared=FALSE for query %s on private datasource %s", 
                                   query.id, data_source.id)
            
            models.db.session.commit()
            
            # Trigger lifecycle hook for query save
            try:
                from redash.services.vdb_lifecycle_hooks import on_query_saved
                on_query_saved(query)
            except Exception as e:
                logger.error('Failed to execute query save hook: {}'.format(str(e)))
            
            # Auto-add datasource to newly added projects
            added_projects = new_project_ids - old_project_ids
            if added_projects:
                logger.info("=" * 80)
                logger.info("AUTO-ADD DATASOURCE (QueryResource.post)")
                logger.info("Query ID: %s", query_id)
                logger.info("Old projects: %s", old_project_ids)
                logger.info("New projects: %s", new_project_ids)
                logger.info("Added to projects: %s", added_projects)
                
                # Get datasource ID
                datasource_id = query.data_source_id
                if not datasource_id and query.latest_query_data:
                    datasource_id = query.latest_query_data.data_source_id
                    logger.info("Using datasource from latest_query_data: %s", datasource_id)
                
                logger.info("Datasource ID: %s", datasource_id)
                logger.info("=" * 80)
                
                if datasource_id:
                    # Use the helper method from QueryProjectResource
                    for project_id in added_projects:
                        try:
                            existing = ProjectDataSource.query.filter_by(
                                project_id=project_id,
                                data_source_id=datasource_id
                            ).first()
                            
                            if not existing:
                                project_data_source = ProjectDataSource(
                                    project_id=project_id,
                                    data_source_id=datasource_id,
                                    owner=self.current_user.id,
                                )
                                models.db.session.add(project_data_source)
                                logger.info("Auto-added datasource %s to project %s", datasource_id, project_id)
                            else:
                                logger.info("Datasource %s already in project %s", datasource_id, project_id)
                        except Exception as e:
                            logger.error("Failed to auto-add datasource %s to project %s: %s", 
                                       datasource_id, project_id, str(e), exc_info=True)
                    
                    try:
                        models.db.session.commit()
                        logger.info("Committed datasource additions")
                    except Exception as e:
                        logger.error("Failed to commit datasource additions: %s", str(e), exc_info=True)
                        models.db.session.rollback()
                else:
                    logger.warning("No datasource_id found for query %s", query_id)
                    
        except StaleDataError:
            abort(409)

        return QuerySerializer(query, with_visualizations=True).serialize()

    def get(self, query_id):
        """
        Retrieve a query.

        :param query_id: ID of query to fetch

        Responds with the :ref:`query <query-response-label>` contents.
        
        Permission logic:
        - Query owner can view
        - Organization admin can view
        - Project members can view queries assigned to their projects
        """
        q = get_object_or_404(models.Query.get_by_id_and_org, query_id, self.current_org)
        
        # Check query view access using new RBAC system
        from redash.services.access_control import AccessControl
        
        if not AccessControl.check_query_access(self.current_user, q, 'view'):
            logger.warning("User %s does not have permission to view query %s", 
                          self.current_user.id, query_id)
            abort(403, message="You don't have permission to view this query.")

        result = QuerySerializer(q, with_visualizations=True).serialize()
        
        # Calculate can_edit using RBAC system
        can_edit = AccessControl.check_query_access(self.current_user, q, 'edit')
        result['can_edit'] = can_edit
        result['project_id'] = q.project_id  # Include project_id in response
        
        # Debug logging
        logger.info(
            "Query GET: query_id=%s, query_owner=%s, current_user=%s, can_edit=%s, project_id=%s",
            query_id, q.user_id, self.current_user.id, can_edit, q.project_id
        )

        self.record_event({
            'action': 'view',
            'object_id': query_id,
            'object_type': 'query',
        })

        return result

    # TODO: move to resource of its own? (POST /queries/{id}/archive)
    @require_resource_access('query', 'delete', 'query_id')
    def delete(self, query_id, query_obj=None):
        """
        Archives a query.

        :param query_id: ID of query to archive
        
        Requirements: 1.7, 6.4-6.8 - Validates ownership or organization admin permission
        """
        # query_obj is provided by the decorator after access validation
        query = query_obj if query_obj else get_object_or_404(models.Query.get_by_id_and_org, query_id, self.current_org)
        query.archive(self.current_user)
        models.db.session.commit()



class QueryRegenerateApiKeyResource(BaseResource):
    @require_permission('edit_query')
    def post(self, query_id):
        query = get_object_or_404(models.Query.get_by_id_and_org, query_id, self.current_org)
        require_admin_or_owner(query.user_id)
        query.regenerate_api_key()
        models.db.session.commit()

        self.record_event({
            'action': 'regnerate_api_key',
            'object_id': query_id,
            'object_type': 'query',
        })

        result = QuerySerializer(query).serialize()
        return result


class QueryForkResource(BaseResource):
    @require_permission('edit_query')
    def post(self, query_id):
        """
        Creates a new query, copying the query text from an existing one.

        :param query_id: ID of query to fork

        Responds with created :ref:`query <query-response-label>` object.
        """
        query = get_object_or_404(models.Query.get_by_id_and_org, query_id, self.current_org)
        require_access(query.data_source, self.current_user, not_view_only)
        forked_query = query.fork(self.current_user)
        models.db.session.commit()

        self.record_event({
            'action': 'fork',
            'object_id': query_id,
            'object_type': 'query',
        })

        return QuerySerializer(forked_query, with_visualizations=True).serialize()


class QueryRefreshResource(BaseResource):
    def post(self, query_id):
        """
        Execute a query, updating the query object with the results.

        :param query_id: ID of query to execute

        Responds with query task details.
        
        Permission logic:
        - Query owner can execute
        - Organization admin can execute
        - Project members can execute queries assigned to their projects
        """
        if self.current_user.is_api_user():
            abort(403, message="Please use a user API key.")

        query = get_object_or_404(models.Query.get_by_id_and_org, query_id, self.current_org)
        
        # Check query execution access using new RBAC system
        has_execute_access = False
        
        # Check if user is owner of the query
        if query.user_id == self.current_user.id:
            has_execute_access = True
            logger.info("User %s is owner of query %s", self.current_user.id, query_id)
        # Check if user is org admin
        elif self.current_user.has_permission('admin') or self.current_user.has_permission('execute_query'):
            has_execute_access = True
            logger.info("User %s is org admin, can execute query %s", self.current_user.id, query_id)
        else:
            # Check if query is assigned to any project the user is a member of
            user_project_ids = [pm.project_id for pm in ProjectMember.query.filter(
                ProjectMember.user_id == self.current_user.id
            ).all()]
            
            if query.project_id and user_project_ids:
                # Check if any of the query's projects match user's projects
                query_projects = query.project_id if isinstance(query.project_id, list) else [query.project_id]
                if set(query_projects) & set(user_project_ids):
                    has_execute_access = True
                    logger.info("User %s can execute query %s through project membership", 
                               self.current_user.id, query_id)
            elif user_project_ids:
                # If query has no project assigned yet but user is a project member,
                # allow execution (query might be in the process of being assigned)
                has_execute_access = True
                logger.info("User %s is a project member, allowing execution of unassigned query %s", 
                           self.current_user.id, query_id)
        
        if not has_execute_access:
            logger.warning("User %s does not have permission to execute query %s", 
                          self.current_user.id, query_id)
            abort(403, message="You don't have permission to execute this query. The query must be assigned to one of your projects.")
        
        # Also check datasource access
        # If user is query owner, they automatically have datasource access
        has_datasource_access = False
        data_source = query.data_source
        
        # Query owner automatically has datasource access
        if query.user_id == self.current_user.id:
            has_datasource_access = True
            logger.info("User %s is query owner, has datasource access for query %s", 
                       self.current_user.id, query_id)
        elif hasattr(data_source, 'owner') and data_source.owner == self.current_user.id:
            has_datasource_access = True
            logger.info("User %s is datasource owner, has access for query %s", 
                       self.current_user.id, query_id)
        elif self.current_user.has_permission('admin'):
            has_datasource_access = True
            logger.info("User %s is admin, has datasource access for query %s", 
                       self.current_user.id, query_id)
        else:
            user_project_ids = [pm.project_id for pm in ProjectMember.query.filter(
                ProjectMember.user_id == self.current_user.id
            ).all()]
            
            if user_project_ids:
                datasource_projects = ProjectDataSource.query.filter(
                    ProjectDataSource.data_source_id == data_source.id,
                    ProjectDataSource.project_id.in_(user_project_ids)
                ).first()
                
                if datasource_projects:
                    has_datasource_access = True
                    logger.info("User %s has datasource access through project membership for query %s", 
                               self.current_user.id, query_id)
        
        if not has_datasource_access:
            logger.warning("User %s does not have access to datasource %s for query %s", 
                          self.current_user.id, data_source.id, query_id)
            abort(403, message="You don't have access to the datasource used by this query.")

        parameter_values = collect_parameters_from_request(request.args)
        parameterized_query = ParameterizedQuery(query.query_text, org=self.current_org)

        return run_query(parameterized_query, parameter_values, query.data_source, query.id)


class QueryTagsResource(BaseResource):
    def get(self):
        """
        Returns all query tags including those for drafts.
        """
        tags = models.Query.all_tags(self.current_user, include_drafts=True)
        return {
            'tags': [
                {
                    'name': name,
                    'count': count,
                }
                for name, count in tags
            ]
        }


class QueryFavoriteListResource(BaseResource):
    def get(self):
        search_term = request.args.get('q')

        if search_term:
            base_query = models.Query.search(search_term, self.current_user.group_ids, include_drafts=True, limit=None)
            favorites = models.Query.favorites(self.current_user, base_query=base_query)
        else:
            favorites = models.Query.favorites(self.current_user)

        favorites = filter_by_tags(favorites, models.Query.tags)

        # order results according to passed order parameter,
        # special-casing search queries where the database
        # provides an order by search rank
        ordered_favorites = order_results(favorites, fallback=not bool(search_term))

        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 25, type=int)
        response = paginate(
            ordered_favorites,
            page,
            page_size,
            QuerySerializer,
            with_stats=True,
            with_last_modified_by=False,
        )

        self.record_event({
            'action': 'load_favorites',
            'object_type': 'query',
            'params': {
                'q': search_term,
                'tags': request.args.getlist('tags'),
                'page': page
            }
        })

        return response

class QueryProjectResource(BaseResource):
    """Endpoint to handle project tagging for queries."""

    def _auto_add_datasource_to_projects(self, data_source_id, project_ids):
        """
        Automatically add a datasource to projects when a query using it is added.
        This ensures datasources are available in the project for the query to work.
        """
        logger.info("=" * 80)
        logger.info("_auto_add_datasource_to_projects CALLED")
        logger.info("  data_source_id: %s (type: %s)", data_source_id, type(data_source_id))
        logger.info("  project_ids: %s (type: %s)", project_ids, type(project_ids))
        logger.info("  current_user.id: %s", self.current_user.id)
        logger.info("=" * 80)
        
        added_count = 0
        for project_id in project_ids:
            logger.info("  Processing project_id: %s", project_id)
            try:
                # Check if datasource is already in the project
                logger.info("    Checking if datasource %s exists in project %s", data_source_id, project_id)
                existing = ProjectDataSource.query.filter_by(
                    project_id=project_id,
                    data_source_id=data_source_id
                ).first()
                
                logger.info("    Existing mapping found: %s", existing is not None)
                
                if not existing:
                    # Add the datasource to the project
                    project_data_source = ProjectDataSource(
                        project_id=project_id,
                        data_source_id=data_source_id,
                        owner=self.current_user.id,
                    )
                    db.session.add(project_data_source)
                    added_count += 1
                    logger.info(
                        "Auto-added datasource %s to project %s for query compatibility",
                        data_source_id, project_id
                    )
                else:
                    logger.info(
                        "Datasource %s already exists in project %s, skipping",
                        data_source_id, project_id
                    )
            except Exception as e:
                logger.error(
                    "Failed to auto-add datasource %s to project %s: %s",
                    data_source_id, project_id, str(e), exc_info=True
                )
                # Don't fail the entire operation if one datasource addition fails
                continue
        
        if added_count > 0:
            try:
                db.session.commit()
                logger.info("Successfully committed %d datasource additions", added_count)
            except Exception as e:
                logger.error("Failed to commit datasource additions: %s", str(e), exc_info=True)
                db.session.rollback()
        else:
            logger.info("No new datasources to add")

    @require_permission('edit_query')
    def post(self, query_id):
        """
        Assign selected projects to a query.

        :param query_id: ID of the query
        :<json list project_ids: List of project IDs to associate with the query
        """
        logger.info("=" * 80)
        logger.info("QueryProjectResource.post() CALLED")
        logger.info("query_id: %s", query_id)
        logger.info("=" * 80)
        
        query = Query.get_by_id_and_org(query_id, self.current_org)
        if not query:
            return {"error": "Query not found."}, 404

        require_object_modify_permission(query, self.current_user)

        try:
            payload = request.get_json(force=True)
            project_ids = payload.get("project_ids", [])

            logger.debug("Payload received for query_id %s: %s", query_id, payload)

            if not isinstance(project_ids, list):
                logger.error("Invalid project_ids format: expected a list")
                return {"error": "Invalid format. Expected a list of project IDs."}, 400

            # Verify user owns or is a member of the projects
            current_user_id = self.current_user.id
            allowed_projects = Project.query.filter(
                (Project.owner_id == current_user_id) |
                (Project.id.in_(
                    [p.project_id for p in ProjectMember.query.filter_by(user_id=current_user_id)]
                ))
            ).all()

            allowed_project_ids = {project.id for project in allowed_projects}
            invalid_projects = set(project_ids) - allowed_project_ids

            if invalid_projects:
                logger.error("Invalid project IDs: %s", list(invalid_projects))
                return {
                    "error": "You do not have permission to add these projects.",
                    "invalid_projects": list(invalid_projects)
                }, 403

            # Assign projects to query
            query.project_id = project_ids
            query.last_modified_by = self.current_user

            db.session.add(query)  # Explicitly add the query object to the session
            db.session.commit()

            logger.info("Query updated successfully: query_id=%s, project_ids=%s", query_id, project_ids)

            # Auto-add the query's datasource(s) to the project(s)
            logger.info("=" * 80)
            logger.info("AUTO-ADD DATASOURCE DEBUG")
            logger.info("Query ID: %s", query_id)
            logger.info("Query data_source_id: %s", query.data_source_id)
            
            # Try to get datasource from query, or fallback to latest_query_data
            datasource_id = query.data_source_id
            if not datasource_id and query.latest_query_data:
                datasource_id = query.latest_query_data.data_source_id
                logger.info("Using datasource from latest_query_data: %s", datasource_id)
            
            logger.info("Final datasource_id to use: %s", datasource_id)
            logger.info("Project IDs: %s", project_ids)
            logger.info("=" * 80)
            
            if datasource_id:
                logger.info("Query has datasource, proceeding with auto-add")
                try:
                    self._auto_add_datasource_to_projects(datasource_id, project_ids)
                    logger.info("Auto-add datasource completed successfully")
                except Exception as e:
                    logger.error("Auto-add datasource failed: %s", str(e), exc_info=True)
            else:
                logger.warning("Query %s has no data_source_id and no latest_query_data, skipping auto-add", query_id)

            return {
                "message": "Projects assigned successfully",
                "query_id": query.id,
                "projects": query.project_id
            }, 200

        except SQLAlchemyError as e:
            logger.exception("Database error while updating query_id %s with project_ids %s", query_id, project_ids)
            db.session.rollback()
            return {"error": "Failed to assign projects due to a database error."}, 500

        except Exception as e:
            logger.exception("Unexpected error while updating query_id %s: %s", query_id, str(e))
            return {"error": "An unexpected error occurred."}, 500

    @require_permission('view_query')
    def get(self, query_id):
        """
        Fetch all projects (private & public) available for tagging.

        :param query_id: ID of the query
        """
        try:
            current_user_id = self.current_user.id

            # Fetch all projects where the user is involved (as owner or member)
            projects = Project.query.outerjoin(ProjectMember).filter(
                (Project.owner_id == current_user_id) | (ProjectMember.user_id == current_user_id)
            ).all()

            # Remove any duplicate projects (if any)
            projects_by_id = {project.id: project for project in projects}
            projects = list(projects_by_id.values())

            private_projects = []
            public_projects = []

            for project in projects:
                # Assume project.members is a list of member objects with attribute user_id.
                # If there's any member other than the current user, consider the project public.
                other_members = [m for m in project.members if m.user_id != current_user_id]
                if other_members:
                    public_projects.append(project.to_dict())
                else:
                    private_projects.append(project.to_dict())

            logger.debug("Projects fetched for query_id %s: private=%s, public=%s",
                         query_id, private_projects, public_projects)

            return {
                "private_projects": private_projects,
                "public_projects": public_projects
            }, 200

        except Exception as e:
            logger.exception("Error fetching projects for query_id %s: %s", query_id, str(e))
            return {"error": "Failed to fetch projects due to an internal error."}, 500

class MyUnassignedQueryListResource(BaseResource):
    """
    GET /api/my_unassigned_queries
    Returns every query where:
      * owner  == current_user.id
      * project_id IS NULL or an empty JSON object '{}'
    """

    def get(self):
        q = (
            models.Query.query
            .filter(models.Query.owner == self.current_user.id)
            .filter(
                (models.Query.project_id == None) |
                (cast(models.Query.project_id, types.String) == '{}')
            )
            .order_by(models.Query.created_at.desc())
        )

        results = [{
            "id":        query.id,
            "name":      query.name,
            "query":     query.query_text,
            "created_at": query.created_at,
            "owner":     query.owner,
            "project_id": query.project_id
        } for query in q]

        return jsonify({"count": len(results), "results": results})


@routes.route(org_scoped_rule('/queries/<int:query_id>/edit'))
@login_required
def edit_query(query_id, org_slug=None):
    logger.debug("edit_query: Received query_id: %s", query_id)
    query = Query.get_by_id_and_org(query_id, current_org)
    if not query:
        logger.error("edit_query: Query not found for query_id: %s", query_id)
        abort(404)
    logger.debug("edit_query: Loaded query: %s", query)
    return render_template('query_editor.html', query=query)


from sqlalchemy import or_

class ProjectAvailableQueriesResource(BaseResource):
    @require_permission('view_query')
    def get(self, project_id):
        pid = int(project_id)
        uid = self.current_user.id
        q = (Query.query
             .filter(Query.owner == uid)
             .filter(or_(Query.project_id.is_(None), ~Query.project_id.contains([pid])))
             .order_by(Query.updated_at.desc()))
        return jsonify([{
            'id': x.id,
            'name': x.name,
            'project_ids': x.project_id,
            'created_at': x.created_at.isoformat() if x.created_at else None,
            'updated_at': x.updated_at.isoformat() if x.updated_at else None,
            'created_by': x.user.name if getattr(x, 'user', None) else None,
            'data_source': x.data_source.name if getattr(x, 'data_source', None) else None
        } for x in q])

    @require_permission('edit_query')
    def post(self, project_id):
        data = request.get_json(force=True) or {}
        raw = data.get('query_ids') if 'query_ids' in data else data.get('query_id', [])
        requested = set(raw if isinstance(raw, list) else [raw]) if raw != [] else set()
        pid = int(project_id)

        # linked queries regardless of owner; permission checked per row
        linked = Query.query.filter(Query.project_id.contains([pid])).all()
        linked_ids = {q.id for q in linked}

        # removals
        for q in linked:
            if q.id not in requested:
                try:
                    require_object_modify_permission(q, self.current_user)
                except Exception:
                    continue
                q.project_id = [p for p in q.project_id if p != pid]
                q.last_modified_by = self.current_user
                db.session.add(q)

        # additions
        queries_to_auto_add_datasource = []
        for qid in requested - linked_ids:
            try:
                q = Query.get_by_id_and_org(qid, self.current_org)
            except NoResultFound:
                continue
            try:
                require_object_modify_permission(q, self.current_user)
            except Exception:
                continue
            if pid not in (q.project_id or []):
                q.project_id = (q.project_id or []) + [pid]
                q.last_modified_by = self.current_user
                db.session.add(q)
                queries_to_auto_add_datasource.append(q)

        try:
            db.session.commit()
            
            # Auto-add datasources for newly added queries
            if queries_to_auto_add_datasource:
                logger.info("=" * 80)
                logger.info("AUTO-ADD DATASOURCE (ProjectAvailableQueriesResource.post)")
                logger.info("Project ID: %s", pid)
                logger.info("Queries added: %s", [q.id for q in queries_to_auto_add_datasource])
                
                for q in queries_to_auto_add_datasource:
                    # Get datasource ID
                    datasource_id = q.data_source_id
                    if not datasource_id and q.latest_query_data:
                        datasource_id = q.latest_query_data.data_source_id
                        logger.info("Query %s: Using datasource from latest_query_data: %s", q.id, datasource_id)
                    
                    if datasource_id:
                        try:
                            existing = ProjectDataSource.query.filter_by(
                                project_id=pid,
                                data_source_id=datasource_id
                            ).first()
                            
                            if not existing:
                                project_data_source = ProjectDataSource(
                                    project_id=pid,
                                    data_source_id=datasource_id,
                                    owner=self.current_user.id,
                                )
                                db.session.add(project_data_source)
                                logger.info("Auto-added datasource %s to project %s for query %s", 
                                          datasource_id, pid, q.id)
                            else:
                                logger.info("Datasource %s already in project %s", datasource_id, pid)
                        except Exception as e:
                            logger.error("Failed to auto-add datasource %s to project %s: %s", 
                                       datasource_id, pid, str(e), exc_info=True)
                    else:
                        logger.warning("Query %s has no datasource_id", q.id)
                
                try:
                    db.session.commit()
                    logger.info("✓ Committed datasource additions")
                    logger.info("=" * 80)
                except Exception as e:
                    logger.error("Failed to commit datasource additions: %s", str(e), exc_info=True)
                    db.session.rollback()
                    
        except SQLAlchemyError as exc:
            db.session.rollback()
            return jsonify({'error': str(exc)}), 500
        return jsonify({'status':'ok'}), 200


class QueryDeleteResource(BaseResource):
    @require_permission('edit_query')
    def delete(self, query_id):
        """
        Permanently deletes a query and all its related data.
        
        :param query_id: The ID of the query to delete
        
        Responds with success message.
        """
        try:
            logger.info("Deleting query {}".format(query_id))
            
            # Get query by ID and organization
            query = models.Query.query.filter(
                models.Query.id == query_id,
                models.Query.org == self.current_org
            ).first()
            
            if not query:
                abort(404, message="Query not found")
            
            # Check permissions
            require_admin_or_owner(query.user_id)
            
            logger.info("Query found: {} (hash: {})".format(query.name, query.query_hash))
            
            # Use the same approach as the archive method but actually delete
            # This follows the existing pattern and should be more reliable
            
            # 1. Delete widgets for each visualization (similar to archive method)
            for vis in query.visualizations:
                logger.info("Processing visualization {}".format(vis.id))
                for w in vis.widgets:
                    logger.info("Deleting widget {}".format(w.id))
                    models.db.session.delete(w)
            
            # 2. Delete alerts (similar to archive method)
            for a in query.alerts:
                logger.info("Deleting alert {}".format(a.id))
                # Delete alert subscriptions first
                subscriptions = models.AlertSubscription.query.filter_by(alert_id=a.id).all()
                for sub in subscriptions:
                    logger.info("Deleting alert subscription {}".format(sub.id))
                    models.db.session.delete(sub)
                models.db.session.delete(a)
            
            # 3. Delete visualizations
            for vis in list(query.visualizations):
                logger.info("Deleting visualization {}".format(vis.id))
                models.db.session.delete(vis)
            
            # 4. Delete favorites
            favorites = models.Favorite.query.filter_by(
                object_type='Query',
                object_id=query.id
            ).all()
            for favorite in favorites:
                logger.info("Deleting favorite {}".format(favorite.id))
                models.db.session.delete(favorite)
            
            # 5. Delete column layouts that reference this query
            # This is what was causing the NOT NULL constraint violation
            # Use direct SQL to avoid model import issues
            logger.info("Deleting column layouts via direct query")
            result = models.db.session.execute(
                "DELETE FROM column_layouts WHERE query_id = :query_id",
                {"query_id": query.id}
            )
            logger.info("Deleted {} column layout records".format(result.rowcount))
            
            # 6. Delete table scopes that reference this query
            logger.info("Deleting table scopes via direct query")
            result = models.db.session.execute(
                "DELETE FROM table_scopes WHERE query_id = :query_id",
                {"query_id": query.id}
            )
            logger.info("Deleted {} table scope records".format(result.rowcount))
            
            # 7. Clear latest_query_data_id BEFORE deleting query results
            # This is critical to avoid foreign key constraint violations
            # We need to clear references from ALL queries that might reference the same query results
            if query.query_hash and query.data_source_id:
                logger.info("Clearing latest_query_data_id references for all queries with same hash")
                # Clear references from all queries that share the same query_hash and data_source
                models.db.session.execute(
                    "UPDATE queries SET latest_query_data_id = NULL WHERE query_hash = :query_hash AND data_source_id = :data_source_id",
                    {"query_hash": query.query_hash, "data_source_id": query.data_source_id}
                )
                models.db.session.flush()  # Flush to database immediately
                logger.info("Cleared latest_query_data_id references")
            
            # 8. Now we can safely delete query results
            # Check for any query results that might still reference this query
            if query.query_hash and query.data_source_id:
                logger.info("Deleting query results via direct query")
                result = models.db.session.execute(
                    "DELETE FROM query_results WHERE query_hash = :query_hash AND data_source_id = :data_source_id",
                    {"query_hash": query.query_hash, "data_source_id": query.data_source_id}
                )
                logger.info("Deleted {} query result records".format(result.rowcount))
            else:
                logger.info("Skipping query results deletion (no hash or data_source_id)")
            
            # 9. Delete the query itself
            logger.info("Deleting query {}".format(query.id))
            models.db.session.delete(query)
            
            # Commit all changes
            models.db.session.commit()
            logger.info("Query {} and all related data deleted successfully".format(query_id))
            
            # Log the event
            self.record_event({
                'action': 'delete',
                'object_id': query.id,
                'object_type': 'query',
            })
            
            logger.info("Query {} deleted successfully".format(query_id))
            return {'message': 'Query deleted successfully'}
            
        except Exception as e:
            logger.error("Error deleting query {}: {}".format(query_id, str(e)), exc_info=True)
            models.db.session.rollback()
            # Return a more user-friendly error message
            error_msg = "Failed to delete query"
            if "foreign key" in str(e).lower():
                error_msg = "Cannot delete query: it has dependent data that must be removed first"
            elif "permission" in str(e).lower():
                error_msg = "You don't have permission to delete this query"
            abort(500, message=error_msg) 
