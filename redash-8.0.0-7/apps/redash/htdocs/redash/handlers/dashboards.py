from flask import request, url_for, jsonify
from funcy import project, partial

from flask_restful import abort
from redash import models, serializers
from redash.handlers.base import (BaseResource, get_object_or_404, paginate,
                                  filter_by_tags,
                                  order_results as _order_results)
from redash.permissions import (can_modify, require_admin_or_owner,
                                require_object_modify_permission,
                                require_permission)
from redash.security import csp_allows_embeding
from redash.serializers import serialize_dashboard, QuerySerializer
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.exc import SQLAlchemyError
from redash.models import Project, ProjectMember, ProjectDataSource, DataSource, DataSourceApproval, User, db, Query, Dashboard

import logging


logger = logging.getLogger(__name__)

# Ordering map for relationships
order_map = {
    'name': 'lowercase_name',
    '-name': '-lowercase_name',
    'created_at': 'created_at',
    '-created_at': '-created_at',
}

order_results = partial(
    _order_results,
    default_order='-created_at',
    allowed_orders=order_map,
)

logger = logging.getLogger(__name__)


class DashboardListResource(BaseResource):
    @require_permission('list_dashboards')
    def get(self):
        """
        Lists all accessible dashboards.

        :qparam number page_size: Number of dashboards to return per page
        :qparam number page: Page number to retrieve
        :qparam string order: Column name to order by
        :qparam string q: Full text search term

        Responds with an array of :ref:`dashboard <dashboard-response-label>` objects.
        """
        search_term = request.args.get('q')

        if search_term:
            results = models.Dashboard.search(
                self.current_org,
                self.current_user.group_ids,
                self.current_user.id,
                search_term,
            )
        else:
            results = models.Dashboard.all(
                self.current_org,
                self.current_user.group_ids,
                self.current_user.id,
            )

        results = filter_by_tags(results, models.Dashboard.tags)
        ordered_results = order_results(results, fallback=not bool(search_term))
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 25, type=int)

        response = paginate(
            ordered_results,
            page=page,
            page_size=page_size,
            serializer=serialize_dashboard,
        )

        if search_term:
            self.record_event({
                'action': 'search',
                'object_type': 'dashboard',
                'term': search_term,
            })
        else:
            self.record_event({
                'action': 'list',
                'object_type': 'dashboard',
            })

        return response

    @require_permission('create_dashboard')
    def post(self):
        """
        Creates a new dashboard.

        :<json string name: Dashboard name

        Responds with a :ref:`dashboard <dashboard-response-label>`.
        """
        dashboard_properties = request.get_json(force=True)
        dashboard = models.Dashboard(
            name=dashboard_properties['name'],
            org=self.current_org,
            user=self.current_user,
            is_draft=True,
            layout='[]'
        )
        models.db.session.add(dashboard)
        models.db.session.commit()
        return serialize_dashboard(dashboard)


