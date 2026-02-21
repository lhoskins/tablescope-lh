"""
VDB Updater Service

Automatically updates VDB file paths when files are uploaded to ensure
the VDB always points to the correct customer-specific folder.
"""

import os
import re
import logging
import requests
from redash.services.customer_folders import CustomerFolderService
from redash.models import db

logger = logging.getLogger(__name__)


class VDBUpdaterService:
    """
    Service for updating VDB files with correct customer paths.
    
    This service ensures that VDB files always reference the correct
    customer-specific upload folders, even if the VDB was created
    before multi-tenancy was implemented.
    """
    
    def __init__(self):
        self.folder_service = CustomerFolderService()
    
    def update_vdb_paths_for_org(self, org_id):
        """
        Update VDB file paths for an organization to use customer-specific folders.
        
        This method:
        1. Finds the VDB file for the organization
        2. Updates all file path references to use customer uploads folder
        3. Writes the updated VDB back to disk
        
        Args:
            org_id: Organization ID
            
        Returns:
            bool: True if VDB was updated, False if no VDB found or update failed
        """
        try:
            logger.info('Updating VDB paths for organization {}'.format(org_id))
            
            # Get customer folders
            vdb_folder = self.folder_service.get_vdb_folder(org_id)
            uploads_folder = self.folder_service.get_uploads_folder(org_id)
            
            # Find VDB file
            vdb_file_path = self._find_vdb_file(vdb_folder, org_id)
            
            if not vdb_file_path:
                logger.warning('No VDB file found for organization {}'.format(org_id))
                return False
            
            logger.info('Found VDB file: {}'.format(vdb_file_path))
            
            # Read VDB content
            with open(vdb_file_path, 'r') as f:
                vdb_content = f.read()
            
            # Update paths
            updated_content = self._update_file_paths(vdb_content, uploads_folder)
            
            # Check if anything changed
            paths_changed = (updated_content != vdb_content)
            
            if paths_changed:
                # Write updated VDB
                with open(vdb_file_path, 'w') as f:
                    f.write(updated_content)
                logger.info('VDB paths updated successfully for organization {}'.format(org_id))
            else:
                logger.info('VDB paths already correct for organization {}'.format(org_id))
            
            # Always trigger VDB reload after file upload
            # This ensures Teiid picks up new files even if paths haven't changed
            logger.info('Redeploying VDB to pick up new files for organization {}'.format(org_id))
            redeploy_success = self._trigger_vdb_reload(vdb_file_path)
            
            if redeploy_success:
                logger.info('VDB redeployed successfully for organization {}'.format(org_id))
            else:
                logger.warning('VDB redeploy failed for organization {}'.format(org_id))
            
            return True
            
        except Exception as e:
            logger.error('Failed to update VDB paths for org {}: {}'.format(org_id, str(e)))
            return False
    
    def update_vdb_paths_for_user(self, org_id, user_id):
        """
        Update VDB file paths for a user to use user-specific folders.
        
        This method:
        1. Finds the VDB file for the user
        2. Updates all file path references to use user uploads folder
        3. Writes the updated VDB back to disk
        4. Triggers VDB redeployment
        
        Args:
            org_id: Organization ID
            user_id: User ID
            
        Returns:
            bool: True if VDB was updated, False if no VDB found or update failed
        """
        try:
            logger.info('Updating user VDB paths for org {}, user {}'.format(org_id, user_id))
            
            # Get user folders
            vdb_folder = self.folder_service.get_user_vdb_folder(org_id, user_id)
            uploads_folder = self.folder_service.get_user_uploads_folder(org_id, user_id)
            
            # Find VDB file
            vdb_file_path = self._find_vdb_file(vdb_folder, org_id)
            
            if not vdb_file_path:
                logger.warning('No user VDB file found for org {}, user {}'.format(org_id, user_id))
                return False
            
            logger.info('Found user VDB file: {}'.format(vdb_file_path))
            
            # Read VDB content
            with open(vdb_file_path, 'r') as f:
                vdb_content = f.read()
            
            # Update paths
            updated_content = self._update_file_paths(vdb_content, uploads_folder)
            
            # Check if anything changed
            paths_changed = (updated_content != vdb_content)
            
            if paths_changed:
                # Write updated VDB
                with open(vdb_file_path, 'w') as f:
                    f.write(updated_content)
                logger.info('User VDB paths updated successfully for org {}, user {}'.format(org_id, user_id))
            else:
                logger.info('User VDB paths already correct for org {}, user {}'.format(org_id, user_id))
            
            # Always trigger VDB reload after file upload
            # This ensures Teiid picks up new files even if paths haven't changed
            logger.info('Redeploying user VDB to pick up new files for org {}, user {}'.format(org_id, user_id))
            redeploy_success = self._trigger_vdb_reload(vdb_file_path)
            
            if redeploy_success:
                logger.info('User VDB redeployed successfully for org {}, user {}'.format(org_id, user_id))
            else:
                logger.warning('User VDB redeploy failed for org {}, user {}'.format(org_id, user_id))
            
            return True
            
        except Exception as e:
            logger.error('Failed to update user VDB paths for org {}, user {}: {}'.format(org_id, user_id, str(e)))
            return False
    
    def _find_vdb_file(self, vdb_folder, org_id):
        """
        Find VDB file in the customer VDB folder.
        
        Args:
            vdb_folder: Path to VDB folder
            org_id: Organization ID
            
        Returns:
            str: Path to VDB file, or None if not found
        """
        try:
            if not os.path.exists(vdb_folder):
                return None
            
            # Look for VDB files (typically vdb_<env>-vdb.xml)
            for filename in os.listdir(vdb_folder):
                if filename.endswith('-vdb.xml'):
                    return os.path.join(vdb_folder, filename)
            
            return None
            
        except Exception as e:
            logger.error('Error finding VDB file: {}'.format(str(e)))
            return None
    
    def _update_file_paths(self, vdb_content, uploads_folder):
        """
        Update all file path references in VDB XML to use relative paths.
        
        This method converts absolute paths to relative paths that work with
        AllowParentPaths=true in standalone.xml. The standalone.xml should have:
        - ParentDirectory=/opt/wildfly/teiidfiles/customers
        - AllowParentPaths=true
        
        Then VDB files use relative paths like:
        - '1/uploads/filename.xlsx' for org_id 1
        - '2/uploads/filename.xlsx' for org_id 2
        
        This method updates:
        - LOCATION attributes with file:// protocol
        - LOCATION attributes without protocol (teiid_excel:FILE syntax)
        - ParentDirectory properties (removed - use standalone.xml config)
        - Importer properties
        - Connection URL properties
        
        Args:
            vdb_content: VDB XML content as string
            uploads_folder: Customer uploads folder path (e.g., /opt/wildfly/teiidfiles/customers/1/uploads)
            
        Returns:
            str: Updated VDB XML content with relative paths
        """
        updated = vdb_content
        
        # Extract org_id and user_id from uploads_folder path
        # uploads_folder format: /opt/wildfly/teiidfiles/customers/{org_id}/uploads (org VDB)
        #                    or: /opt/wildfly/teiidfiles/customers/{org_id}/{user_id}/uploads (user VDB)
        
        # Try user VDB path first (with user_id)
        user_match = re.search(r'/customers/(\d+)/(\d+)/uploads', uploads_folder)
        if user_match:
            org_id = user_match.group(1)
            user_id = user_match.group(2)
            relative_path_prefix = '{}/{}/uploads'.format(org_id, user_id)
            logger.info('Using user VDB path format: {}/...'.format(relative_path_prefix))
        else:
            # Try org VDB path (without user_id)
            org_match = re.search(r'/customers/(\d+)/uploads', uploads_folder)
            if org_match:
                org_id = org_match.group(1)
                relative_path_prefix = '{}/uploads'.format(org_id)
                logger.info('Using org VDB path format: {}/...'.format(relative_path_prefix))
            else:
                logger.warning('Could not extract org_id from uploads_folder: {}'.format(uploads_folder))
                return updated
        
        # Pattern 1: LOCATION with file:// protocol
        # file:///opt/wildfly/teiidfiles/.../filename.xlsx -> file:///{org_id}/uploads/filename.xlsx
        updated = re.sub(
            r"LOCATION='file:///opt/wildfly/teiidfiles/(?:excelFilesTest|CSVFiles|customers/\d+/uploads)/([^']+)'",
            r"LOCATION='file:///" + relative_path_prefix + r"/\1'",
            updated
        )
        updated = re.sub(
            r"LOCATION='file:///opt/wildfly/teiidfiles/([^']+)'",
            r"LOCATION='file:///" + relative_path_prefix + r"/\1'",
            updated
        )
        
        # Pattern 2: LOCATION without protocol (teiid_excel:FILE syntax)
        # "teiid_excel:FILE" '/opt/wildfly/.../file.xlsx' -> "teiid_excel:FILE" '{org_id}/uploads/file.xlsx'
        updated = re.sub(
            r'"teiid_excel:FILE"\s+\'/opt/wildfly/teiidfiles/(?:excelFilesTest|CSVFiles|customers/\d+/uploads)/([^\']+)\'',
            r'"teiid_excel:FILE" \'' + relative_path_prefix + r"/\1'",
            updated
        )
        updated = re.sub(
            r'"teiid_excel:FILE"\s+\'/opt/wildfly/teiidfiles/([^\']+)\'',
            r'"teiid_excel:FILE" \'' + relative_path_prefix + r"/\1'",
            updated
        )
        
        # Pattern 3: Remove ParentDirectory properties from VDB
        # (ParentDirectory should be configured in standalone.xml, not per-VDB)
        updated = re.sub(
            r'\s*<property name="ParentDirectory" value="[^"]*"/>\s*\n?',
            '',
            updated
        )
        
        # Pattern 4: Remove Importer ParentDirectory
        updated = re.sub(
            r'\s*<property name="importer\.ParentDirectory" value="[^"]*"/>\s*\n?',
            '',
            updated
        )
        
        # Pattern 5: Connection URL with file:// protocol
        updated = re.sub(
            r'<property name="connection-url" value="file:///opt/wildfly/teiidfiles/(?:excelFilesTest|CSVFiles|customers/\d+/uploads)/([^"]+)"',
            r'<property name="connection-url" value="file:///' + relative_path_prefix + r'/\1"',
            updated
        )
        updated = re.sub(
            r'<property name="connection-url" value="file:///opt/wildfly/teiidfiles/([^"]+)"',
            r'<property name="connection-url" value="file:///' + relative_path_prefix + r'/\1"',
            updated
        )
        
        # Pattern 6: LOCATION without file:// protocol (plain paths)
        # LOCATION='/opt/wildfly/teiidfiles/.../file.xlsx' -> LOCATION='{org_id}/uploads/file.xlsx'
        updated = re.sub(
            r"LOCATION='/opt/wildfly/teiidfiles/(?:excelFilesTest|CSVFiles|customers/\d+/uploads)/([^']+)'",
            r"LOCATION='" + relative_path_prefix + r"/\1'",
            updated
        )
        updated = re.sub(
            r"LOCATION='/opt/wildfly/teiidfiles/([^']+)'",
            r"LOCATION='" + relative_path_prefix + r"/\1'",
            updated
        )
        
        return updated
    
    def _trigger_vdb_reload(self, vdb_file_path):
        """
        Trigger VDB reload in Teiid by redeploying the VDB file.
        
        This uses the Teiid Admin API via the servlet to redeploy the VDB
        so that Teiid picks up the updated file paths.
        
        Args:
            vdb_file_path: Path to updated VDB file
        """
        try:
            logger.info('Redeploying VDB to Teiid: {}'.format(vdb_file_path))
            
            # Get VDB ID from filename (e.g., vdb_production-vdb.xml -> vdb_production)
            vdb_filename = os.path.basename(vdb_file_path)
            vdb_id = vdb_filename.replace('-vdb.xml', '')
            
            # Get Teiid configuration from database
            config = self._load_teiid_config()
            if not config:
                logger.error('Cannot redeploy VDB: Teiid configuration not found')
                return False
            
            # Call servlet to redeploy VDB
            servlet_url = config['servlet_url']
            payload = {
                'vdb_id': vdb_id,
                'vdb_file_path': vdb_file_path,
                'teiid_host': config['teiid_host'],
                'teiid_port': config['teiid_port']
            }
            
            headers = {
                'Content-Type': 'application/json'
            }
            
            if config.get('servlet_api_key'):
                headers['X-API-Key'] = config['servlet_api_key']
            
            response = requests.post(
                '{}/redeployVDB'.format(servlet_url),
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    logger.info('VDB redeployed successfully: {}'.format(vdb_id))
                    return True
                else:
                    logger.error('VDB redeploy failed: {}'.format(result.get('error')))
                    return False
            else:
                logger.error('VDB redeploy request failed: {} - {}'.format(
                    response.status_code, response.text
                ))
                return False
                
        except Exception as e:
            logger.error('Failed to redeploy VDB: {}'.format(str(e)))
            return False
    
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
                    servlet_url, servlet_api_key, teiid_host, teiid_port
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
                'teiid_port': result[3]
            }
        except Exception as e:
            logger.error('Failed to load Teiid config: {}'.format(str(e)))
            return None
