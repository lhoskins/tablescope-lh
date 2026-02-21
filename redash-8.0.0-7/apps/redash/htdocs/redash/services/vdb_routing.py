"""
VDB Routing Service

Routes queries to the appropriate VDB (user or shared) based on project type.
Implements user-level VDB isolation by determining which VDB to use for query execution.
Includes auto-provisioning of shared VDB records when VDB files exist but database records don't.
"""

import logging
from redash.models.user_vdb import UserVDB
from redash.models.shared_vdb import SharedVDB
from redash.services.shared_vdb_provisioning import SharedVDBProvisioningService, SharedVDBProvisioningError

logger = logging.getLogger(__name__)


# Custom Exceptions
class VDBNotConfiguredError(Exception):
    """Raised when no VDB is configured for the user or organization."""
    pass


class VDBInactiveError(Exception):
    """Raised when the required VDB is not active."""
    pass


class VDBNotFoundError(Exception):
    """Raised when a VDB cannot be found."""
    pass


class VDBRoutingService:
    """
    Service for routing queries to appropriate VDB (user or shared).
    
    This service determines which VDB to use based on project type:
    - Private projects (single owner) -> User VDB
    - Shared projects (multiple members) -> Shared VDB
    
    For datasource schema preview (no query_id), routing also considers
    whether the datasource has been migrated to the shared VDB.
    """
    
    @staticmethod
    def get_vdb_for_query(user_id, project_id, query_id=None, datasource_id=None):
        """
        Determine which VDB to use for a query.
        
        Routes based on query.is_shared flag:
        - If query.is_shared is True -> Shared VDB
        - If query.is_shared is False -> User VDB
        - If query_id not provided, falls back to project.is_shared
        - For datasource schema preview (no query_id), also checks datasource.is_shared
        
        Args:
            user_id (int): ID of the user executing the query
            project_id (int): ID of the project containing the query
            query_id (int, optional): ID of the query being executed
            datasource_id (int, optional): ID of the datasource (for schema preview routing)
        
        Returns:
            tuple: (vdb_config, vdb_type) where:
                - vdb_config is UserVDB or SharedVDB instance
                - vdb_type is 'user' or 'shared'
        
        Raises:
            VDBNotConfiguredError: If no VDB is configured for the user/organization
        
        Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 13.1, 13.2, 13.3, 13.4, 13.5
        """
        from redash.models.project import Project
        from redash.models import Query, DataSource, db
        
        # Get the project
        project = Project.query.get(project_id)
        if not project:
            raise VDBNotFoundError("Project {} not found".format(project_id))
        
        # Determine routing based on query.is_shared if query_id is provided
        is_shared = False
        if query_id and query_id != 'adhoc':
            try:
                query = Query.get_by_id(query_id)
                if query:
                    is_shared = query.is_shared if hasattr(query, 'is_shared') else False
                    logger.info("Query {} is_shared={}".format(query_id, is_shared))
                else:
                    logger.warning("Query {} not found, falling back to project.is_shared".format(query_id))
                    is_shared = project.is_shared if hasattr(project, 'is_shared') else False
            except Exception as e:
                logger.error("Error getting query {}: {}, falling back to project.is_shared".format(query_id, str(e)))
                is_shared = project.is_shared if hasattr(project, 'is_shared') else False
        else:
            # No query_id provided (adhoc query or schema preview)
            # Check if datasource_id is provided for schema preview routing
            if datasource_id:
                try:
                    datasource = DataSource.query.get(datasource_id)
                    if datasource:
                        # For schema preview, route based on datasource.is_shared
                        # This ensures new datasources in shared projects route to user VDB
                        # until they are migrated to the shared VDB
                        # Use the is_shared COLUMN (not method) to check migration status
                        ds_is_shared = getattr(datasource, 'is_shared', False)
                        project_is_shared = project.is_shared if hasattr(project, 'is_shared') else False
                        
                        logger.info("Datasource {} is_shared={}, project {} is_shared={}".format(
                            datasource_id, ds_is_shared, project_id, project_is_shared
                        ))
                        
                        # Only route to shared VDB if BOTH project AND datasource are shared
                        # This prevents routing to shared VDB for unmigrated datasources
                        if project_is_shared and not ds_is_shared:
                            logger.warning(
                                "Datasource {} is in shared project {} but not migrated yet. "
                                "Routing to user VDB instead of shared VDB.".format(
                                    datasource_id, project_id
                                )
                            )
                            is_shared = False
                        else:
                            is_shared = ds_is_shared
                    else:
                        logger.warning("Datasource {} not found, falling back to project.is_shared".format(datasource_id))
                        is_shared = project.is_shared if hasattr(project, 'is_shared') else False
                except Exception as e:
                    logger.error("Error getting datasource {}: {}, falling back to project.is_shared".format(datasource_id, str(e)))
                    is_shared = project.is_shared if hasattr(project, 'is_shared') else False
            else:
                # No datasource_id provided, use project.is_shared
                is_shared = project.is_shared if hasattr(project, 'is_shared') else False
                logger.info("No query_id or datasource_id provided, using project.is_shared={}".format(is_shared))
        
        # Validate is_shared matches member count and auto-correct if needed (for project)
        member_count = len(project.members) if hasattr(project, 'members') else 0
        should_be_shared = member_count > 1
        
        if project.is_shared != should_be_shared:
            logger.warning(
                "Project {} is_shared mismatch detected: is_shared={}, member_count={}, should_be_shared={}. Auto-correcting.".format(
                    project_id, project.is_shared, member_count, should_be_shared
                )
            )
            project.is_shared = should_be_shared
            db.session.add(project)
            try:
                db.session.commit()
                logger.info("Project {} is_shared auto-corrected to {}".format(project_id, should_be_shared))
                
                # Update is_shared variable if we're using project.is_shared for routing
                # This ensures the corrected value is used for routing decisions
                if not query_id or query_id == 'adhoc':
                    is_shared = should_be_shared
                    logger.info("Updated routing is_shared to corrected value: {}".format(is_shared))
                    
            except Exception as e:
                logger.error("Failed to auto-correct is_shared for project {}: {}".format(project_id, str(e)))
                db.session.rollback()
        
        logger.info("Routing decision: is_shared={}, project_id={}, query_id={}".format(
            is_shared, project_id, query_id
        ))
        
        if is_shared:
            # Use shared VDB for shared queries
            logger.info("Routing query to shared VDB for project {}".format(project_id))
            shared_vdb = SharedVDB.get_by_organization(project.org_id)
            
            # Auto-provision shared VDB if needed (Requirements 26.1, 26.2, 26.3, 26.6)
            if not shared_vdb:
                logger.info("Shared VDB record not found for organization {}. Checking for auto-provisioning...".format(project.org_id))
                
                try:
                    provisioning_service = SharedVDBProvisioningService()
                    shared_vdb = provisioning_service.check_and_provision_if_needed(project.org_id)
                    
                    if not shared_vdb:
                        # No VDB file exists - provide clear error message
                        raise VDBNotConfiguredError(
                            "No shared VDB configured for organization {}. "
                            "The shared VDB file does not exist. "
                            "Please provision a shared VDB before accessing shared projects.".format(project.org_id)
                        )
                    
                    logger.info("Auto-provisioned shared VDB {} for organization {}".format(
                        shared_vdb.vdb_id, project.org_id
                    ))
                    
                except SharedVDBProvisioningError as e:
                    # Auto-provisioning failed - provide clear error message
                    raise VDBNotConfiguredError(
                        "No shared VDB configured for organization {}. "
                        "Auto-provisioning failed: {}. "
                        "Please contact your administrator.".format(project.org_id, str(e))
                    )
            
            return (shared_vdb, 'shared')
        else:
            # Use user VDB for private queries
            logger.info("Routing query to user VDB for user {}, project {}".format(user_id, project_id))
            user_vdb = UserVDB.get_by_user(user_id)
            
            # Auto-provision user VDB if it doesn't exist but VDB file exists on disk
            if not user_vdb:
                logger.info("No user VDB record found for user {}. Checking for auto-provisioning...".format(user_id))
                logger.info("Auto-provisioning context: user_id={}, org_id={}, project_id={}".format(
                    user_id, project.org_id, project_id
                ))
                
                try:
                    from redash.services.user_vdb_provisioning import UserVDBProvisioningService, UserVDBProvisioningError
                    provisioning_service = UserVDBProvisioningService()
                    
                    logger.info("Calling check_and_provision_if_needed for user {}...".format(user_id))
                    user_vdb = provisioning_service.check_and_provision_if_needed(user_id, project.org_id)
                    
                    if not user_vdb:
                        logger.warning("Auto-provisioning returned None for user {} - VDB file may not exist".format(user_id))
                        raise VDBNotConfiguredError(
                            "No VDB configured for user {}. "
                            "Please create a data source to provision your VDB.".format(user_id)
                        )
                    
                    logger.info("Auto-provisioned user VDB {} for user {}".format(user_vdb.vdb_id, user_id))
                    
                except UserVDBProvisioningError as e:
                    # Log the ACTUAL provisioning error with full details
                    logger.error("UserVDBProvisioningError for user {}: {}".format(user_id, str(e)))
                    import traceback
                    logger.error("Full traceback:\n{}".format(traceback.format_exc()))
                    raise VDBNotConfiguredError(
                        "No VDB configured for user {}. "
                        "Auto-provisioning failed: {}".format(user_id, str(e))
                    )
                    
                except ImportError as e:
                    # Log import errors separately
                    logger.error("Import error during auto-provisioning for user {}: {}".format(user_id, str(e)))
                    import traceback
                    logger.error("Full traceback:\n{}".format(traceback.format_exc()))
                    raise VDBNotConfiguredError(
                        "No VDB configured for user {}. "
                        "Auto-provisioning service unavailable: {}".format(user_id, str(e))
                    )
                    
                except Exception as e:
                    # Log unexpected errors with full traceback
                    logger.error("Unexpected error during auto-provisioning for user {}: {}".format(user_id, str(e)))
                    import traceback
                    logger.error("Full traceback:\n{}".format(traceback.format_exc()))
                    raise VDBNotConfiguredError(
                        "No VDB configured for user {}. "
                        "Auto-provisioning failed unexpectedly: {}".format(user_id, str(e))
                    )
            
            return (user_vdb, 'user')
    
    @staticmethod
    def get_connection_string_for_query(user_id, project_id, query_id=None, datasource_id=None):
        """
        Get JDBC connection string for a query based on query sharing status.
        
        This method determines the appropriate VDB (user or shared) based on
        query.is_shared flag and returns the connection string with credentials
        for establishing a database connection.
        
        Args:
            user_id (int): ID of the user executing the query
            project_id (int): ID of the project containing the query
            query_id (int, optional): ID of the query being executed
            datasource_id (int, optional): ID of the datasource (for schema preview routing)
        
        Returns:
            dict: Connection information containing:
                - connection_string: PostgreSQL connection string (without credentials)
                - username: VDB username
                - password: Decrypted VDB password
                - vdb_type: 'user' or 'shared'
                - vdb_id: VDB identifier
                - host: VDB host
                - port: VDB port
        
        Raises:
            VDBNotConfiguredError: If no VDB is configured
            VDBInactiveError: If the VDB is not active
        
        Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 13.1, 13.2, 13.3, 13.4, 13.5
        """
        # Get the appropriate VDB based on query.is_shared (and datasource.is_shared for schema preview)
        vdb_config, vdb_type = VDBRoutingService.get_vdb_for_query(user_id, project_id, query_id, datasource_id)
        
        # Check if VDB is active
        if not vdb_config.is_active:
            raise VDBInactiveError(
                "{} VDB {} is not active. "
                "Please contact your administrator to activate the VDB.".format(
                    vdb_type.capitalize(), vdb_config.vdb_id
                )
            )
        
        # Build connection information
        connection_info = {
            'connection_string': vdb_config.get_connection_string(),
            'username': vdb_config.vdb_username,
            'password': vdb_config.get_decrypted_password(),
            'vdb_type': vdb_type,
            'vdb_id': vdb_config.vdb_id,
            'host': vdb_config.vdb_host,
            'port': vdb_config.vdb_port
        }
        
        logger.info(
            "Retrieved connection string for {} VDB {} (user: {}, project: {}, query: {}, datasource: {})".format(
                vdb_type, vdb_config.vdb_id, user_id, project_id, query_id, datasource_id
            )
        )
        
        return connection_info