class DashboardResource(BaseResource):
    @require_permission('list_dashboards')
    def get(self, dashboard_slug=None):
        """
        Retrieves a dashboard.

        :qparam string slug: Slug of dashboard to retrieve.

        .. _dashboard-response-label:

        :>json number id: Dashboard ID
        :>json string name:
        :>json string slug:
        :>json number user_id: ID of the dashboard creator
        :>json string created_at: ISO format timestamp for dashboard creation
        :>json string updated_at: ISO format timestamp for last dashboard modification
        :>json number version: Revision number of dashboard
        :>json boolean dashboard_filters_enabled: Whether filters are enabled or not
        :>json boolean is_archived: Whether this dashboard has been removed from the index or not
        :>json boolean is_draft: Whether this dashboard is a draft or not.
        :>json array layout: Array of arrays containing widget IDs, corresponding to the rows and columns the widgets are displayed in
        :>json array widgets: Array of arrays containing :ref:`widget <widget-response-label>` data

        .. _widget-response-label:

        Widget structure:

        :>json number widget.id: Widget ID
        :>json number widget.width: Widget size
        :>json object widget.options: Widget options
        :>json number widget.dashboard_id: ID of dashboard containing this widget
        :>json string widget.text: Widget contents, if this is a text-box widget
        :>json object widget.visualization: Widget contents, if this is a visualization widget
        :>json string widget.created_at: ISO format timestamp for widget creation
        :>json string widget.updated_at: ISO format timestamp for last widget modification
        """
        dashboard = get_object_or_404(models.Dashboard.get_by_slug_and_org, dashboard_slug, self.current_org)
        response = serialize_dashboard(dashboard, with_widgets=True, user=self.current_user)

        api_key = models.ApiKey.get_by_object(dashboard)
        if api_key:
            response['public_url'] = url_for('redash.public_dashboard',
                                             token=api_key.api_key,
                                             org_slug=self.current_org.slug,
                                             _external=True)
            response['api_key'] = api_key.api_key

        response['can_edit'] = can_modify(dashboard, self.current_user)

        self.record_event({
            'action': 'view',
            'object_id': dashboard.id,
            'object_type': 'dashboard',
        })

        return response

    @require_permission('edit_dashboard')
    def post(self, dashboard_slug):
        """
        Modifies a dashboard.

        :qparam string slug: Slug of dashboard to retrieve.

        Responds with the updated :ref:`dashboard <dashboard-response-label>`.

        :status 200: success
        :status 409: Version conflict -- dashboard modified since last read
        """
        dashboard_properties = request.get_json(force=True)
        # TODO: either convert all requests to use slugs or ids
        dashboard = models.Dashboard.get_by_id_and_org(dashboard_slug, self.current_org)

        require_object_modify_permission(dashboard, self.current_user)

        updates = project(dashboard_properties, ('name', 'layout', 'version', 'tags',
                                                 'is_draft', 'dashboard_filters_enabled'))

        if 'version' in updates and updates['version'] != dashboard.version:
            abort(409)

        updates['changed_by'] = self.current_user

        self.update_model(dashboard, updates)
        models.db.session.add(dashboard)
        try:
            models.db.session.commit()
        except StaleDataError:
            abort(409)

        result = serialize_dashboard(dashboard, with_widgets=True, user=self.current_user)

        self.record_event({
            'action': 'edit',
            'object_id': dashboard.id,
            'object_type': 'dashboard',
        })

        return result

    @require_permission('edit_dashboard')
    def delete(self, dashboard_slug):
        """
        Archives a dashboard.

        :qparam string slug: Slug of dashboard to retrieve.

        Responds with the archived :ref:`dashboard <dashboard-response-label>`.
        """
        dashboard = models.Dashboard.get_by_slug_and_org(dashboard_slug, self.current_org)
        dashboard.is_archived = True
        dashboard.record_changes(changed_by=self.current_user)
        models.db.session.add(dashboard)
        d = serialize_dashboard(dashboard, with_widgets=True, user=self.current_user)
        models.db.session.commit()

        self.record_event({
            'action': 'archive',
            'object_id': dashboard.id,
            'object_type': 'dashboard',
        })

        return d


class PublicDashboardResource(BaseResource):
    decorators = BaseResource.decorators + [csp_allows_embeding]

    def get(self, token):
        """
        Retrieve a public dashboard.

        :param token: An API key for a public dashboard.
        :>json array widgets: An array of arrays of :ref:`public widgets <public-widget-label>`, corresponding to the rows and columns the widgets are displayed in
        """
        if not isinstance(self.current_user, models.ApiUser):
            api_key = get_object_or_404(models.ApiKey.get_by_api_key, token)
            dashboard = api_key.object
        else:
            dashboard = self.current_user.object

        return serializers.public_dashboard(dashboard)


class DashboardShareResource(BaseResource):
    def post(self, dashboard_id):
        """
        Allow anonymous access to a dashboard.

        :param dashboard_id: The numeric ID of the dashboard to share.
        :>json string public_url: The URL for anonymous access to the dashboard.
        :>json api_key: The API key to use when accessing it.
        """
        dashboard = models.Dashboard.get_by_id_and_org(dashboard_id, self.current_org)
        require_admin_or_owner(dashboard.user_id)
        api_key = models.ApiKey.create_for_object(dashboard, self.current_user)
        models.db.session.flush()
        models.db.session.commit()

        public_url = url_for('redash.public_dashboard',
                             token=api_key.api_key,
                             org_slug=self.current_org.slug,
                             _external=True)

        self.record_event({
            'action': 'activate_api_key',
            'object_id': dashboard.id,
            'object_type': 'dashboard',
        })

        return {'public_url': public_url, 'api_key': api_key.api_key}

    def delete(self, dashboard_id):
        """
        Disable anonymous access to a dashboard.

        :param dashboard_id: The numeric ID of the dashboard to unshare.
        """
        dashboard = models.Dashboard.get_by_id_and_org(dashboard_id, self.current_org)
        require_admin_or_owner(dashboard.user_id)
        api_key = models.ApiKey.get_by_object(dashboard)

        if api_key:
            api_key.active = False
            models.db.session.add(api_key)
            models.db.session.commit()

        self.record_event({
            'action': 'deactivate_api_key',
            'object_id': dashboard.id,
            'object_type': 'dashboard',
        })


