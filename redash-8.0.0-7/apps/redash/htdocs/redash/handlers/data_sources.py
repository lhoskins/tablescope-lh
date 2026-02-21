import logging
import requests
from flask import make_response, request, jsonify
from flask_restful import abort
from funcy import project
from six import text_type
from sqlalchemy.exc import IntegrityError

from redash import models
from redash.handlers.base import BaseResource, get_object_or_404, require_fields
from redash.permissions import (require_access, require_admin,
                                require_permission as require_permission_old, view_only)
from redash.handlers.permissions import require_permission, require_resource_access
from redash.query_runner import (get_configuration_schema_for_query_runner_type,
                                 query_runners, NotSupported)
from redash.utils import filter_none
from redash.utils.configuration import ConfigurationContainer, ValidationError
from redash.models.project import Project, ProjectDataSource

logger = logging.getLogger(__name__)

class DataSourceTypeListResource(BaseResource):
    @require_admin
    def get(self):
        available_query_runners = filter(lambda q: not q.deprecated, query_runners.values())
        return [q.to_dict() for q in sorted(available_query_runners, key=lambda q: q.name())]


class DataSourceResource(BaseResource):
    @require_resource_access('datasource', 'view', 'data_source_id')
    def get(self, data_source_id, datasource_obj=None):
        # Use the datasource object passed by the decorator
        data_source = datasource_obj if datasource_obj else models.DataSource.get_by_id_and_org(data_source_id, self.current_org)
        ds = data_source.to_dict(all=True)
        self.record_event({
            'action': 'view',
            'object_id': data_source_id,
            'object_type': 'datasource',
        })
        return ds

    @require_resource_access('datasource', 'edit', 'data_source_id')
    def post(self, data_source_id, datasource_obj=None):
        # Use the datasource object passed by the decorator
        data_source = datasource_obj if datasource_obj else models.DataSource.get_by_id_and_org(data_source_id, self.current_org)
        req = request.get_json(True)

        schema = get_configuration_schema_for_query_runner_type(req['type'])
        if schema is None:
            abort(400)
        try:
            data_source.options.set_schema(schema)
            data_source.options.update(filter_none(req['options']))
        except ValidationError:
            abort(400)

        data_source.type = req['type']
        data_source.name = req['name']
        # Don't change the owner when editing
        models.db.session.add(data_source)

        try:
            models.db.session.commit()
        except IntegrityError as e:
            if req['name'] in e.message:
                abort(400, message="Data source with the name {} already exists.".format(req['name']))

            abort(400)

        # Trigger lifecycle hook for data source update
        try:
            from redash.services.vdb_lifecycle_hooks import on_data_source_updated
            on_data_source_updated(data_source)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error('Failed to execute data source update hook: {}'.format(str(e)))

        self.record_event({
            'action': 'edit',
            'object_id': data_source.id,
            'object_type': 'datasource',
        })

        return data_source.to_dict(all=True)

    @require_resource_access('datasource', 'delete', 'data_source_id')
    def delete(self, data_source_id, datasource_obj=None):
        # Use the datasource object passed by the decorator
        data_source = datasource_obj if datasource_obj else models.DataSource.get_by_id_and_org(data_source_id, self.current_org)
        data_source_name = data_source.name
        
        # Call Wildfly servlet to remove foreign table and view from VDB
        try:
            wildfly_url = "http://64.52.108.62:8095/TeiidExcelImporterTest/deleteDataSource"
            logger.info("Calling Wildfly servlet to delete datasource: %s at %s", data_source_name, wildfly_url)
            response = requests.post(
                wildfly_url,
                data={'dataSourceName': data_source_name},
                timeout=10
            )
            if response.status_code == 200:
                logger.info("Successfully removed foreign table and view for data source: %s", data_source_name)
            else:
                logger.warning("Failed to remove VDB entries for data source %s: %s", data_source_name, response.text)
        except Exception as e:
            logger.error("Error calling Wildfly servlet to delete data source %s: %s", data_source_name, str(e))
            # Continue with deletion even if VDB cleanup fails
        
        # Delete associated queries, but preserve queries that use multiple datasources (joins)
        queries_to_delete = []
        queries_to_preserve = []
        
        # Get all queries that use this datasource
        queries = models.Query.query.filter(
            models.Query.data_source_id == data_source_id,
            models.Query.org_id == self.current_org.id
        ).all()
        
        for query in queries:
            # Check if query uses multiple datasources by looking for JOIN keywords
            # or references to other datasources in the query text
            if self._query_uses_multiple_datasources(query, data_source_name):
                queries_to_preserve.append(query.id)
                logger.info("Preserving query %s (%s) - uses multiple datasources", query.id, query.name)
            else:
                queries_to_delete.append(query.id)
                logger.info("Deleting query %s (%s) - only uses datasource %s", query.id, query.name, data_source_name)
        
        # Delete queries that only use this datasource
        if queries_to_delete:
            try:
                # Delete related records first (visualizations, widgets, alerts)
                for query_id in queries_to_delete:
                    query = models.Query.query.get(query_id)
                    if query:
                        # Delete visualizations and their widgets
                        for vis in query.visualizations:
                            # Delete widgets that use this visualization
                            models.Widget.query.filter(models.Widget.visualization_id == vis.id).delete(synchronize_session=False)
                            # Delete the visualization
                            models.db.session.delete(vis)
                        
                        # Delete alerts
                        models.Alert.query.filter(models.Alert.query_id == query_id).delete(synchronize_session=False)
                        
                        # Delete the query
                        models.db.session.delete(query)
                
                models.db.session.commit()
                logger.info("Deleted %d queries and related records associated with datasource %s", len(queries_to_delete), data_source_name)
            except Exception as e:
                models.db.session.rollback()
                logger.error("Error deleting queries for datasource %s: %s", data_source_name, str(e))
                abort(500, message="Failed to delete associated queries: {}".format(str(e)))
        
        if queries_to_preserve:
            logger.info("Preserved %d queries that use multiple datasources", len(queries_to_preserve))
        
        # Delete the datasource
        try:
            data_source.delete()
        except Exception as e:
            models.db.session.rollback()
            logger.error("Error deleting datasource %s: %s", data_source_name, str(e))
            abort(500, message="Failed to delete data source: {}".format(str(e)))

        self.record_event({
            'action': 'delete',
            'object_id': data_source_id,
            'object_type': 'datasource',
            'queries_deleted': len(queries_to_delete),
            'queries_preserved': len(queries_to_preserve),
        })

        return make_response('', 204)
    
    def _query_uses_multiple_datasources(self, query, current_datasource_name):
        """
        Check if a query uses multiple datasources by analyzing the query text.
        Returns True if the query contains JOIN keywords or references to other datasources.
        """
        if not query.query_text:
            return False
        
        query_text_upper = query.query_text.upper()
        
        # Check for JOIN keywords (indicates multiple tables/datasources)
        join_keywords = ['JOIN', 'INNER JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'OUTER JOIN', 'CROSS JOIN', 'FULL JOIN']
        has_join = any(keyword in query_text_upper for keyword in join_keywords)
        
        if has_join:
            # If there's a JOIN, check if it references other datasources
            # Get all datasources in the org
            all_datasources = models.DataSource.all(self.current_org)
            datasource_names = [ds.name for ds in all_datasources if ds.name != current_datasource_name]
            
            # Check if query references any other datasource
            for ds_name in datasource_names:
                # Check for datasource name in query (case-insensitive)
                if ds_name.upper() in query_text_upper:
                    logger.info("Query %s references other datasource: %s", query.id, ds_name)
                    return True
        
        return False


class DataSourcePreviewResource(BaseResource):
    def get(self, data_source_id):
        """
        Preview data from a datasource.
        
        Permission logic:
        - Datasource owner can preview
        - Organization admin can preview
        - Project members can preview datasources assigned to their projects
        """
        data_source = models.DataSource.get_by_id_and_org(data_source_id, self.current_org)
        
        # Check datasource access using new RBAC system
        has_access = False
        
        # Check if user is owner of the datasource
        if hasattr(data_source, 'owner') and data_source.owner == self.current_user.id:
            has_access = True
            logger.info("User %s is owner of datasource %s", self.current_user.id, data_source_id)
        # Check if user is org admin
        elif self.current_user.has_permission('admin') or self.current_user.has_permission('view_source'):
            has_access = True
            logger.info("User %s is org admin, can preview datasource %s", self.current_user.id, data_source_id)
        else:
            # Check if datasource is assigned to any project the user is a member of
            from redash.models.project import ProjectMember, ProjectDataSource
            user_project_ids = [pm.project_id for pm in ProjectMember.query.filter(
                ProjectMember.user_id == self.current_user.id
            ).all()]
            
            if user_project_ids:
                datasource_projects = ProjectDataSource.query.filter(
                    ProjectDataSource.data_source_id == data_source.id,
                    ProjectDataSource.project_id.in_(user_project_ids)
                ).first()
                
                if datasource_projects:
                    has_access = True
                    logger.info("User %s can preview datasource %s through project membership", 
                               self.current_user.id, data_source_id)
        
        if not has_access:
            logger.warning("User %s does not have permission to preview datasource %s", 
                          self.current_user.id, data_source_id)
            abort(403, message="Insufficient permissions to perform this action")
        
        try:
            # Set project context for VDB routing BEFORE getting query runner
            # Find which project this data source belongs to
            from redash.models.project import ProjectDataSource
            from flask import g
            
            project_ds = ProjectDataSource.query.filter_by(data_source_id=data_source.id).first()
            project_id = None
            if project_ds:
                project = models.Project.query.get(project_ds.project_id)
                if project:
                    g.project = project
                    project_id = project.id
                    logger.info("Set project context for preview: project_id={}, is_shared={}".format(
                        project.id, project.is_shared if hasattr(project, 'is_shared') else False
                    ))
            else:
                logger.info("Data source {} is not assigned to any project".format(data_source.id))
            
            # Get the query runner for this data source (after setting project context)
            query_runner = data_source.query_runner
            
            # Store user, project, and datasource context on runner (needed for VDB routing)
            query_runner._current_user = self.current_user
            query_runner._datasource_id = data_source_id  # For routing unmigrated datasources
            if project_id:
                query_runner._preview_project_id = project_id
                logger.info("Stored project_id {}, datasource_id {}, and user {} on query_runner for preview".format(
                    project_id, data_source_id, self.current_user.id
                ))
            else:
                logger.info("Stored datasource_id {} and user {} on query_runner for preview (no project)".format(
                    data_source_id, self.current_user.id
                ))
            
            # Check if a specific table is requested
            table_name = request.args.get('table')
            
            logger.info("Preview request for datasource %s (type: %s), table: %s", 
                       data_source_id, data_source.type, table_name)
            
            # Build the query
            if data_source.type == 'external':
                # For external (file) data sources
                query = "SELECT * FROM {} LIMIT 100".format(data_source.name)
            elif table_name:
                # For database sources with a specific table
                query = "SELECT * FROM {} LIMIT 100".format(table_name)
            else:
                # For database sources without table name
                logger.warning("Table name required for database source %s", data_source_id)
                return jsonify({"error": "Table name required for database sources"}), 400
            
            logger.info("Executing query: %s", query)
            
            # Run the query
            data, error = query_runner.run_query(query, self.current_user)
            
            if error:
                logger.error("Query execution error: %s", error)
                return jsonify({"error": error}), 400
            
            # Parse the result
            import json
            result = json.loads(data)
            
            logger.info("Query returned %d rows", len(result.get('rows', [])))
            
            return jsonify(result)
            
        except Exception as e:
            logger.error("Error previewing data source %s: %s", data_source_id, str(e))
            return jsonify({"error": str(e)}), 500


class DataSourceListResource(BaseResource):
    def get(self):
        """
        List all datasources accessible to the current user.
        
        Permission logic:
        - Organization admins can see all datasources
        - Project members can see datasources assigned to their projects
        - Users can see datasources they own
        """
        # Import AccessControl for filtering accessible datasources
        from redash.services.access_control import AccessControl
        
        # Get accessible datasources using AccessControl service
        accessible_datasources_query = AccessControl.get_accessible_datasources(
            self.current_user, self.current_org
        )
        data_sources = accessible_datasources_query.all()

        response = {}
        for ds in data_sources:
            if ds.id in response:
                continue

            try:
                d = ds.to_dict()
                d['view_only'] = all(project(ds.groups, self.current_user.group_ids).values())
                
                # Add ownership information
                if hasattr(ds, 'owner') and ds.owner:
                    owner = models.User.query.get(ds.owner)
                    if owner:
                        d['owner'] = {
                            'id': owner.id,
                            'name': owner.name,
                            'email': owner.email
                        }
                    else:
                        d['owner'] = None
                else:
                    d['owner'] = None
                
                # Add project assignments
                project_datasources = ProjectDataSource.query.filter(
                    ProjectDataSource.data_source_id == ds.id
                ).all()
                
                d['projects'] = []
                for pds in project_datasources:
                    proj = Project.query.get(pds.project_id)
                    if proj:
                        d['projects'].append({
                            'id': proj.id,
                            'name': proj.name
                        })
                
                response[ds.id] = d
            except AttributeError:
                logging.exception("Error with DataSource#to_dict (data source id: %d)", ds.id)

        self.record_event({
            'action': 'list',
            'object_id': 'admin/data_sources',
            'object_type': 'datasource',
        })

        return sorted(response.values(), key=lambda d: d['name'].lower())

    def post(self):
        """
        Create a new datasource.
        
        Permission logic:
        - Organization admins can create datasources
        - Any project member (owner, admin, designer, member) can create datasources for their projects
        - Users who are not members of any project cannot create datasources
        """
        req = request.get_json(True)
        require_fields(req, ('options', 'name', 'type'))

        # Check if user has permission to create datasources
        # Allow if: user is org admin OR user is a member of at least one project
        has_permission = False
        
        # Check if user is org admin
        if self.current_user.has_permission('admin') or self.current_user.has_permission('create_datasource'):
            has_permission = True
            logger.info("User %s is org admin, allowing datasource creation", self.current_user.id)
        else:
            # Check if user is a member of any project (any role: owner, admin, designer, member)
            from redash.models.project import ProjectMember
            user_projects = ProjectMember.query.filter(
                ProjectMember.user_id == self.current_user.id
            ).first()
            
            if user_projects:
                has_permission = True
                logger.info("User %s is project member (role: %s), allowing datasource creation", 
                           self.current_user.id, user_projects.role)
        
        if not has_permission:
            abort(403, message="Insufficient permissions to create datasource. You must be an organization admin or a member of at least one project.")

        schema = get_configuration_schema_for_query_runner_type(req['type'])
        if schema is None:
            abort(400)

        config = ConfigurationContainer(filter_none(req['options']), schema)
        if not config.is_valid():
            abort(400)

        try:
            datasource = models.DataSource.create_with_group(
                org=self.current_org,
                name=req['name'],
                type=req['type'],
                options=config,
                owner=self.current_user.id  # Set owner during creation
            )
            
            # For external datasources, populate file paths from options
            # This is critical for unshare migration to work correctly
            if req['type'] == 'external' and config:
                file_path = config.get('file_path', '')
                if file_path:
                    # Check if this datasource is being created for a shared project
                    # by checking if the file path contains '/shared/'
                    if '/shared/' in file_path:
                        # Set shared_file_path (relative path)
                        import re
                        # Extract relative path: "52/shared/uploads/file.xlsx"
                        match = re.search(r'(\d+/shared/uploads/[^/]+)$', file_path)
                        if match:
                            datasource.shared_file_path = match.group(1)
                            logger.info("Set shared_file_path for datasource %s: %s", 
                                       datasource.name, datasource.shared_file_path)
                        
                        # Also set private_file_path for future unshare
                        # Convert "/shared/" to "/{user_id}/"
                        private_path = file_path.replace('/shared/', '/{}/'.format(self.current_user.id))
                        match = re.search(r'(\d+/\d+/uploads/[^/]+)$', private_path)
                        if match:
                            datasource.private_file_path = match.group(1)
                            logger.info("Set private_file_path for datasource %s: %s", 
                                       datasource.name, datasource.private_file_path)
                    else:
                        # Private upload - set private_file_path
                        import re
                        match = re.search(r'(\d+/\d+/uploads/[^/]+)$', file_path)
                        if match:
                            datasource.private_file_path = match.group(1)
                            logger.info("Set private_file_path for datasource %s: %s", 
                                       datasource.name, datasource.private_file_path)
            
            models.db.session.commit()
            
            logger.info("Datasource %s created by user %s", datasource.name, self.current_user.id)
        except IntegrityError as e:
            if req['name'] in e.message:
                abort(400, message="Data source with the name {} already exists.".format(req['name']))

            abort(400)

        self.record_event({
            'action': 'create',
            'object_id': datasource.id,
            'object_type': 'datasource'
        })

        return datasource.to_dict(all=True)

class DataSourceSchemaResource(BaseResource):
    def get(self, data_source_id):
        """
        Fetch schema for the selected data source.
        - Calls `get_schema(refresh)` for standard data sources.
        - Calls `_get_tables()` for external data sources (virtual database).
        
        Permission logic:
        - Datasource owner can view schema
        - Organization admins can view schema
        - Project members can view schema if datasource is assigned to their project
        """
        models = __import__("redash.models", fromlist=["DataSource"])
        DataSource = models.DataSource  

        data_source = get_object_or_404(DataSource.get_by_id_and_org, data_source_id, self.current_org)
        
        # Check datasource access using new RBAC system
        from redash.services.access_control import AccessControl
        
        if not AccessControl.check_datasource_access(self.current_user, data_source, 'view'):
            logger.warning("User %s does not have permission to view schema for datasource %s", 
                          self.current_user.id, data_source_id)
            abort(403, message="You don't have permission to view this datasource schema.")
        refresh = request.args.get('refresh') is not None

        response = {}

        try:
            if data_source.type == "external":
                safe_name = data_source.name.encode("utf-8") if isinstance(data_source.name, unicode) else data_source.name
                logger.info(u"Handling schema for External Data Source (ID: %s, Name: %s)", data_source_id, safe_name)

                # Set project context for VDB routing (needed for shared projects)
                from flask import g
                from redash.models.project import ProjectDataSource
                
                g.user = self.current_user
                
                # Find which project this data source belongs to
                project_ds = ProjectDataSource.query.filter_by(data_source_id=data_source.id).first()
                project_id = None
                if project_ds:
                    project = models.Project.query.get(project_ds.project_id)
                    if project:
                        g.project = project
                        project_id = project.id
                        logger.info("Set project context for schema: project_id={}, is_shared={}".format(
                            project.id, project.is_shared if hasattr(project, 'is_shared') else False
                        ))
                else:
                    logger.info("Data source {} is not assigned to any project".format(data_source.id))

                external_query_runner = __import__("redash.query_runner.external", fromlist=["ExternalDataSource"])
                ExternalDataSource = external_query_runner.ExternalDataSource
                external_runner = ExternalDataSource(configuration=data_source.options)
                
                # Store user, project, and datasource context on runner (needed for VDB routing)
                external_runner._current_user = self.current_user
                external_runner._datasource_id = data_source_id  # For routing unmigrated datasources
                if project_id:
                    external_runner._preview_project_id = project_id
                    logger.info("Stored project_id {}, datasource_id {}, and user {} on query_runner for schema".format(
                        project_id, data_source_id, self.current_user.id
                    ))
                else:
                    logger.info("Stored datasource_id {} and user {} on query_runner for schema (no project)".format(
                        data_source_id, self.current_user.id
                    ))
                
                schema = external_runner._get_tables({})

                # Updated list comprehension to preserve each table as one dictionary.
                response['schema'] = [
                    {k: (v if isinstance(v, list) else unicode(str(v), "utf-8"))
                     for k, v in table.items()}
                    for table in schema
                ]
            else:
                response['schema'] = data_source.get_schema(refresh)

        except NotSupported:
            response['error'] = {
                'code': 1,
                'message': 'Data source type does not support retrieving schema'
            }
        except Exception as e:
            error_message = unicode(str(e), "utf-8") if not isinstance(e, unicode) else e
            logger.error(u"Error retrieving schema for DataSource ID %s: %s", data_source_id, error_message)
            response['error'] = {
                'code': 2,
                'message': 'Error retrieving schema.'
            }

        return jsonify(response)





class DataSourcePauseResource(BaseResource):
    @require_admin
    def post(self, data_source_id):
        data_source = get_object_or_404(models.DataSource.get_by_id_and_org, data_source_id, self.current_org)
        data = request.get_json(force=True, silent=True)
        if data:
            reason = data.get('reason')
        else:
            reason = request.args.get('reason')

        data_source.pause(reason)

        self.record_event({
            'action': 'pause',
            'object_id': data_source.id,
            'object_type': 'datasource'
        })
        return data_source.to_dict()

    @require_admin
    def delete(self, data_source_id):
        data_source = get_object_or_404(models.DataSource.get_by_id_and_org, data_source_id, self.current_org)
        data_source.resume()

        self.record_event({
            'action': 'resume',
            'object_id': data_source.id,
            'object_type': 'datasource'
        })
        return data_source.to_dict()


class DataSourceTestResource(BaseResource):
    @require_admin
    def post(self, data_source_id):
        data_source = get_object_or_404(models.DataSource.get_by_id_and_org, data_source_id, self.current_org)

        # Set project context if data source belongs to a project (for VDB routing)
        from flask import g
        try:
            from redash.models.project import ProjectDataSource
            project_ds = ProjectDataSource.query.filter_by(data_source_id=data_source_id).first()
            if project_ds:
                project = models.Project.query.filter_by(id=project_ds.project_id).first()
                if project:
                    g.project = project
                    logger.info("Set project context for data source test: project_id={}, is_shared={}".format(
                        project.id, project.is_shared
                    ))
        except Exception as e:
            logger.warning("Could not set project context for data source test: {}".format(str(e)))
        
        # Set user context for VDB routing
        g.user = self.current_user

        response = {}
        try:
            data_source.query_runner.test_connection()
        except Exception as e:
            response = {"message": text_type(e), "ok": False}
        else:
            response = {"message": "success", "ok": True}

        self.record_event({
            'action': 'test',
            'object_id': data_source_id,
            'object_type': 'datasource',
            'result': response,
        })
        return response


class PrivateDataSourceListResource(BaseResource):
    def get(self):
        """
        Return data sources owned by the current user with no members assigned.
        A data source is private if:
        - Current user is the owner AND
        - No members are assigned (no DataSourceGroup entries except default group)
        
        Permission logic: Any authenticated user can list their own private datasources
        """
        current_user_id = self.current_user.id
        
        # Get all data sources owned by current user
        owned_data_sources = models.DataSource.query.filter_by(
            owner=current_user_id,
            org_id=self.current_org.id
        ).all()
        
        private_data_sources = []
        for ds in owned_data_sources:
            # Count non-default group memberships
            group_count = models.DataSourceGroup.query.filter(
                models.DataSourceGroup.data_source_id == ds.id
            ).count()
            
            # If only default group or no groups, it's private
            if group_count <= 1:
                try:
                    private_data_sources.append(ds.to_dict())
                except AttributeError:
                    logger.exception("Error with DataSource#to_dict (data source id: %d)", ds.id)
        
        self.record_event({
            'action': 'list',
            'object_id': 'private_data_sources',
            'object_type': 'datasource',
        })
        
        return sorted(private_data_sources, key=lambda d: d['name'].lower())


class SharedDataSourceListResource(BaseResource):
    def get(self):
        """
        Return data sources where:
        - Current user is the owner AND at least one member is assigned, OR
        - Current user is not the owner BUT is a member of the data source
        
        Permission logic: Any authenticated user can list shared datasources they have access to
        """
        current_user_id = self.current_user.id
        
        # Get data sources where user is owner
        owned_data_sources = models.DataSource.query.filter_by(
            owner=current_user_id,
            org_id=self.current_org.id
        ).all()
        
        # Get data sources where user is a member (through groups)
        member_data_source_ids = models.db.session.query(
            models.DataSourceGroup.data_source_id
        ).join(
            models.Group
        ).filter(
            models.Group.id.in_(self.current_user.group_ids)
        ).distinct()
        
        member_data_sources = models.DataSource.query.filter(
            models.DataSource.id.in_(member_data_source_ids),
            models.DataSource.org_id == self.current_org.id,
            models.DataSource.owner != current_user_id  # Not owned by current user
        ).all()
        
        shared_data_sources = []
        
        # Add owned data sources with members
        for ds in owned_data_sources:
            group_count = models.DataSourceGroup.query.filter(
                models.DataSourceGroup.data_source_id == ds.id
            ).count()
            
            # If more than default group, it's shared
            if group_count > 1:
                try:
                    shared_data_sources.append(ds.to_dict())
                except AttributeError:
                    logger.exception("Error with DataSource#to_dict (data source id: %d)", ds.id)
        
        # Add data sources where user is a member but not owner
        for ds in member_data_sources:
            try:
                shared_data_sources.append(ds.to_dict())
            except AttributeError:
                logger.exception("Error with DataSource#to_dict (data source id: %d)", ds.id)
        
        self.record_event({
            'action': 'list',
            'object_id': 'shared_data_sources',
            'object_type': 'datasource',
        })
        
        # Remove duplicates and sort
        unique_ds = {ds['id']: ds for ds in shared_data_sources}
        return sorted(unique_ds.values(), key=lambda d: d['name'].lower())


class EnterpriseDataSourceListResource(BaseResource):
    def get(self):
        """
        Return enterprise data sources.
        Logic for enterprise data sources will be implemented later.
        For now, return an empty list.
        
        Permission logic: Any authenticated user can list enterprise datasources
        """
        self.record_event({
            'action': 'list',
            'object_id': 'enterprise_data_sources',
            'object_type': 'datasource',
        })
        
        return []


class DataSourceQueriesResource(BaseResource):
    @require_permission('list_data_sources')
    def get(self, data_source_id):
        """
        Get all queries that use this data source with statistics.
        Returns query id, name, created_at, updated_at, and last execution time.
        """
        data_source = models.DataSource.get_by_id_and_org(data_source_id, self.current_org)
        
        # Get all queries for this datasource
        queries = models.Query.query.filter(
            models.Query.data_source_id == data_source_id,
            models.Query.org_id == self.current_org.id,
            models.Query.is_archived == False
        ).all()
        
        result = []
        for query in queries:
            # Get the last execution time from latest_query_data
            last_executed_at = None
            if query.latest_query_data:
                last_executed_at = query.latest_query_data.retrieved_at.isoformat() if query.latest_query_data.retrieved_at else None
            
            result.append({
                'id': query.id,
                'name': query.name,
                'created_at': query.created_at.isoformat() if query.created_at else None,
                'updated_at': query.updated_at.isoformat() if query.updated_at else None,
                'last_executed_at': last_executed_at,
                'user': query.user.name if query.user else None,
            })
        
        return result
