"""
VDB Management Service

Service for managing VDB (Virtual Database) lifecycle operations including:
- VDB provisioning from templates
- VDB deletion and cleanup
- Credential rotation
- Health monitoring
"""

import logging
import requests
from datetime import datetime

from redash import settings
from redash.models import db
from redash.models.organization_vdb import OrganizationVDB
from redash.models.user_vdb import UserVDB
from redash.models.shared_vdb import SharedVDB
from redash.utils.vdb_utils import generate_vdb_id, generate_vdb_credentials
from redash.utils.configuration import ConfigurationContainer

logger = logging.getLogger(__name__)


class VDBProvisioningError(Exception):
    """Exception raised when VDB provisioning fails."""
    pass


class VDBManagementService:
    """
    Service for managing VDB lifecycle operations.
    
    This service handles:
    - Creating VDBs from templates
    - Deploying VDBs to Teiid server
    - Managing VDB credentials
    - Health monitoring
    """
    
    def __init__(self, teiid_servlet_url=None, template_vdb_name=None):
        """
        Initialize VDB Management Service.
        
        Args:
            teiid_servlet_url: URL of Teiid servlet (defaults to database config)
            template_vdb_name: Name of template VDB (defaults to database config)
        """
        # Load configuration from database if not provided
        if not teiid_servlet_url or not template_vdb_name:
            config = self._load_teiid_config()
            if not config:
                raise VDBProvisioningError('Teiid configuration not found. Please configure first.')
            
            self.teiid_servlet_url = teiid_servlet_url or config.get('servlet_url')
            self.template_vdb_name = template_vdb_name or config.get('template_vdb_name')
            self.servlet_api_key = config.get('servlet_api_key')
            self.teiid_host = config.get('teiid_host')
            self.teiid_port = config.get('teiid_port')
            self.customer_base_path = config.get('customer_base_path')
        else:
            self.teiid_servlet_url = teiid_servlet_url
            self.template_vdb_name = template_vdb_name
            self.servlet_api_key = getattr(settings, 'TEIID_SERVLET_API_KEY', None)
            self.teiid_host = getattr(settings, 'TEIID_HOST', 'localhost')
            self.teiid_port = getattr(settings, 'TEIID_PORT', 31020)
            self.customer_base_path = getattr(settings, 'CUSTOMER_BASE_PATH', '/opt/wildfly/teiidfiles/customers')
    
    def _load_teiid_config(self):
        """
        Load Teiid configuration from database.
        
        Returns:
            Dict with configuration or None if not found
        """
        try:
            result = db.session.execute(
                """
                SELECT 
                    servlet_url, servlet_api_key, teiid_host, teiid_port,
                    customer_base_path, template_vdb_name, vdb_enabled
                FROM teiid_config 
                WHERE id = 1 AND vdb_enabled = TRUE
                """
            ).fetchone()
            
            if not result:
                return None
            
            return {
                'servlet_url': result[0],
                'servlet_api_key': result[1],
                'teiid_host': result[2],
                'teiid_port': result[3],
                'customer_base_path': result[4],
                'template_vdb_name': result[5]
            }
        except Exception as e:
            logger.error('Failed to load Teiid config from database: {}'.format(str(e)))
            return None
    
    def provision_vdb_for_organization(self, organization, org_id=None):
        """
        Provision a new VDB for an organization.
        
        This method is called during organization provisioning workflow to set up
        a dedicated VDB for the organization with unique credentials and folder structure.
        
        Steps:
        1. Generate VDB identifier from org slug
        2. Generate unique credentials
        3. Get customer folder paths
        4. Call Teiid servlet to create VDB from template
        5. Store VDB config in database
        6. Verify VDB deployment
        
        Args:
            organization: Organization instance
            org_id: Optional organization ID (defaults to organization.id)
            
        Returns:
            OrganizationVDB instance
            
        Raises:
            VDBProvisioningError: If provisioning fails at any step
        """
        # Use provided org_id or get from organization instance
        org_id = org_id or organization.id
        
        logger.info('[PROVISIONING] Starting VDB provisioning for organization: {} (id={})'.format(
            organization.slug, org_id
        ))
        
        try:
            # 1. Generate VDB ID
            vdb_id = generate_vdb_id()
            logger.info('[PROVISIONING] Generated VDB ID: {}'.format(vdb_id))
            
            # 2. Generate credentials
            username, password = generate_vdb_credentials()
            logger.info('[PROVISIONING] Generated VDB credentials for user: {}'.format(username))
            
            # 3. Get customer folder paths
            from redash.services.customer_folders import CustomerFolderService
            folder_service = CustomerFolderService()
            vdb_folder = folder_service.get_vdb_folder(org_id)
            uploads_folder = folder_service.get_uploads_folder(org_id)
            
            logger.info('[PROVISIONING] VDB folder: {}, Uploads folder: {}'.format(
                vdb_folder, uploads_folder
            ))
            
            # 4. Create VDB via servlet
            logger.info('[PROVISIONING] Calling servlet to create VDB for org_id: {}'.format(org_id))
            result = self.create_vdb_via_servlet(
                org_id=org_id,
                vdb_id=vdb_id,
                username=username,
                password=password,
                vdb_folder=vdb_folder,
                uploads_folder=uploads_folder
            )
            
            if not result.get('success'):
                error_msg = 'Servlet returned error: {}'.format(result.get('error'))
                logger.error('[PROVISIONING] {}'.format(error_msg))
                raise VDBProvisioningError(error_msg)
            
            logger.info('[PROVISIONING] VDB created successfully via servlet: {}'.format(vdb_id))
            
            # 5. Store VDB config in database
            # Use PostgreSQL-compatible port (35442) for query execution, not admin port
            logger.info('[PROVISIONING] Storing VDB config in database for org_id: {}'.format(org_id))
            vdb_config = OrganizationVDB(
                organization_id=org_id,
                vdb_id=vdb_id,
                vdb_username=username,
                vdb_host='127.0.0.1',  # Default to localhost
                vdb_port=35442,  # PostgreSQL-compatible port (resolved timeout issues)
                is_active=True
            )
            
            # Encrypt and store password
            vdb_config.set_encrypted_password(password)
            
            db.session.add(vdb_config)
            db.session.flush()  # Get the ID without committing
            
            logger.info('[PROVISIONING] VDB config stored in database with ID: {}'.format(
                vdb_config.id
            ))
            
            # 6. Verify VDB deployment (health check)
            logger.info('[PROVISIONING] Performing health check for VDB: {}'.format(vdb_id))
            health_result = self.check_vdb_health(vdb_config)
            health_ok = health_result.get('is_healthy', False)
            
            if not health_ok:
                logger.warning('[PROVISIONING] VDB health check failed for {}, but continuing. Status: {}'.format(
                    vdb_id, health_result.get('status', 'UNKNOWN')
                ))
                vdb_config.update_health_status('down')
            else:
                logger.info('[PROVISIONING] VDB health check passed for {}'.format(vdb_id))
                vdb_config.update_health_status('healthy')
            
            logger.info('[PROVISIONING] VDB provisioned successfully for org {} (id={}): {}'.format(
                organization.slug, org_id, vdb_id
            ))
            
            return vdb_config
            
        except VDBProvisioningError:
            # Re-raise VDBProvisioningError as-is (already logged)
            raise
            
        except Exception as e:
            error_msg = 'Failed to provision VDB for org {} (id={}): {}'.format(
                organization.slug, org_id, str(e)
            )
            logger.error('[PROVISIONING] {}'.format(error_msg), exc_info=True)
            raise VDBProvisioningError(error_msg)
    
    def create_vdb_via_servlet(self, org_id, vdb_id, username, password, vdb_folder, uploads_folder, vdb_type='organization', user_id=None):
        """
        Call Teiid servlet to create VDB from template.
        
        SECURITY: Credentials sent via HTTPS POST body with API key authentication.
        
        Args:
            org_id: Organization ID
            vdb_id: VDB identifier (7-digit number)
            username: VDB username
            password: VDB password
            vdb_folder: Path to VDB folder
            uploads_folder: Path to uploads folder
            vdb_type: Type of VDB ('organization', 'user', or 'shared')
            user_id: User ID (required for user VDBs, optional otherwise)
            
        Returns:
            Dict with 'success' and optional 'error' keys
        """
        # Ensure HTTPS is used in production (optional warning)
        if not self.teiid_servlet_url.startswith('https://'):
            logger.warning('Teiid servlet URL should use HTTPS in production for security')
        
        payload = {
            'org_id': org_id,
            'vdb_id': vdb_id,
            'username': username,
            'password': password,
            'teiid_host': self.teiid_host,
            'teiid_port': self.teiid_port,
            'vdb_type': vdb_type
        }
        
        # Add user_id for user VDBs
        if user_id is not None:
            payload['user_id'] = user_id
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        # Add API key if configured
        if self.servlet_api_key:
            headers['X-API-Key'] = self.servlet_api_key
        
        try:
            logger.info('Calling Teiid servlet to create VDB: {} (type: {})'.format(vdb_id, vdb_type))
            
            response = requests.post(
                '{}/createVDB'.format(self.teiid_servlet_url),
                json=payload,
                headers=headers,
                timeout=30,
                verify=True  # Verify SSL certificates
            )
            
            # Never log the payload (contains credentials)
            logger.info('VDB creation request sent for vdb_id: {}, type: {}, status: {}'.format(
                vdb_id, vdb_type, response.status_code
            ))
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = 'Servlet returned status {}: {}'.format(
                    response.status_code, response.text
                )
                logger.error(error_msg)
                return {'success': False, 'error': error_msg}
                
        except requests.exceptions.Timeout:
            error_msg = 'Servlet request timed out after 30 seconds'
            logger.error(error_msg)
            return {'success': False, 'error': error_msg}
            
        except requests.exceptions.RequestException as e:
            error_msg = 'Servlet communication failed: {}'.format(str(e))
            logger.error(error_msg)
            return {'success': False, 'error': error_msg}
            
        except Exception as e:
            error_msg = 'Unexpected error calling servlet: {}'.format(str(e))
            logger.error(error_msg)
            return {'success': False, 'error': error_msg}
    
    def delete_vdb(self, vdb_id):
        """
        Delete VDB from Teiid server.
        
        Args:
            vdb_id: VDB identifier to delete
            
        Returns:
            Dict with 'success' and optional 'error' keys
        """
        payload = {
            'vdb_id': vdb_id
        }
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        if self.servlet_api_key:
            headers['X-API-Key'] = self.servlet_api_key
        
        try:
            logger.info('Calling Teiid servlet to delete VDB: {}'.format(vdb_id))
            
            response = requests.post(
                '{}/deleteVDB'.format(self.teiid_servlet_url),
                json=payload,
                headers=headers,
                timeout=30,
                verify=True
            )
            
            logger.info('VDB deletion request sent for vdb_id: {}, status: {}'.format(
                vdb_id, response.status_code
            ))
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = 'Servlet returned status {}: {}'.format(
                    response.status_code, response.text
                )
                logger.error(error_msg)
                return {'success': False, 'error': error_msg}
                
        except Exception as e:
            error_msg = 'Failed to delete VDB via servlet: {}'.format(str(e))
            logger.error(error_msg)
            return {'success': False, 'error': error_msg}
    
    def update_vdb_credentials(self, vdb_id, new_username, new_password):
        """
        Update VDB credentials (credential rotation).
        
        Args:
            vdb_id: VDB identifier
            new_username: New VDB username
            new_password: New VDB password
            
        Returns:
            Dict with 'success' and optional 'error' keys
        """
        payload = {
            'vdb_id': vdb_id,
            'username': new_username,
            'password': new_password
        }
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        if self.servlet_api_key:
            headers['X-API-Key'] = self.servlet_api_key
        
        try:
            logger.info('Calling Teiid servlet to update VDB credentials: {}'.format(vdb_id))
            
            response = requests.post(
                '{}/updateVDBCredentials'.format(self.teiid_servlet_url),
                json=payload,
                headers=headers,
                timeout=30,
                verify=True
            )
            
            logger.info('VDB credential update request sent for vdb_id: {}, status: {}'.format(
                vdb_id, response.status_code
            ))
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = 'Servlet returned status {}: {}'.format(
                    response.status_code, response.text
                )
                logger.error(error_msg)
                return {'success': False, 'error': error_msg}
                
        except Exception as e:
            error_msg = 'Failed to update VDB credentials via servlet: {}'.format(str(e))
            logger.error(error_msg)
            return {'success': False, 'error': error_msg}
    
    def check_vdb_health(self, vdb_config):
        """
        Check VDB deployment status on WildFly/Teiid server.
        
        Queries the Teiid Admin API via servlet to get actual VDB deployment status.
        
        Args:
            vdb_config: OrganizationVDB instance
            
        Returns:
            dict with 'is_healthy' (bool) and 'response_time' (int in ms)
        """
        try:
            logger.info('Checking VDB status on WildFly for: {}'.format(vdb_config.vdb_id))
            
            # Build request to servlet
            servlet_url = '{}/checkVDBStatus'.format(self.teiid_servlet_url.rstrip('/'))
            
            payload = {
                'vdb_id': vdb_config.vdb_id,
                'teiid_host': self.teiid_host,
                'teiid_port': self.teiid_port
            }
            
            headers = {
                'Content-Type': 'application/json'
            }
            
            # Add API key if configured
            if self.servlet_api_key:
                headers['X-API-Key'] = self.servlet_api_key
            
            # Call servlet to check VDB status
            response = requests.post(
                servlet_url,
                json=payload,
                headers=headers,
                timeout=10,
                verify=True
            )
            
            if response.status_code != 200:
                logger.error('Servlet returned error: {} - {}'.format(
                    response.status_code, response.text
                ))
                return {
                    'is_healthy': False,
                    'response_time': 0,
                    'status': 'ERROR',
                    'error': 'Servlet error: {}'.format(response.status_code)
                }
            
            result = response.json()
            
            # Check if VDB is ACTIVE on WildFly
            vdb_status = result.get('status', 'UNKNOWN')
            response_time = result.get('response_time', 0)
            is_healthy = vdb_status == 'ACTIVE'
            
            if is_healthy:
                logger.info('VDB is ACTIVE on WildFly: {} ({}ms)'.format(
                    vdb_config.vdb_id, response_time
                ))
            else:
                logger.warning('VDB status on WildFly: {} - {}'.format(
                    vdb_config.vdb_id, vdb_status
                ))
            
            return {
                'is_healthy': is_healthy,
                'response_time': response_time,
                'status': vdb_status,
                'details': result
            }
            
        except Exception as e:
            logger.error('VDB health check error for {}: {}'.format(
                vdb_config.vdb_id, str(e)
            ))
            return {
                'is_healthy': False,
                'response_time': 0,
                'status': 'ERROR',
                'error': str(e)
            }
    
    def provision_user_vdb(self, user_id, org_id):
        """
        Provision a new VDB for a user.
        
        This method creates a dedicated VDB for a user with unique credentials
        and folder structure for user-level data isolation.
        
        Steps:
        1. Generate unique VDB identifier (7-digit random)
        2. Generate unique credentials
        3. Create user folder structure
        4. Call Teiid servlet to create VDB with vdb_type='user'
        5. Store UserVDB record in database
        6. Verify VDB deployment
        
        Args:
            user_id: User ID
            org_id: Organization ID
            
        Returns:
            UserVDB instance
            
        Raises:
            VDBProvisioningError: If provisioning fails at any step
        """
        logger.info('[USER_VDB_PROVISIONING] Starting VDB provisioning for user_id: {}, org_id: {}'.format(
            user_id, org_id
        ))
        
        try:
            # 1. Generate VDB ID
            vdb_id = generate_vdb_id()
            logger.info('[USER_VDB_PROVISIONING] Generated VDB ID: {}'.format(vdb_id))
            
            # 2. Generate credentials
            username, password = generate_vdb_credentials()
            logger.info('[USER_VDB_PROVISIONING] Generated VDB credentials for user: {}'.format(username))
            
            # 3. Create user folder structure
            from redash.services.customer_folders import CustomerFolderService
            folder_service = CustomerFolderService()
            folder_created = folder_service.create_user_folders(org_id, user_id)
            
            if not folder_created:
                raise VDBProvisioningError('Failed to create user folders')
            
            user_vdb_folder = folder_service.get_user_vdb_folder(org_id, user_id)
            user_uploads_folder = folder_service.get_user_uploads_folder(org_id, user_id)
            
            logger.info('[USER_VDB_PROVISIONING] User VDB folder: {}, Uploads folder: {}'.format(
                user_vdb_folder, user_uploads_folder
            ))
            
            # 4. Create VDB via servlet with vdb_type='user'
            logger.info('[USER_VDB_PROVISIONING] Calling servlet to create user VDB')
            result = self.create_vdb_via_servlet(
                org_id=org_id,
                vdb_id=vdb_id,
                username=username,
                password=password,
                vdb_folder=user_vdb_folder,
                uploads_folder=user_uploads_folder,
                vdb_type='user',
                user_id=user_id
            )
            
            if not result.get('success'):
                error_msg = 'Servlet returned error: {}'.format(result.get('error'))
                logger.error('[USER_VDB_PROVISIONING] {}'.format(error_msg))
                raise VDBProvisioningError(error_msg)
            
            logger.info('[USER_VDB_PROVISIONING] User VDB created successfully via servlet: {}'.format(vdb_id))
            
            # 5. Store UserVDB record in database
            logger.info('[USER_VDB_PROVISIONING] Storing UserVDB config in database')
            user_vdb = UserVDB(
                user_id=user_id,
                organization_id=org_id,
                vdb_id=vdb_id,
                vdb_username=username,
                vdb_host='127.0.0.1',
                vdb_port=35442,
                is_active=True
            )
            
            # Encrypt and store password
            user_vdb.set_encrypted_password(password)
            
            db.session.add(user_vdb)
            db.session.flush()
            
            logger.info('[USER_VDB_PROVISIONING] UserVDB config stored in database with ID: {}'.format(
                user_vdb.id
            ))
            
            # 6. Verify VDB deployment (health check)
            logger.info('[USER_VDB_PROVISIONING] Performing health check for user VDB: {}'.format(vdb_id))
            health_result = self.check_vdb_health(user_vdb)
            health_ok = health_result.get('is_healthy', False)
            
            if not health_ok:
                logger.warning('[USER_VDB_PROVISIONING] VDB health check failed for {}, but continuing. Status: {}'.format(
                    vdb_id, health_result.get('status', 'UNKNOWN')
                ))
                user_vdb.update_health_status('down')
            else:
                logger.info('[USER_VDB_PROVISIONING] VDB health check passed for {}'.format(vdb_id))
                user_vdb.update_health_status('healthy')
            
            logger.info('[USER_VDB_PROVISIONING] User VDB provisioned successfully for user_id {}: {}'.format(
                user_id, vdb_id
            ))
            
            return user_vdb
            
        except VDBProvisioningError:
            raise
            
        except Exception as e:
            error_msg = 'Failed to provision user VDB for user_id {} (org_id={}): {}'.format(
                user_id, org_id, str(e)
            )
            logger.error('[USER_VDB_PROVISIONING] {}'.format(error_msg), exc_info=True)
            raise VDBProvisioningError(error_msg)

    def provision_shared_vdb(self, org_id):
        """
        Provision a shared VDB for an organization.
        
        This method creates a dedicated shared VDB for an organization to enable
        collaborative data access for shared projects.
        
        Steps:
        1. Generate unique VDB identifier (7-digit random)
        2. Generate unique credentials
        3. Create shared folder structure
        4. Call Teiid servlet to create VDB with vdb_type='shared'
        5. Store SharedVDB record in database
        6. Verify VDB deployment
        
        Args:
            org_id: Organization ID
            
        Returns:
            SharedVDB instance
            
        Raises:
            VDBProvisioningError: If provisioning fails at any step
        """
        logger.info('[SHARED_VDB_PROVISIONING] Starting shared VDB provisioning for org_id: {}'.format(org_id))
        
        try:
            # 1. Generate VDB ID
            vdb_id = generate_vdb_id()
            logger.info('[SHARED_VDB_PROVISIONING] Generated VDB ID: {}'.format(vdb_id))
            
            # 2. Generate credentials
            username, password = generate_vdb_credentials()
            logger.info('[SHARED_VDB_PROVISIONING] Generated VDB credentials for user: {}'.format(username))
            
            # 3. Create shared folder structure
            from redash.services.customer_folders import CustomerFolderService
            folder_service = CustomerFolderService()
            folder_created = folder_service.create_shared_folders(org_id)
            
            if not folder_created:
                raise VDBProvisioningError('Failed to create shared folders')
            
            shared_vdb_folder = folder_service.get_shared_vdb_folder(org_id)
            shared_uploads_folder = folder_service.get_shared_uploads_folder(org_id)
            
            logger.info('[SHARED_VDB_PROVISIONING] Shared VDB folder: {}, Uploads folder: {}'.format(
                shared_vdb_folder, shared_uploads_folder
            ))
            
            # 4. Create VDB via servlet with vdb_type='shared'
            logger.info('[SHARED_VDB_PROVISIONING] Calling servlet to create shared VDB')
            result = self.create_vdb_via_servlet(
                org_id=org_id,
                vdb_id=vdb_id,
                username=username,
                password=password,
                vdb_folder=shared_vdb_folder,
                uploads_folder=shared_uploads_folder,
                vdb_type='shared',
                user_id=None
            )
            
            if not result.get('success'):
                error_msg = 'Servlet returned error: {}'.format(result.get('error'))
                logger.error('[SHARED_VDB_PROVISIONING] {}'.format(error_msg))
                raise VDBProvisioningError(error_msg)
            
            logger.info('[SHARED_VDB_PROVISIONING] Shared VDB created successfully via servlet: {}'.format(vdb_id))
            
            # 5. Store SharedVDB record in database
            logger.info('[SHARED_VDB_PROVISIONING] Storing SharedVDB config in database')
            shared_vdb = SharedVDB(
                organization_id=org_id,
                vdb_id=vdb_id,
                vdb_username=username,
                vdb_host='127.0.0.1',
                vdb_port=35442,
                is_active=True
            )
            
            # Encrypt and store password
            shared_vdb.set_encrypted_password(password)
            
            db.session.add(shared_vdb)
            db.session.flush()
            
            logger.info('[SHARED_VDB_PROVISIONING] SharedVDB config stored in database with ID: {}'.format(
                shared_vdb.id
            ))
            
            # 6. Verify VDB deployment (health check)
            logger.info('[SHARED_VDB_PROVISIONING] Performing health check for shared VDB: {}'.format(vdb_id))
            health_result = self.check_vdb_health(shared_vdb)
            health_ok = health_result.get('is_healthy', False)
            
            if not health_ok:
                logger.warning('[SHARED_VDB_PROVISIONING] VDB health check failed for {}, but continuing. Status: {}'.format(
                    vdb_id, health_result.get('status', 'UNKNOWN')
                ))
                shared_vdb.update_health_status('down')
            else:
                logger.info('[SHARED_VDB_PROVISIONING] VDB health check passed for {}'.format(vdb_id))
                shared_vdb.update_health_status('healthy')
            
            logger.info('[SHARED_VDB_PROVISIONING] Shared VDB provisioned successfully for org_id {}: {}'.format(
                org_id, vdb_id
            ))
            
            return shared_vdb
            
        except VDBProvisioningError:
            raise
            
        except Exception as e:
            error_msg = 'Failed to provision shared VDB for org_id {}: {}'.format(
                org_id, str(e)
            )
            logger.error('[SHARED_VDB_PROVISIONING] {}'.format(error_msg), exc_info=True)
            raise VDBProvisioningError(error_msg)

    def redeploy_user_vdb(self, user_id):
        """
        Redeploy user VDB with updated data sources/queries.
        
        This method updates an existing user VDB with current data sources
        and query definitions without creating a new VDB.
        
        Args:
            user_id: User ID
            
        Returns:
            Dict with 'success' and optional 'error' keys
            
        Raises:
            VDBProvisioningError: If user VDB not found or redeployment fails
        """
        logger.info('[USER_VDB_REDEPLOY] Starting VDB redeployment for user_id: {}'.format(user_id))
        
        try:
            # Retrieve UserVDB from database
            user_vdb = UserVDB.get_by_user(user_id)
            if not user_vdb:
                raise VDBProvisioningError('No VDB found for user {}'.format(user_id))
            
            logger.info('[USER_VDB_REDEPLOY] Found user VDB: {}'.format(user_vdb.vdb_id))
            
            # Get folder paths
            from redash.services.customer_folders import CustomerFolderService
            folder_service = CustomerFolderService()
            user_vdb_folder = folder_service.get_user_vdb_folder(user_vdb.organization_id, user_id)
            user_uploads_folder = folder_service.get_user_uploads_folder(user_vdb.organization_id, user_id)
            
            # Call servlet to redeploy VDB
            logger.info('[USER_VDB_REDEPLOY] Calling servlet to redeploy user VDB')
            result = self.create_vdb_via_servlet(
                org_id=user_vdb.organization_id,
                vdb_id=user_vdb.vdb_id,
                username=user_vdb.vdb_username,
                password=user_vdb.get_decrypted_password(),
                vdb_folder=user_vdb_folder,
                uploads_folder=user_uploads_folder,
                vdb_type='user',
                user_id=user_id
            )
            
            if not result.get('success'):
                error_msg = 'Servlet returned error: {}'.format(result.get('error'))
                logger.error('[USER_VDB_REDEPLOY] {}'.format(error_msg))
                raise VDBProvisioningError(error_msg)
            
            logger.info('[USER_VDB_REDEPLOY] User VDB redeployed successfully: {}'.format(user_vdb.vdb_id))
            
            return result
            
        except VDBProvisioningError:
            raise
            
        except Exception as e:
            error_msg = 'Failed to redeploy user VDB for user_id {}: {}'.format(
                user_id, str(e)
            )
            logger.error('[USER_VDB_REDEPLOY] {}'.format(error_msg), exc_info=True)
            raise VDBProvisioningError(error_msg)
    
    def redeploy_shared_vdb(self, org_id):
        """
        Redeploy shared VDB with updated shared data sources.
        
        This method updates an existing shared VDB with current shared data sources
        without creating a new VDB.
        
        Args:
            org_id: Organization ID
            
        Returns:
            Dict with 'success' and optional 'error' keys
            
        Raises:
            VDBProvisioningError: If shared VDB not found or redeployment fails
        """
        logger.info('[SHARED_VDB_REDEPLOY] Starting shared VDB redeployment for org_id: {}'.format(org_id))
        
        try:
            # Retrieve SharedVDB from database
            shared_vdb = SharedVDB.get_by_organization(org_id)
            if not shared_vdb:
                raise VDBProvisioningError('No shared VDB found for org {}'.format(org_id))
            
            logger.info('[SHARED_VDB_REDEPLOY] Found shared VDB: {}'.format(shared_vdb.vdb_id))
            
            # Get folder paths
            from redash.services.customer_folders import CustomerFolderService
            folder_service = CustomerFolderService()
            shared_vdb_folder = folder_service.get_shared_vdb_folder(org_id)
            shared_uploads_folder = folder_service.get_shared_uploads_folder(org_id)
            
            # Call servlet to redeploy VDB
            logger.info('[SHARED_VDB_REDEPLOY] Calling servlet to redeploy shared VDB')
            result = self.create_vdb_via_servlet(
                org_id=org_id,
                vdb_id=shared_vdb.vdb_id,
                username=shared_vdb.vdb_username,
                password=shared_vdb.get_decrypted_password(),
                vdb_folder=shared_vdb_folder,
                uploads_folder=shared_uploads_folder,
                vdb_type='shared',
                user_id=None
            )
            
            if not result.get('success'):
                error_msg = 'Servlet returned error: {}'.format(result.get('error'))
                logger.error('[SHARED_VDB_REDEPLOY] {}'.format(error_msg))
                raise VDBProvisioningError(error_msg)
            
            logger.info('[SHARED_VDB_REDEPLOY] Shared VDB redeployed successfully: {}'.format(shared_vdb.vdb_id))
            
            return result
            
        except VDBProvisioningError:
            raise
            
        except Exception as e:
            error_msg = 'Failed to redeploy shared VDB for org_id {}: {}'.format(
                org_id, str(e)
            )
            logger.error('[SHARED_VDB_REDEPLOY] {}'.format(error_msg), exc_info=True)
            raise VDBProvisioningError(error_msg)
