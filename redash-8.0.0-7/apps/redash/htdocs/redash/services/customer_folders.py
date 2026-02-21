# -*- coding: utf-8 -*-
"""
Customer Folder Management Service

Service for managing customer-specific folder structures for VDB files and uploads.
Each organization gets dedicated folders for data isolation.
"""

import os
import shutil
import logging
import time

from redash import settings

logger = logging.getLogger(__name__)


class CustomerFolderService:
    """
    Service for managing customer-specific folder structures.
    
    Creates and manages folder structure:
    /opt/wildfly/teiidfiles/customers/<org_id>/
    ├── vdb/        # VDB XML files
    └── uploads/    # Uploaded data files
    """
    
    def __init__(self, base_path=None):
        """
        Initialize Customer Folder Service.
        
        Args:
            base_path: Base path for customer folders (defaults to database config)
        """
        if base_path:
            self.base_path = base_path
        else:
            # Get base path from database configuration
            self.base_path = self._get_base_path_from_db()
    
    def _get_base_path_from_db(self):
        """
        Get customer base path from database configuration.
        
        Returns:
            Base path from database, or default if not configured
        """
        try:
            from redash import models
            
            # Query teiid_config table
            result = models.db.session.execute(
                "SELECT customer_base_path FROM teiid_config WHERE id = 1"
            ).fetchone()
            
            if result and result[0]:
                logger.info("Using customer base path from database: {}".format(result[0]))
                return result[0]
            else:
                # Fallback to default
                default_path = '/opt/wildfly/teiidfiles/customers'
                logger.warning("No Teiid config found in database, using default: {}".format(default_path))
                return default_path
                
        except Exception as e:
            # Fallback to default if database query fails
            default_path = '/opt/wildfly/teiidfiles/customers'
            logger.warning("Failed to get base path from database: {}. Using default: {}".format(
                str(e), default_path
            ))
            return default_path
    
    def create_customer_folders(self, org_id):
        """
        Create folder structure for a customer organization.
        
        Creates folders atomically - if any step fails, logs error but continues.
        This ensures folders are created even if base path doesn't exist yet.
        
        Structure:
        /opt/wildfly/teiidfiles/customers/<org_id>/
        ├── vdb/        # VDB XML files
        └── uploads/    # Uploaded data files
        
        Args:
            org_id: Organization ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            org_path = os.path.join(self.base_path, str(org_id))
            vdb_path = os.path.join(org_path, 'vdb')
            uploads_path = os.path.join(org_path, 'uploads')
            
            logger.info('Creating customer folders for org_id: {}'.format(org_id))
            logger.info('  Base path: {}'.format(self.base_path))
            logger.info('  Org path: {}'.format(org_path))
            
            # Create directories (makedirs creates parent directories automatically)
            # Python 2.7 doesn't support exist_ok, so check first
            if not os.path.exists(vdb_path):
                os.makedirs(vdb_path, mode=0o750)
            if not os.path.exists(uploads_path):
                os.makedirs(uploads_path, mode=0o750)
            
            # Set permissions explicitly (in case folders already existed)
            try:
                os.chmod(org_path, 0o750)
                os.chmod(vdb_path, 0o750)
                os.chmod(uploads_path, 0o750)
            except Exception as perm_error:
                # Log but don't fail - permissions might already be correct
                logger.warning('Could not set permissions for org {}: {}'.format(
                    org_id, str(perm_error)
                ))
            
            logger.info('Successfully created customer folders for org_id: {}'.format(org_id))
            logger.info('  VDB folder: {}'.format(vdb_path))
            logger.info('  Uploads folder: {}'.format(uploads_path))
            
            return True
            
        except Exception as e:
            logger.error('Failed to create customer folders for org_id {}: {}'.format(
                org_id, str(e)
            ))
            logger.error('  Base path: {}'.format(self.base_path))
            logger.error('  Attempted org path: {}'.format(os.path.join(self.base_path, str(org_id))))
            return False
    
    def get_vdb_folder(self, org_id):
        """
        Get VDB folder path for an organization.
        
        Args:
            org_id: Organization ID
            
        Returns:
            VDB folder path (e.g., '/opt/wildfly/teiidfiles/customers/5/vdb')
        """
        return os.path.join(self.base_path, str(org_id), 'vdb')
    
    def get_uploads_folder(self, org_id):
        """
        Get uploads folder path for an organization.
        
        Args:
            org_id: Organization ID
            
        Returns:
            Uploads folder path (e.g., '/opt/wildfly/teiidfiles/customers/5/uploads')
        """
        return os.path.join(self.base_path, str(org_id), 'uploads')
    
    def get_org_folder(self, org_id):
        """
        Get organization root folder path.
        
        Args:
            org_id: Organization ID
            
        Returns:
            Organization folder path (e.g., '/opt/wildfly/teiidfiles/customers/5')
        """
        return os.path.join(self.base_path, str(org_id))
    
    def folder_exists(self, org_id):
        """
        Check if customer folders exist for an organization.
        
        Args:
            org_id: Organization ID
            
        Returns:
            True if folders exist, False otherwise
        """
        org_path = os.path.join(self.base_path, str(org_id))
        vdb_path = os.path.join(org_path, 'vdb')
        uploads_path = os.path.join(org_path, 'uploads')
        
        return os.path.exists(org_path) and os.path.exists(vdb_path) and os.path.exists(uploads_path)
    
    def archive_customer_folders(self, org_id):
        """
        Archive customer folders without deleting them.
        
        This method is used during provisioning rollback to preserve
        customer data for audit purposes.
        
        Args:
            org_id: Organization ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            org_path = os.path.join(self.base_path, str(org_id))
            
            if not os.path.exists(org_path):
                logger.warning('Customer folder does not exist for org_id: {}'.format(org_id))
                return True
            
            # Archive to archived/<org_id>_<timestamp>
            archive_base = os.path.join(self.base_path, 'archived')
            archive_path = os.path.join(archive_base, 'org_{}_{}'.format(
                org_id, int(time.time())
            ))
            
            if not os.path.exists(archive_base):
                os.makedirs(archive_base, mode=0o750)
            
            shutil.move(org_path, archive_path)
            logger.info('Archived customer folders for org_id {} to {}'.format(
                org_id, archive_path
            ))
            
            return True
            
        except Exception as e:
            logger.error('Failed to archive customer folders for org_id {}: {}'.format(
                org_id, str(e)
            ))
            return False
    
    def delete_customer_folders(self, org_id, archive=True):
        """
        Delete customer folders, optionally archiving first.
        
        Args:
            org_id: Organization ID
            archive: If True, archive folders before deletion
            
        Returns:
            True if successful, False otherwise
        """
        try:
            org_path = os.path.join(self.base_path, str(org_id))
            
            if not os.path.exists(org_path):
                logger.warning('Customer folder does not exist for org_id: {}'.format(org_id))
                return True
            
            if archive:
                # Use the archive_customer_folders method
                return self.archive_customer_folders(org_id)
            else:
                shutil.rmtree(org_path)
                logger.info('Deleted customer folders for org_id: {}'.format(org_id))
            
            return True
            
        except Exception as e:
            logger.error('Failed to delete customer folders for org_id {}: {}'.format(
                org_id, str(e)
            ))
            return False
    
    def validate_file_path(self, org_id, file_path):
        """
        Validate that a file path is within the organization's folder.
        Prevents directory traversal attacks.
        
        Args:
            org_id: Organization ID
            file_path: File path to validate (relative or absolute)
            
        Returns:
            True if valid, False otherwise
            
        Example:
            >>> service = CustomerFolderService()
            >>> service.validate_file_path(5, 'data.xlsx')
            True
            >>> service.validate_file_path(5, '../../../etc/passwd')
            False
        """
        try:
            org_path = os.path.join(self.base_path, str(org_id))
            
            # Resolve the full path
            if os.path.isabs(file_path):
                full_path = os.path.realpath(file_path)
            else:
                full_path = os.path.realpath(os.path.join(org_path, file_path))
            
            # Check if resolved path is within org folder
            org_path_real = os.path.realpath(org_path)
            is_valid = full_path.startswith(org_path_real)
            
            if not is_valid:
                logger.warning('Invalid file path detected for org {}: {}'.format(
                    org_id, file_path
                ))
            
            return is_valid
            
        except Exception as e:
            logger.error('Error validating file path for org {}: {}'.format(
                org_id, str(e)
            ))
            return False
    
    def list_files(self, org_id, folder_type='uploads'):
        """
        List files in a customer folder.
        
        Args:
            org_id: Organization ID
            folder_type: 'vdb' or 'uploads'
            
        Returns:
            List of file names
        """
        try:
            if folder_type == 'vdb':
                folder_path = self.get_vdb_folder(org_id)
            elif folder_type == 'uploads':
                folder_path = self.get_uploads_folder(org_id)
            else:
                raise ValueError('Invalid folder_type: {}'.format(folder_type))
            
            if not os.path.exists(folder_path):
                return []
            
            files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
            return files
            
        except Exception as e:
            logger.error('Failed to list files for org {} in {}: {}'.format(
                org_id, folder_type, str(e)
            ))
            return []
    
    def get_folder_size(self, org_id):
        """
        Get total size of customer folders in bytes.
        
        Args:
            org_id: Organization ID
            
        Returns:
            Total size in bytes
        """
        try:
            org_path = os.path.join(self.base_path, str(org_id))
            
            if not os.path.exists(org_path):
                return 0
            
            total_size = 0
            for dirpath, dirnames, filenames in os.walk(org_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    total_size += os.path.getsize(filepath)
            
            return total_size
            
        except Exception as e:
            logger.error('Failed to get folder size for org {}: {}'.format(
                org_id, str(e)
            ))
            return 0
    
    def create_user_folders(self, org_id, user_id):
        """
        Create folder structure for a user.
        
        Creates:
        - /Customer/{org_id}/{user_id}/
        - /Customer/{org_id}/{user_id}/uploads/
        - /Customer/{org_id}/{user_id}/vdb/
        
        Args:
            org_id: Organization ID
            user_id: User ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            user_base_path = os.path.join(self.base_path, str(org_id), str(user_id))
            user_uploads_path = os.path.join(user_base_path, 'uploads')
            user_vdb_path = os.path.join(user_base_path, 'vdb')
            
            logger.info('Creating user folders for org_id: {}, user_id: {}'.format(org_id, user_id))
            logger.info('  User base path: {}'.format(user_base_path))
            
            # Create directories (Python 2.7 compatible)
            if not os.path.exists(user_uploads_path):
                os.makedirs(user_uploads_path, mode=0o750)
            if not os.path.exists(user_vdb_path):
                os.makedirs(user_vdb_path, mode=0o750)
            
            # Set permissions explicitly
            try:
                os.chmod(user_base_path, 0o750)
                os.chmod(user_uploads_path, 0o750)
                os.chmod(user_vdb_path, 0o750)
            except Exception as perm_error:
                logger.warning('Could not set permissions for user {} in org {}: {}'.format(
                    user_id, org_id, str(perm_error)
                ))
            
            logger.info('Successfully created user folders for org_id: {}, user_id: {}'.format(org_id, user_id))
            logger.info('  Uploads folder: {}'.format(user_uploads_path))
            logger.info('  VDB folder: {}'.format(user_vdb_path))
            
            return True
            
        except Exception as e:
            logger.error('Failed to create user folders for org_id {}, user_id {}: {}'.format(
                org_id, user_id, str(e)
            ))
            return False
    
    def create_shared_folders(self, org_id):
        """
        Create shared folder structure for an organization.
        
        Creates:
        - /Customer/{org_id}/shared/
        - /Customer/{org_id}/shared/uploads/
        - /Customer/{org_id}/shared/vdb/
        
        Args:
            org_id: Organization ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            shared_base_path = os.path.join(self.base_path, str(org_id), 'shared')
            shared_uploads_path = os.path.join(shared_base_path, 'uploads')
            shared_vdb_path = os.path.join(shared_base_path, 'vdb')
            
            logger.info('Creating shared folders for org_id: {}'.format(org_id))
            logger.info('  Shared base path: {}'.format(shared_base_path))
            
            # Create directories (Python 2.7 compatible)
            if not os.path.exists(shared_uploads_path):
                os.makedirs(shared_uploads_path, mode=0o755)
            if not os.path.exists(shared_vdb_path):
                os.makedirs(shared_vdb_path, mode=0o755)
            
            # Set permissions explicitly (0o755 for shared access)
            try:
                os.chmod(shared_base_path, 0o755)
                os.chmod(shared_uploads_path, 0o755)
                os.chmod(shared_vdb_path, 0o755)
            except Exception as perm_error:
                logger.warning('Could not set permissions for shared folders in org {}: {}'.format(
                    org_id, str(perm_error)
                ))
            
            logger.info('Successfully created shared folders for org_id: {}'.format(org_id))
            logger.info('  Shared uploads folder: {}'.format(shared_uploads_path))
            logger.info('  Shared VDB folder: {}'.format(shared_vdb_path))
            
            return True
            
        except Exception as e:
            logger.error('Failed to create shared folders for org_id {}: {}'.format(
                org_id, str(e)
            ))
            return False
    
    def get_user_uploads_folder(self, org_id, user_id):
        """
        Get path to user's uploads folder.
        
        Args:
            org_id: Organization ID
            user_id: User ID
            
        Returns:
            User uploads folder path (e.g., '/opt/wildfly/teiidfiles/customers/5/123/uploads')
        """
        return os.path.join(self.base_path, str(org_id), str(user_id), 'uploads')
    
    def get_user_vdb_folder(self, org_id, user_id):
        """
        Get path to user's VDB folder.
        
        Args:
            org_id: Organization ID
            user_id: User ID
            
        Returns:
            User VDB folder path (e.g., '/opt/wildfly/teiidfiles/customers/5/123/vdb')
        """
        return os.path.join(self.base_path, str(org_id), str(user_id), 'vdb')
    
    def get_shared_uploads_folder(self, org_id):
        """
        Get path to shared uploads folder.
        
        Args:
            org_id: Organization ID
            
        Returns:
            Shared uploads folder path (e.g., '/opt/wildfly/teiidfiles/customers/5/shared/uploads')
        """
        return os.path.join(self.base_path, str(org_id), 'shared', 'uploads')
    
    def get_shared_vdb_folder(self, org_id):
        """
        Get path to shared VDB folder.
        
        Args:
            org_id: Organization ID
            
        Returns:
            Shared VDB folder path (e.g., '/opt/wildfly/teiidfiles/customers/5/shared/vdb')
        """
        return os.path.join(self.base_path, str(org_id), 'shared', 'vdb')

    def archive_user_vdb_files(self, org_id, user_id):
        """
        Archive user VDB files and data sources when user is deleted.
        
        Creates archive folders and moves user's VDB and upload files to:
        - /Customer/{org_id}/{user_id}/vdb/archive/
        - /Customer/{org_id}/{user_id}/uploads/archive/
        
        Args:
            org_id: Organization ID
            user_id: User ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            user_vdb_folder = self.get_user_vdb_folder(org_id, user_id)
            user_uploads_folder = self.get_user_uploads_folder(org_id, user_id)
            
            logger.info('Archiving VDB files for user {} in org {}'.format(user_id, org_id))
            
            # Archive VDB files
            if os.path.exists(user_vdb_folder):
                vdb_archive_folder = os.path.join(user_vdb_folder, 'archive')
                if not os.path.exists(vdb_archive_folder):
                    os.makedirs(vdb_archive_folder, mode=0o750)
                
                # Move all VDB files to archive
                for filename in os.listdir(user_vdb_folder):
                    file_path = os.path.join(user_vdb_folder, filename)
                    if os.path.isfile(file_path):
                        archive_path = os.path.join(vdb_archive_folder, filename)
                        shutil.move(file_path, archive_path)
                        logger.info('Archived VDB file: {} -> {}'.format(file_path, archive_path))
            
            # Archive upload files
            if os.path.exists(user_uploads_folder):
                uploads_archive_folder = os.path.join(user_uploads_folder, 'archive')
                if not os.path.exists(uploads_archive_folder):
                    os.makedirs(uploads_archive_folder, mode=0o750)
                
                # Move all upload files to archive
                for filename in os.listdir(user_uploads_folder):
                    file_path = os.path.join(user_uploads_folder, filename)
                    if os.path.isfile(file_path):
                        archive_path = os.path.join(uploads_archive_folder, filename)
                        shutil.move(file_path, archive_path)
                        logger.info('Archived upload file: {} -> {}'.format(file_path, archive_path))
            
            logger.info('Successfully archived VDB files for user {} in org {}'.format(user_id, org_id))
            return True
            
        except Exception as e:
            logger.error('Failed to archive VDB files for user {} in org {}: {}'.format(
                user_id, org_id, str(e)
            ))
            return False
