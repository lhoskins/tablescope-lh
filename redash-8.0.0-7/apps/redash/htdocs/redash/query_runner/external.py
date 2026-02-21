import os
import logging
import select
from flask_restful import Resource, abort
from flask import request
import psycopg2
from psycopg2.extras import Range
from redash.query_runner import *
from redash.utils import JSONEncoder, json_dumps, json_loads

logger = logging.getLogger(__name__)

types_map = {
    20: TYPE_INTEGER,
    21: TYPE_INTEGER,
    23: TYPE_INTEGER,
    700: TYPE_FLOAT,
    1700: TYPE_FLOAT,
    701: TYPE_FLOAT,
    16: TYPE_BOOLEAN,
    1082: TYPE_DATE,
    1114: TYPE_DATETIME,
    1184: TYPE_DATETIME,
    1014: TYPE_STRING,
    1015: TYPE_STRING,
    1008: TYPE_STRING,
    1009: TYPE_STRING,
    2951: TYPE_STRING,
}

class PostgreSQLJSONEncoder(JSONEncoder):
    def default(self, o):
        if isinstance(o, Range):
            if o._bounds is None:
                return ''
            items = [
                o._bounds[0],
                str(o._lower), ', ',
                str(o._upper), o._bounds[1]
            ]
            return ''.join(items)
        return super(PostgreSQLJSONEncoder, self).default(o)


def _wait(conn, timeout=None):
    while True:
        try:
            state = conn.poll()
            if state == psycopg2.extensions.POLL_OK:
                break
            elif state == psycopg2.extensions.POLL_WRITE:
                select.select([], [conn.fileno()], [], timeout)
            elif state == psycopg2.extensions.POLL_READ:
                select.select([conn.fileno()], [], [], timeout)
            else:
                raise psycopg2.OperationalError("poll() returned %s" % state)
        except select.error:
            raise psycopg2.OperationalError("select.error received")