class DashboardTagsResource(BaseResource):
    @require_permission('list_dashboards')
    def get(self):
        """
        Lists all accessible dashboards.
        """
        tags = models.Dashboard.all_tags(self.current_org, self.current_user)
        return {
            'tags': [
                {
                    'name': name,
                    'count': count,
                }
                for name, count in tags
            ]
        }


class DashboardFavoriteListResource(BaseResource):
    def get(self):
        search_term = request.args.get('q')

        if search_term:
            base_query = models.Dashboard.search(
                self.current_org,
                self.current_user.group_ids,
                self.current_user.id,
                search_term
            )
            favorites = models.Dashboard.favorites(self.current_user, base_query=base_query)
        else:
            favorites = models.Dashboard.favorites(self.current_user)

        favorites = filter_by_tags(favorites, models.Dashboard.tags)
        favorites = order_results(favorites, fallback=not bool(search_term))
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 25, type=int)
        response = paginate(favorites, page, page_size, serialize_dashboard)

        self.record_event({
            'action': 'load_favorites',
            'object_type': 'dashboard',
            'params': {
                'q': search_term,
                'tags': request.args.getlist('tags'),
                'page': page
            }
        })

        return response


class DashboardProjectResource(BaseResource):
    # @require_permission('view_dashboard')
    def get(self, dashboard_id):
        """
        Retrieve a dashboard by its numeric ID and return a minimal JSON object
        containing its name, id, project_id, and user.
        """
        # Lookup dashboard by its integer ID and current organization
        dashboard = Dashboard.query.filter_by(id=dashboard_id, org_id=self.current_org.id).first()
        if not dashboard:
            return jsonify({"error": "Dashboard not found."}), 404

        # Build the response.
        # (Assumes that dashboard.project_id is either an integer or None.)
        response = {
            "id": dashboard.id,
            "name": dashboard.name,
            "project_id": dashboard.project_id,
            "user": dashboard.user.to_dict() if dashboard.user else None
        }
        return jsonify(response)


# NEW --- Resource to safely search queries within a dashboard's project
# In dashboards.py

class DashboardQuerySearchResource(BaseResource):
    @require_permission('view_query')
    def get(self, dashboard_id):
        dashboard = get_object_or_404(models.Dashboard.get_by_id_and_org, dashboard_id, self.current_org)

        # A dashboard can be in one or more projects.
        # The project_id field can be a list. Let's safely take the first one.
        project_ids = dashboard.project_id
        if not project_ids:
            # If dashboard is not in a project, return a correctly formatted empty response.
            return jsonify({'count': 0, 'page': 1, 'page_size': 0, 'results': []})

        # Handle both list and single int for project_id for robustness
        first_project_id = project_ids[0] if isinstance(project_ids, list) else project_ids

        project = get_object_or_404(models.Project.get_by_id_and_org, first_project_id, self.current_org)

        search_term = request.args.get('q', '').lower()

        # Get all queries from the project
        project_queries = project.queries

        results = []
        if search_term:
            # Filter the project's queries by the search term
            for query in project_queries:
                if search_term in query.name.lower():
                    results.append(query)
        else:
            results = list(project_queries)

        # Use the full QuerySerializer to ensure all needed data is sent to the frontend.
        serialized_results = QuerySerializer(results, with_stats=False, with_last_modified_by=False).serialize()

        # Wrap the results in the standard paginated response object.
        response_data = {
            'count': len(serialized_results),
            'page': 1,
            'page_size': len(serialized_results), # Return all results in one page
            'results': serialized_results
        }

        return jsonify(response_data)


