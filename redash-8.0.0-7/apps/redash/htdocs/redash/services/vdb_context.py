"""
VDB Context Service

Service for managing VDB context in user sessions and query execution.
Handles VDB configuration retrieval and connection string generation.
"""

import logging

from redash.models.organization_vdb import OrganizationVDB

logger = logging.getLogger(__name__)


class VDBNotConfiguredError(Exception):
    """Exception raised when VDB is not configured for an organization."""
    pass


class VDBInactiveError(Exception):
    """Exception raised when VDB exists but is not active."""
    pass


class VDBContextService:
    """
    Service for managing VDB context in user sessions and query execution.
    
    This service provides methods to:
    - Retrieve VDB configuration for organizations
    - Generate connection strings
    - Validate VDB status
    """
    
    @staticmethod
    def get_vdb_for_organization(org_id):
        """
        Retrieve VDB configuration for an organization.
        
        Args:
            org_id: Organization ID
            
        Returns:
            OrganizationVDB instance or None
            
        Example:
            >>> vdb_config = VDBContextService.get_vdb_for_organization(5)
            >>> print(vdb_config.vdb_id)
            'vdb_development'
        """
        logger.info('VDBContextService.get_vdb_for_organization called')
        logger.info('  org_id: {}, type: {}'.format(org_id, type(org_id)))
        
        logger.info('  Calling OrganizationVDB.get_by_organization({})...'.format(org_id))
        vdb_config = OrganizationVDB.get_by_organization(org_id)
        logger.info('  Result: {}'.format(vdb_config))
        
        if vdb_config:
            logger.info('  Found VDB config: {} for org: {}'.format(
                vdb_config.vdb_id, org_id
            ))
        else:
            logger.warning('  No VDB config found for org: {}'.format(org_id))
            logger.warning('  Checking if any VDBs exist in database...')
            all_vdbs = OrganizationVDB.query.all()
            logger.warning('  Total VDBs in database: {}'.format(len(all_vdbs)))
            for v in all_vdbs:
                logger.warning('    - VDB id={}, org_id={}, vdb_id={}'.format(v.id, v.organization_id, v.vdb_id))
        
        return vdb_config
    
    @staticmethod
    def get_connection_string_for_org(org_id):
        """
        Get JDBC connection string for organization's VDB.
        
        This method retrieves the VDB configuration and builds a connection
        string WITHOUT credentials (credentials are passed separately).
        
        Args:
            org_id: Organization ID
            
        Returns:
            JDBC connection string (without credentials)
            
        Raises:
            VDBNotConfiguredError: If no VDB is configured for the organization
            VDBInactiveError: If VDB exists but is not active
            
        Example:
            >>> conn_str = VDBContextService.get_connection_string_for_org(5)
            >>> print(conn_str)
            'jdbc:teiid:vdb_development@mm://localhost:31020'
        """
        vdb_config = VDBContextService.get_vdb_for_organization(org_id)
        
        if not vdb_config:
            error_msg = 'No VDB configured for organization {}'.format(org_id)
            logger.error(error_msg)
            raise VDBNotConfiguredError(error_msg)
    
    @staticmethod
    def get_vdb_connection_params(org_id):
        """
        Get connection parameters for organization's VDB.
        
        Returns a dictionary with DSN, user, and password for psycopg2 connection.
        Uses PostgreSQL connection format (NOT JDBC format).
        
        Args:
            org_id: Organization ID
            
        Returns:
            Dictionary with keys: dsn, user, password, vdb_id, host, port
            
        Raises:
            VDBNotConfiguredError: If no VDB is configured for the organization
            VDBInactiveError: If VDB exists but is not active
            
        Example:
            >>> params = VDBContextService.get_vdb_connection_params(1)
            >>> print(params['dsn'])
            'postgresql://64.52.108.62:10000/vdb_production'
            >>> conn = psycopg2.connect(
            ...     dsn=params['dsn'],
            ...     user=params['user'],
            ...     password=params['password']
            ... )
        """
        vdb_config = VDBContextService.get_vdb_for_organization(org_id)
        
        if not vdb_config:
            error_msg = 'No VDB configured for organization {}'.format(org_id)
            logger.error(error_msg)
            raise VDBNotConfiguredError(error_msg)
        
        if not vdb_config.is_active:
            error_msg = 'VDB {} is not active for organization {}'.format(
                vdb_config.vdb_id, org_id
            )
            logger.error(error_msg)
            raise VDBInactiveError(error_msg)
        
        # Build PostgreSQL-style DSN for Teiid (WITHOUT credentials)
        # Format: postgresql://host:port/vdb_name?sslmode=disable
        # Credentials are passed separately to psycopg2.connect()
        # sslmode=disable is required because Teiid doesn't use SSL by default
        dsn = 'postgresql://{}:{}/{}?sslmode=disable'.format(
            vdb_config.vdb_host,
            vdb_config.vdb_port,
            vdb_config.vdb_id
        )
        
        # Get decrypted password
        password = vdb_config.get_decrypted_password() if hasattr(vdb_config, 'get_decrypted_password') else vdb_config.encrypted_password
        
        params = {
            'dsn': dsn,
            'user': vdb_config.vdb_username,
            'password': password,
            'vdb_id': vdb_config.vdb_id,
            'host': vdb_config.vdb_host,
            'port': vdb_config.vdb_port
        }
        
        logger.info('Generated connection params for org {}, vdb_id: {}, host: {}, port: {}'.format(
            org_id, vdb_config.vdb_id, vdb_config.vdb_host, vdb_config.vdb_port
        ))
        
        return params
    
    @staticmethod
    def validate_vdb_for_org(org_id):
        """
        Validate that a VDB is properly configured and active for an organization.
        
        Args:
            org_id: Organization ID
            
        Returns:
            Tuple of (is_valid, error_message)
            - is_valid: True if VDB is configured and active, False otherwise
            - error_message: Error message if not valid, None if valid
            
        Example:
            >>> is_valid, error = VDBContextService.validate_vdb_for_org(5)
            >>> if not is_valid:
            ...     print(f"VDB validation failed: {error}")
        """
        try:
            vdb_config = VDBContextService.get_vdb_for_organization(org_id)
            
            if not vdb_config:
                return False, 'No VDB configured for organization {}'.format(org_id)
            
            if not vdb_config.is_active:
                return False, 'VDB {} is not active'.format(vdb_config.vdb_id)
            
            # Check if credentials are set
            if not vdb_config.vdb_username:
                return False, 'VDB username not configured'
            
            if not vdb_config.encrypted_password:
                return False, 'VDB password not configured'
            
            return True, None
            
        except Exception as e:
            error_msg = 'VDB validation error: {}'.format(str(e))
            logger.error(error_msg)
            return False, error_msg
    
    @staticmethod
    def inject_vdb_context(query_runner, org_id):
        """
        Inject VDB connection parameters into query runner.
        
        Modifies the query runner's connection configuration to use
        the organization-specific VDB.
        
        Args:
            query_runner: Query runner instance to modify
            org_id: Organization ID
            
        Returns:
            Modified query runner instance
            
        Raises:
            VDBNotConfiguredError: If no VDB is configured for the organization
            VDBInactiveError: If VDB exists but is not active
            
        Note:
            This method modifies the query runner in-place.
        """
        logger.debug('Injecting VDB context for org: {}'.format(org_id))
        
        params = VDBContextService.get_vdb_connection_params(org_id)
        
        # Store VDB params in query runner for later use
        query_runner._vdb_params = params
        
        logger.info('VDB context injected for org {}, vdb_id: {}'.format(
            org_id, params['vdb_id']
        ))
        
        return query_runner