class ExternalDataSource(BaseSQLQueryRunner):
    noop_query = "SELECT 1"

    @classmethod
    def configuration_schema(cls):
        return {
            "type": "object",
            "properties": {},
        }

    @classmethod
    def type(cls):
        return "external"

    def _get_definitions(self, schema, query):
        results, error = self.run_query(query, None)
        if error is not None:
            raise Exception("Failed getting schema.")
        results = json_loads(results)
        for row in results['rows']:
            table_name = u"{}.{}".format(row['table_schema'], row['table_name'])
            if table_name not in schema:
                schema[table_name] = {'name': table_name, 'columns': []}
            schema[table_name]['columns'].append(row['column_name'])

    def _get_tables(self, schema):
        """
        Retrieves tables and columns dynamically using the data source name.
        """
        # Dynamically get the data source name
        from redash.models import DataSource

        data_source_id = request.view_args.get("data_source_id")
        if not data_source_id:
            raise Exception("Missing required parameter: 'data_source_id'")

        data_source = DataSource.query.filter(DataSource.id == data_source_id).first()
        if not data_source:
            raise Exception("Data source with ID {} not found.".format(data_source_id))

        data_source_name = data_source.name.replace("'", "''")  # Escape single quotes
        logger.info(u"Using data source name: {}".format(data_source_name))

        # Normalize the datasource name to match Teiid's view naming convention
        # Teiid creates views in uppercase with underscores
        normalized_name = data_source_name.replace(" ", "_").upper()
        logger.info(u"Normalized view name: {}".format(normalized_name))

        # Query for schema information using case-insensitive matching
        query = """
        SELECT table_schema,
               table_name,
               column_name
        FROM information_schema.columns
        WHERE table_schema = 'MyCompany'
          AND UPPER(table_name) = UPPER('{}')
        ORDER BY table_schema, table_name, ordinal_position;
        """.format(normalized_name)

        self._get_definitions(schema, query)

        return schema.values()

    def _get_connection(self):
        """
        Establishes a connection to the virtual database.
        
        When USER_VDB_ISOLATION_ENABLED is True:
        - Routes to user VDB for private projects
        - Routes to shared VDB for shared projects
        
        When USER_VDB_ISOLATION_ENABLED is False:
        - Falls back to organization VDB (legacy behavior)
        
        Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 12.1, 12.2, 12.3
        """
        logger.info("_get_connection() called")
        
        # Check if user-level VDB isolation is enabled
        from redash import settings
        user_vdb_isolation_enabled = getattr(settings, 'USER_VDB_ISOLATION_ENABLED', False)
        
        if not user_vdb_isolation_enabled:
            logger.info("User VDB isolation disabled, using organization VDB")
            return self._get_organization_vdb_connection()
        
        # Get user and project from current context
        user_id = self._get_current_user_id()
        project_id = self._get_current_project_id()
        
        logger.info("User ID: {}, Project ID: {}".format(user_id, project_id))
        
        # If we have user_id but no project_id, try to get user VDB directly
        if user_id and not project_id:
            logger.info("No project context, attempting to use user VDB for user: {}".format(user_id))
            try:
                from redash.services.vdb_routing import VDBRoutingService
                from redash.models.user_vdb import UserVDB
                from redash.services.user_vdb_provisioning import UserVDBProvisioningService, UserVDBProvisioningError
                
                # Check if user has a user VDB
                user_vdb = UserVDB.get_by_user(user_id)
                
                # If no user VDB record exists, try to auto-provision
                if not user_vdb:
                    logger.info("No user VDB record found for user: {}. Checking for auto-provisioning...".format(user_id))
                    
                    # Get org_id from user
                    org_id = self._get_current_org_id()
                    if org_id:
                        try:
                            provisioning_service = UserVDBProvisioningService()
                            user_vdb = provisioning_service.check_and_provision_if_needed(user_id, org_id)
                            
                            if user_vdb:
                                logger.info("Auto-provisioned user VDB {} for user {}".format(
                                    user_vdb.vdb_id, user_id
                                ))
                            else:
                                logger.warning("Could not auto-provision user VDB for user {}".format(user_id))
                        except UserVDBProvisioningError as e:
                            logger.error("Auto-provisioning failed for user {}: {}".format(user_id, str(e)))
                    else:
                        logger.warning("Cannot auto-provision user VDB: no org_id available")
                
                if user_vdb and user_vdb.is_active:
                    logger.info("Found active user VDB: {} for user: {}".format(user_vdb.vdb_id, user_id))
                    
                    # Get decrypted password
                    password = user_vdb.get_decrypted_password()
                    
                    logger.info("User VDB Connection Parameters:")
                    logger.info("  VDB ID: {}".format(user_vdb.vdb_id))
                    logger.info("  Host: {}".format(user_vdb.vdb_host))
                    logger.info("  Port: {}".format(user_vdb.vdb_port))
                    logger.info("  User: {}".format(user_vdb.vdb_username))
                    
                    connection = psycopg2.connect(
                        host=user_vdb.vdb_host,
                        port=user_vdb.vdb_port,
                        database=user_vdb.vdb_id,
                        user=user_vdb.vdb_username,
                        password=password,
                        async_=True
                    )
                    logger.info("Successfully connected to user VDB")
                    return connection
                else:
                    # IMPORTANT: Do NOT fall back to organization VDB
                    # Organization VDB should be empty and reserved for future use
                    # Instead, raise an error so the user knows to provision their VDB
                    logger.error("No active user VDB found for user: {}. Organization VDB fallback is disabled.".format(user_id))
                    raise Exception(
                        "No VDB configured for user {}. "
                        "Please create a data source to provision your VDB. "
                        "Organization VDB fallback is disabled.".format(user_id)
                    )
            except Exception as e:
                # Re-raise the exception instead of falling back to org VDB
                logger.error("Error getting user VDB: {}".format(str(e)))
                raise
        
        if not user_id:
            logger.warning("Missing user context")
            raise Exception("Missing user context. Cannot determine which VDB to connect to.")
        
        try:
            # Get VDB connection parameters based on query.is_shared flag
            from redash.services.vdb_routing import VDBRoutingService, VDBNotConfiguredError, VDBInactiveError
            
            # Get query_id if available (set by QueryExecutor)
            query_id = getattr(self, '_query_id', None)
            
            # If not set, try to get from request context
            if not query_id:
                from flask import request
                if request and hasattr(request, 'view_args'):
                    query_id = request.view_args.get('query_id')
                    if query_id:
                        logger.info("Found query_id from request.view_args: {}".format(query_id))
                
                if not query_id and request and hasattr(request, 'args'):
                    query_id = request.args.get('query_id')
                    if query_id:
                        logger.info("Found query_id from request.args: {}".format(query_id))
            
            # Get datasource_id for schema preview routing
            # This ensures unmigrated datasources in shared projects route to user VDB
            datasource_id = getattr(self, '_datasource_id', None)
            if not datasource_id:
                from flask import request
                if request and hasattr(request, 'view_args'):
                    datasource_id = request.view_args.get('data_source_id')
                    if datasource_id:
                        logger.info("Found datasource_id from request.view_args: {}".format(datasource_id))
            
            logger.info("Getting VDB connection params for user: {}, project: {}, query: {}, datasource: {}".format(
                user_id, project_id, query_id, datasource_id
            ))
            
            # Pass query_id and datasource_id to routing service
            # datasource_id is used for schema preview to check if datasource is migrated
            connection_info = VDBRoutingService.get_connection_string_for_query(
                user_id, project_id, query_id, datasource_id
            )
            
            logger.info("VDB Connection Parameters:")
            logger.info("  VDB Type: {}".format(connection_info['vdb_type']))
            logger.info("  VDB ID: {}".format(connection_info['vdb_id']))
            logger.info("  Host: {}".format(connection_info['host']))
            logger.info("  Port: {}".format(connection_info['port']))
            logger.info("  User: {}".format(connection_info['username']))
            
            # Establish connection with VDB-specific credentials
            logger.info("Attempting psycopg2.connect with async_=True...")
            connection = psycopg2.connect(
                host=connection_info['host'],
                port=connection_info['port'],
                database=connection_info['vdb_id'],
                user=connection_info['username'],
                password=connection_info['password'],
                async_=True
            )
            
            logger.info("psycopg2.connect() returned successfully")
            logger.info("Connection object: {}".format(connection))
            return connection
            
        except (VDBNotConfiguredError, VDBInactiveError) as e:
            logger.error("VDB routing error: {}".format(str(e)))
            raise Exception("VDB routing failed: {}".format(str(e)))
            
        except psycopg2.OperationalError as e:
            logger.error("PostgreSQL connection error: {}".format(str(e)))
            if 'connection_info' in locals():
                logger.error("Connection details: host={}, port={}, vdb={}, type={}".format(
                    connection_info.get('host'), 
                    connection_info.get('port'), 
                    connection_info.get('vdb_id'),
                    connection_info.get('vdb_type')
                ))
            raise Exception("VDB connection failed (OperationalError): {}".format(str(e)))
            
        except Exception as e:
            logger.error("Failed to connect to VDB: {}".format(str(e)), exc_info=True)
            if 'connection_info' in locals():
                logger.error("Connection details: host={}, port={}, vdb={}, type={}".format(
                    connection_info.get('host'), 
                    connection_info.get('port'), 
                    connection_info.get('vdb_id'),
                    connection_info.get('vdb_type')
                ))
            raise Exception("VDB connection failed: {}".format(str(e)))
    
    def _get_current_user_id(self):
        """
        Extract user ID from request context.
        
        Returns:
            User ID or None if not found
        
        Requirements: 11.1, 11.2
        """
        try:
            # Method 1: Get from user parameter passed to run_query
            if hasattr(self, '_current_user') and self._current_user:
                if hasattr(self._current_user, 'id'):
                    logger.info("Found user_id from user parameter: {}".format(self._current_user.id))
                    return self._current_user.id
            
            # Method 2: Try Flask g.user
            from flask import g
            if hasattr(g, 'user') and g.user and hasattr(g.user, 'id'):
                logger.info("Found user_id from g.user: {}".format(g.user.id))
                return g.user.id
            
            logger.warning("No user context found")
            return None
            
        except Exception as e:
            logger.error("Error getting user context: {}".format(str(e)))
            return None
    
    def _get_current_project_id(self):
        """
        Extract project ID from request context.
        
        Returns:
            Project ID or None if not found
        
        Requirements: 11.1, 11.2
        """
        try:
            # Method 1: Try preview project_id (set by preview handler)
            if hasattr(self, '_preview_project_id') and self._preview_project_id:
                logger.info("Found project_id from preview context: {}".format(self._preview_project_id))
                return int(self._preview_project_id)
            
            # Method 2: Try Flask g.project
            from flask import g
            if hasattr(g, 'project') and g.project and hasattr(g.project, 'id'):
                logger.info("Found project_id from g.project: {}".format(g.project.id))
                return g.project.id
            
            # Method 3: Try Flask request args
            from flask import request
            if request and hasattr(request, 'args'):
                project_id = request.args.get('project_id')
                if project_id:
                    logger.info("Found project_id from request args: {}".format(project_id))
                    return int(project_id)
            
            # Method 4: Try Flask request view_args
            if request and hasattr(request, 'view_args'):
                project_id = request.view_args.get('project_id')
                if project_id:
                    logger.info("Found project_id from request view_args: {}".format(project_id))
                    return int(project_id)
            
            # Method 5: Query database if we have query_id (for background workers)
            # This is critical for shared projects where Flask g context is not available
            if hasattr(self, '_query_id') and self._query_id and self._query_id != 'adhoc':
                try:
                    from redash.models import Query
                    query = Query.get_by_id(self._query_id)
                    if query and query.project_id and len(query.project_id) > 0:
                        project_id = query.project_id[0]
                        logger.info("Found project_id from database query: {}".format(project_id))
                        return int(project_id)
                except Exception as e:
                    logger.error("Error querying database for project_id: {}".format(str(e)))
            
            logger.warning("No project context found")
            return None
            
        except Exception as e:
            logger.error("Error getting project context: {}".format(str(e)))
            return None
    
    def _get_current_org_id(self):
        """
        Extract organization ID from request context.
        
        Returns:
            Organization ID or None if not found
        """
        try:
            # Method 1: Get from user parameter passed to run_query
            if hasattr(self, '_current_user') and self._current_user:
                if hasattr(self._current_user, 'org_id'):
                    logger.info("Found org_id from user parameter: {}".format(self._current_user.org_id))
                    return self._current_user.org_id
            
            # Method 2: Try Flask g.org
            from flask import g
            if hasattr(g, 'org') and g.org:
                logger.info("Found org_id from g.org: {}".format(g.org.id))
                return g.org.id
            
            # Method 3: Try Flask g.user
            if hasattr(g, 'user') and g.user and hasattr(g.user, 'org_id'):
                logger.info("Found org_id from g.user: {}".format(g.user.org_id))
                return g.user.org_id
            
            logger.warning("No organization context found")
            return None
            
        except Exception as e:
            logger.error("Error getting organization context: {}".format(str(e)))
            return None
    
    def _get_organization_vdb_connection(self):
        """
        Legacy organization VDB connection (backward compatibility).
        
        Falls back to organization-level VDB when user-level VDB isolation is disabled
        or when context is missing.
        
        Requirements: 12.1, 12.2, 12.3, 12.4, 12.5
        """
        logger.info("_get_organization_vdb_connection() called")
        
        # Get organization from current context
        org_id = self._get_current_org_id()
        logger.info("Organization ID: {}".format(org_id))
        
        if not org_id:
            logger.error("No organization context found")
            raise Exception("No organization context found. Cannot determine which VDB to connect to.")
        
        try:
            # Get VDB connection parameters for organization
            from redash.services.vdb_context import VDBContextService, VDBNotConfiguredError, VDBInactiveError
            
            logger.info("Getting VDB connection params for org: {}".format(org_id))
            params = VDBContextService.get_vdb_connection_params(org_id)
            
            logger.info("VDB Connection Parameters:")
            logger.info("  VDB ID: {}".format(params['vdb_id']))
            logger.info("  Host: {}".format(params['host']))
            logger.info("  Port: {}".format(params['port']))
            logger.info("  User: {}".format(params['user']))
            logger.info("  DSN: {}".format(params['dsn']))
            
            # Establish connection with VDB-specific credentials
            logger.info("Attempting psycopg2.connect with async_=True...")
            connection = psycopg2.connect(
                dsn=params['dsn'],
                user=params['user'],
                password=params['password'],
                async_=True
            )
            
            logger.info("psycopg2.connect() returned successfully")
            logger.info("Connection object: {}".format(connection))
            return connection
            
        except (VDBNotConfiguredError, VDBInactiveError) as e:
            logger.error("VDB not configured for org {}: {}".format(org_id, str(e)))
            raise Exception("No VDB configured for organization {}. Please configure a VDB in the admin panel.".format(org_id))
            
        except psycopg2.OperationalError as e:
            logger.error("PostgreSQL connection error for org {}: {}".format(org_id, str(e)))
            logger.error("Connection details: host={}, port={}, vdb={}".format(
                params.get('host'), params.get('port'), params.get('vdb_id')
            ))
            raise Exception("VDB connection failed (OperationalError): {}".format(str(e)))
            
        except Exception as e:
            logger.error("Failed to connect to VDB for org {}: {}".format(org_id, str(e)), exc_info=True)
            if 'params' in locals():
                logger.error("Connection details: host={}, port={}, vdb={}".format(
                    params.get('host'), params.get('port'), params.get('vdb_id')
                ))
            raise Exception("VDB connection failed: {}".format(str(e)))
    


    def run_query(self, query, user):
        import time
        start_time = time.time()
        
        # Store user for _get_connection to access
        self._current_user = user
        
        logger.info("="*80)
        logger.info("QUERY EXECUTION START")
        logger.info("User: {}".format(user.email if user else 'None'))
        logger.info("Org ID: {}".format(user.org_id if user and hasattr(user, 'org_id') else 'None'))
        logger.info("Query: {}".format(query[:200] if len(query) > 200 else query))
        logger.info("="*80)
        
        try:
            logger.info("[1/6] Getting database connection...")
            connection_start = time.time()
            connection = self._get_connection()
            connection_time = time.time() - connection_start
            logger.info("[1/6] Connection obtained in {:.2f}s".format(connection_time))
            
            logger.info("[2/6] Waiting for connection to be ready...")
            wait_start = time.time()
            _wait(connection, timeout=60)
            wait_time = time.time() - wait_start
            logger.info("[2/6] Connection ready in {:.2f}s".format(wait_time))
            
            logger.info("[3/6] Creating cursor...")
            cursor = connection.cursor()
            logger.info("[3/6] Cursor created")

            try:
                logger.info("[4/6] Executing query...")
                execute_start = time.time()
                cursor.execute(query)
                execute_time = time.time() - execute_start
                logger.info("[4/6] Query executed in {:.2f}s".format(execute_time))
                
                logger.info("[5/6] Waiting for query results...")
                result_wait_start = time.time()
                _wait(connection, timeout=60)
                result_wait_time = time.time() - result_wait_start
                logger.info("[5/6] Results ready in {:.2f}s".format(result_wait_time))

                if cursor.description is not None:
                    logger.info("[6/6] Processing results...")
                    process_start = time.time()
                    
                    columns = self.fetch_columns([(i[0], types_map.get(i[1], None))
                                                  for i in cursor.description])
                    logger.info("[6/6] Columns fetched: {}".format(len(columns)))
                    
                    rows = [
                        dict(zip((c['name'] for c in columns), row))
                        for row in cursor
                    ]
                    logger.info("[6/6] Rows fetched: {}".format(len(rows)))
                    
                    data = {'columns': columns, 'rows': rows}
                    error = None
                    json_data = json_dumps(data, ignore_nan=True, cls=PostgreSQLJSONEncoder)
                    
                    process_time = time.time() - process_start
                    logger.info("[6/6] Results processed in {:.2f}s".format(process_time))
                else:
                    logger.warning("[6/6] Query completed but returned no data")
                    error = 'Query completed but it returned no data.'
                    json_data = None
                    
            except (select.error, OSError) as e:
                logger.error("Query interrupted: {}".format(str(e)))
                error = "Query interrupted. Please retry."
                json_data = None
            except psycopg2.DatabaseError as e:
                logger.error("Database error: {}".format(str(e)))
                error = str(e)
                json_data = None
            except (KeyboardInterrupt, InterruptException) as e:
                logger.error("Query cancelled: {}".format(str(e)))
                connection.cancel()
                error = "Query cancelled by user."
                json_data = None
            finally:
                logger.info("Closing connection...")
                connection.close()
                logger.info("Connection closed")

        except Exception as e:
            logger.error("FATAL ERROR in run_query: {}".format(str(e)), exc_info=True)
            error = "Query execution failed: {}".format(str(e))
            json_data = None

        total_time = time.time() - start_time
        logger.info("="*80)
        logger.info("QUERY EXECUTION COMPLETE")
        logger.info("Total time: {:.2f}s".format(total_time))
        logger.info("Success: {}".format(error is None))
        if error:
            logger.error("Error: {}".format(error))
        logger.info("="*80)

        return json_data, error


class CreateDatasourceResource(Resource):
    def post(self):
        """
        API to create a new data source in Redash.
        """
        from redash.models import DataSource

        payload = request.get_json(force=True)
        name = payload.get("name")
        org_id = payload.get("org_id", 1)

        if not name:
            abort(400, message="Missing required parameter: name")

        safe_name = name.replace(".", "_")

        existing_ds = DataSource.query.filter(DataSource.name == safe_name).first()
        if existing_ds:
            abort(400, message="Data source '{}' already exists.".format(safe_name))

        try:
            data_source = DataSource.create(
                org_id=org_id,
                name=safe_name,
                type="external",
                options={},
            )
        except Exception as e:
            abort(500, message="Failed to create data source: {}".format(str(e)))

        return {
            "status": "success",
            "data_source": {
                "id": data_source.id,
                "name": data_source.name,
                "type": data_source.type,
            },
        }


register(ExternalDataSource)