class ProjectDashboardCreateResource(BaseResource):
    @require_permission('create_dashboard')
    def post(self, project_id):
        """
        Creates a new dashboard and assigns it to the specified project.
        
        :param project_id: The ID of the project to assign the dashboard to
        :<json string name: Dashboard name
        
        Responds with a :ref:`dashboard <dashboard-response-label>` with project_id set.
        """
        try:
            logger.info("Creating dashboard for project {}".format(project_id))
            dashboard_properties = request.get_json(force=True)
            
            if not dashboard_properties or 'name' not in dashboard_properties:
                abort(400, message="Dashboard name is required")
            
            # Validate that the project exists and user has access
            project = get_object_or_404(models.Project.get_by_id_and_org, project_id, self.current_org)
            logger.info("Project {} found: {}".format(project_id, project.name))
            
            # Create dashboard - try with project_id first, fallback if column doesn't exist
            try:
                dashboard = models.Dashboard(
                    name=dashboard_properties['name'],
                    org=self.current_org,
                    user=self.current_user,
                    project_id=project_id,  # Assign to project
                    is_draft=True,
                    layout='[]'
                )
            except Exception as e:
                logger.warning("Failed to create dashboard with project_id, trying without: {}".format(str(e)))
                # Fallback: create without project_id if column doesn't exist
                dashboard = models.Dashboard(
                    name=dashboard_properties['name'],
                    org=self.current_org,
                    user=self.current_user,
                    is_draft=True,
                    layout='[]'
                )
            
            logger.info("Dashboard object created: {}".format(dashboard.name))
            
            models.db.session.add(dashboard)
            models.db.session.commit()
            
            logger.info("Dashboard {} committed to database".format(dashboard.id))
            
            # Log the event
            self.record_event({
                'action': 'create',
                'object_id': dashboard.id,
                'object_type': 'dashboard',
                'project_id': project_id,
            })
            
            result = serialize_dashboard(dashboard)
            logger.info("Dashboard serialized successfully")
            return result
            
        except Exception as e:
            logger.error("Error creating dashboard for project {}: {}".format(project_id, str(e)), exc_info=True)
            models.db.session.rollback()
            abort(500, message="Failed to create dashboard: {}".format(str(e)))


class DashboardDeleteResource(BaseResource):
    @require_permission('edit_dashboard')
    def delete(self, dashboard_id):
        """
        Permanently deletes a dashboard and all its related data.
        
        :param dashboard_id: The ID of the dashboard to delete
        
        Responds with success message.
        """
        try:
            logger.info("Deleting dashboard {}".format(dashboard_id))
            
            # Get dashboard by ID and organization
            dashboard = get_object_or_404(models.Dashboard.get_by_id_and_org, dashboard_id, self.current_org)
            
            # Check permissions
            require_object_modify_permission(dashboard, self.current_user)
            
            logger.info("Dashboard found: {}".format(dashboard.name))
            
            # Delete related data in proper order to handle foreign key constraints
            
            # 1. Delete all widgets associated with this dashboard
            widgets = models.Widget.query.filter_by(dashboard_id=dashboard.id).all()
            for widget in widgets:
                logger.info("Deleting widget {}".format(widget.id))
                models.db.session.delete(widget)
            
            # 2. Delete any API keys associated with this dashboard
            api_keys = models.ApiKey.query.filter_by(
                object_type='dashboards',  # Use table name, not class name
                object_id=dashboard.id
            ).all()
            for api_key in api_keys:
                logger.info("Deleting API key {}".format(api_key.id))
                models.db.session.delete(api_key)
            
            # 3. Delete any favorites associated with this dashboard
            favorites = models.Favorite.query.filter_by(
                object_type='Dashboard',
                object_id=dashboard.id
            ).all()
            for favorite in favorites:
                logger.info("Deleting favorite {}".format(favorite.id))
                models.db.session.delete(favorite)
            
            # 4. Delete the dashboard itself
            logger.info("Deleting dashboard {}".format(dashboard.id))
            models.db.session.delete(dashboard)
            
            # Commit all changes
            models.db.session.commit()
            
            # Log the event
            self.record_event({
                'action': 'delete',
                'object_id': dashboard.id,
                'object_type': 'dashboard',
            })
            
            logger.info("Dashboard {} deleted successfully".format(dashboard_id))
            return {'message': 'Dashboard deleted successfully'}
            
        except Exception as e:
            logger.error("Error deleting dashboard {}: {}".format(dashboard_id, str(e)), exc_info=True)
            models.db.session.rollback()
            abort(500, message="Failed to delete dashboard: {}".format(str(e)))