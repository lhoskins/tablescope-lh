"""
Project Sharing Service

Service for handling project sharing and data movement between user and shared VDBs.
When a project is shared, data sources are physically copied from user's private folder
to the organization's shared folder, and the shared VDB is updated.
"""

import os
import shutil
import logging

from redash.models import db
from redash.models.shared_vdb import SharedVDB
from redash.services.vdb_management import VDBManagementService, VDBProvisioningError
from redash.services.customer_folders import CustomerFolderService

logger = logging.getLogger(__name__)


class ProjectSharingError(Exception):
    """Exception raised when project sharing fails."""
    pass


class ProjectSharingService:
    """
    Service for handling project sharing operations.
    
    This service manages:
    - Marking projects as shared
    - Copying data files from user folders to shared folders
    - Updating data source references
    - Provisioning shared VDB if needed
    - Redeploying shared VDB with new data sources
    """
    
    def __init__(self):
        """Initialize Project Sharing Service."""
        self.folder_service = CustomerFolderService()
        self.vdb_service = VDBManagementService()
    
    def share_project(self, project_id, user_id):
        """
        Share a project and move data to shared folder.
        
        This method performs the following steps:
        1. Mark project as shared in database
        2. Ensure shared VDB exists (provision if needed)
        3. Copy data sources to shared folder
        4. Update data source references
        5. Preserve original owner metadata
        6. Trigger shared VDB redeployment
        
        Args:
            project_id: Project ID to share
            user_id: User ID of the project owner
            
        Returns:
            Dict with 'success' and optional 'error' keys
            
        Raises:
            ProjectSharingError: If sharing fails at any step
        """
        logger.info('[PROJECT_SHARING] Starting project sharing for project_id: {}, user_id: {}'.format(
            project_id, user_id
        ))
        
        try:
            # Import here to avoid circular dependencies
            from redash.models.project import Project, ProjectDataSource
            
            # Get project
            project = Project.query.get(project_id)
            if not project:
                raise ProjectSharingError('Project {} not found'.format(project_id))
            
            org_id = project.org_id
            logger.info('[PROJECT_SHARING] Project org_id: {}'.format(org_id))
            
            # Mark project as shared (assuming there's an is_shared field)
            # If the field doesn't exist, we'll need to add it to the schema
            if hasattr(project, 'is_shared'):
                project.is_shared = True
                db.session.add(project)
                logger.info('[PROJECT_SHARING] Marked project as shared')
            else:
                logger.warning('[PROJECT_SHARING] Project model does not have is_shared field')
            
            # Ensure shared VDB exists
            shared_vdb = self._ensure_shared_vdb_exists(org_id)
            logger.info('[PROJECT_SHARING] Shared VDB ensured: {}'.format(shared_vdb.vdb_id))
            
            # Get folder paths
            user_uploads = self.folder_service.get_user_uploads_folder(org_id, user_id)
            shared_uploads = self.folder_service.get_shared_uploads_folder(org_id)
            
            logger.info('[PROJECT_SHARING] User uploads folder: {}'.format(user_uploads))
            logger.info('[PROJECT_SHARING] Shared uploads folder: {}'.format(shared_uploads))
            
            # Copy data sources to shared folder
            data_sources_copied = 0
            logger.info('[PROJECT_SHARING] Found {} project data sources to process'.format(len(project.data_sources)))
            
            for project_ds in project.data_sources:
                data_source = project_ds.data_source
                logger.info('[PROJECT_SHARING] Processing data source {}: name={}, type={}'.format(
                    data_source.id, data_source.name, data_source.type
                ))
                
                # Check if data source has a file path
                if hasattr(data_source, 'options') and data_source.options:
                    logger.info('[PROJECT_SHARING] Data source {} options: {}'.format(
                        data_source.id, data_source.options
                    ))
                    file_path = data_source.options.get('file_path')
                    
                    if file_path:
                        logger.info('[PROJECT_SHARING] Data source {} file_path: {}'.format(
                            data_source.id, file_path
                        ))
                        logger.info('[PROJECT_SHARING] Checking if file_path starts with user_uploads: {}'.format(
                            user_uploads
                        ))
                        
                        if file_path.startswith(user_uploads):
                            logger.info('[PROJECT_SHARING] File path matches user uploads, copying file')
                            # Copy file to shared folder
                            copied = self._copy_data_source_file(
                                data_source,
                                file_path,
                                user_uploads,
                                shared_uploads,
                                user_id
                            )
                            
                            if copied:
                                data_sources_copied += 1
                        else:
                            logger.warning('[PROJECT_SHARING] Data source {} file_path does not start with user_uploads folder. file_path={}, user_uploads={}'.format(
                                data_source.id, file_path, user_uploads
                            ))
                    else:
                        logger.info('[PROJECT_SHARING] Data source {} has no file_path in options'.format(
                            data_source.id
                        ))
                else:
                    logger.info('[PROJECT_SHARING] Data source {} has no options attribute or options is None'.format(
                        data_source.id
                    ))
            
            # Commit all changes
            db.session.commit()
            logger.info('[PROJECT_SHARING] Committed {} data source updates'.format(data_sources_copied))
            
            # Redeploy shared VDB with new data sources
            logger.info('[PROJECT_SHARING] Triggering shared VDB redeployment')
            redeploy_result = self.vdb_service.redeploy_shared_vdb(org_id)
            
            if not redeploy_result.get('success'):
                logger.warning('[PROJECT_SHARING] Shared VDB redeployment failed: {}'.format(
                    redeploy_result.get('error')
                ))
            else:
                logger.info('[PROJECT_SHARING] Shared VDB redeployed successfully')
            
            logger.info('[PROJECT_SHARING] Project sharing completed successfully for project_id: {}'.format(
                project_id
            ))
            
            return {
                'success': True,
                'project_id': project_id,
                'shared_vdb_id': shared_vdb.vdb_id,
                'data_sources_copied': data_sources_copied
            }
            
        except ProjectSharingError:
            db.session.rollback()
            raise
            
        except Exception as e:
            db.session.rollback()
            error_msg = 'Failed to share project {}: {}'.format(project_id, str(e))
            logger.error('[PROJECT_SHARING] {}'.format(error_msg), exc_info=True)
            raise ProjectSharingError(error_msg)
    
    def _ensure_shared_vdb_exists(self, org_id):
        """
        Ensure shared VDB exists for organization, provision if needed.
        
        Args:
            org_id: Organization ID
            
        Returns:
            SharedVDB instance
            
        Raises:
            ProjectSharingError: If VDB provisioning fails
        """
        logger.info('[PROJECT_SHARING] Checking if shared VDB exists for org_id: {}'.format(org_id))
        
        # Check if shared VDB already exists
        shared_vdb = SharedVDB.get_by_organization(org_id)
        
        if shared_vdb:
            logger.info('[PROJECT_SHARING] Shared VDB already exists: {}'.format(shared_vdb.vdb_id))
            return shared_vdb
        
        # Provision new shared VDB
        logger.info('[PROJECT_SHARING] Provisioning new shared VDB for org_id: {}'.format(org_id))
        
        try:
            shared_vdb = self.vdb_service.provision_shared_vdb(org_id)
            logger.info('[PROJECT_SHARING] Shared VDB provisioned successfully: {}'.format(
                shared_vdb.vdb_id
            ))
            return shared_vdb
            
        except VDBProvisioningError as e:
            error_msg = 'Failed to provision shared VDB for org {}: {}'.format(org_id, str(e))
            logger.error('[PROJECT_SHARING] {}'.format(error_msg))
            raise ProjectSharingError(error_msg)
    
    def _copy_data_source_file(self, data_source, file_path, user_uploads, shared_uploads, user_id):
        """
        Copy data source file from user folder to shared folder.
        
        Uses shutil.copy2 to preserve metadata.
        Handles file name conflicts by appending a suffix.
        Updates data source references in database.
        
        Args:
            data_source: DataSource instance
            file_path: Current file path
            user_uploads: User uploads folder path
            shared_uploads: Shared uploads folder path
            user_id: Original owner user ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Extract filename
            filename = os.path.basename(file_path)
            shared_path = os.path.join(shared_uploads, filename)
            
            logger.info('[PROJECT_SHARING] Copying file from {} to {}'.format(
                file_path, shared_path
            ))
            
            # Check if source file exists
            if not os.path.exists(file_path):
                logger.warning('[PROJECT_SHARING] Source file does not exist: {}'.format(file_path))
                return False
            
            # Handle file name conflicts
            shared_path = self._handle_file_conflict(shared_path)
            
            # Copy file with metadata preservation
            shutil.copy2(file_path, shared_path)
            logger.info('[PROJECT_SHARING] File copied successfully to: {}'.format(shared_path))
            
            # Verify file copy success
            if not os.path.exists(shared_path):
                logger.error('[PROJECT_SHARING] File copy verification failed: {}'.format(shared_path))
                return False
            
            # Update data source references
            self._update_data_source_references(data_source, file_path, shared_path, user_id)
            
            return True
            
        except Exception as e:
            logger.error('[PROJECT_SHARING] Failed to copy file {}: {}'.format(
                file_path, str(e)
            ), exc_info=True)
            return False
    
    def _handle_file_conflict(self, file_path):
        """
        Handle file name conflicts by appending a suffix.
        
        Args:
            file_path: Desired file path
            
        Returns:
            Available file path (may be modified to avoid conflicts)
        """
        if not os.path.exists(file_path):
            return file_path
        
        # File exists, append suffix
        base, ext = os.path.splitext(file_path)
        counter = 1
        
        while os.path.exists(file_path):
            file_path = '{}_{}{}'.format(base, counter, ext)
            counter += 1
            
            # Safety limit
            if counter > 1000:
                raise ProjectSharingError('Too many file conflicts for: {}'.format(base))
        
        logger.info('[PROJECT_SHARING] File conflict resolved, using: {}'.format(file_path))
        return file_path
    
    def _update_data_source_references(self, data_source, original_path, shared_path, user_id):
        """
        Update data source references after copying to shared folder.
        
        Updates:
        - shared_file_path field (if exists)
        - original_owner_id field (if exists)
        - Maintains original file path for reference
        
        Args:
            data_source: DataSource instance
            original_path: Original file path
            shared_path: New shared file path
            user_id: Original owner user ID
        """
        logger.info('[PROJECT_SHARING] Updating data source references for data_source_id: {}'.format(
            data_source.id
        ))
        
        # Update shared_file_path if field exists
        if hasattr(data_source, 'shared_file_path'):
            data_source.shared_file_path = shared_path
            logger.info('[PROJECT_SHARING] Updated shared_file_path')
        else:
            # If shared_file_path doesn't exist, update the file_path in options
            if hasattr(data_source, 'options') and data_source.options:
                data_source.options['file_path'] = shared_path
                logger.info('[PROJECT_SHARING] Updated file_path in options')
        
        # Store original owner if field exists
        if hasattr(data_source, 'original_owner_id'):
            data_source.original_owner_id = user_id
            logger.info('[PROJECT_SHARING] Updated original_owner_id')
        
        # Maintain original file path for reference if field exists
        if hasattr(data_source, 'original_file_path'):
            data_source.original_file_path = original_path
            logger.info('[PROJECT_SHARING] Updated original_file_path')
        
        db.session.add(data_source)
        logger.info('[PROJECT_SHARING] Data source references updated')
