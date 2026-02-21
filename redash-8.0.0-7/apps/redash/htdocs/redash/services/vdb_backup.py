"""
VDB Backup Service

Service for creating and managing backups of VDB configuration files before
migration operations. Provides backup creation, retention management, and
restore functionality.

Requirements: 23.1-23.5
"""

import os
import shutil
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class VDBBackupService(object):
    """
    Service for creating and managing VDB configuration backups.
    
    This service handles:
    - Creating backups of VDB files before migration
    - Managing backup retention (30 days)
    - Restoring VDB files from backup
    - Cleaning up old backups
    
    Requirements: 23.1-23.5
    """
    
    def __init__(self, base_path=None):
        """
        Initialize VDB Backup Service.
        
        Args:
            base_path: Base path for customer folders (defaults to /opt/wildfly/teiidfiles/customers)
        """
        if base_path:
            self.base_path = base_path
        else:
            self.base_path = self._get_base_path_from_db()
        
        self.retention_days = 30  # Requirement 23.4
    
    def _get_base_path_from_db(self):
        """
        Get customer base path from database configuration.
        
        Returns:
            Base path from database, or default if not configured
        """
        default_path = '/opt/wildfly/teiidfiles/customers'
        
        try:
            import os
            from redash import models
            
            # First try environment variable (most reliable)
            env_path = os.environ.get('TEIID_CUSTOMER_BASE_PATH')
            if env_path:
                logger.info("Using TEIID_CUSTOMER_BASE_PATH from environment: {}".format(env_path))
                return env_path
            
            # Query teiid_config table
            result = models.db.session.execute(
                "SELECT customer_base_path FROM teiid_config WHERE id = 1"
            ).fetchone()
            
            if result and result[0]:
                logger.info("Using customer base path from database: {}".format(result[0]))
                return result[0]
            else:
                # Fallback to default
                logger.warning("No Teiid config found in database, using default: {}".format(default_path))
                return default_path
                
        except Exception as e:
            # Rollback to clear any failed transaction state
            try:
                from redash import models
                models.db.session.rollback()
            except:
                pass
            # Fallback to default if database query fails
            logger.warning("Failed to get base path from database: {}. Using default: {}".format(
                str(e), default_path
            ))
            return default_path
    
    def create_backup(self, vdb_file_path, org_id, vdb_type='private', user_id=None):
        """
        Create a backup copy of a VDB configuration file.
        
        This method creates a timestamped backup of the VDB file in the
        organization's backup directory. The backup can be used for rollback
        if migration fails.
        
        Requirements: 23.1, 23.2, 23.3
        
        Args:
            vdb_file_path (str): Path to the VDB file to backup
            org_id (int): Organization ID
            vdb_type (str): Type of VDB ('private' or 'shared')
            user_id (int): User ID (required for private VDBs)
            
        Returns:
            str: Path to the backup file
            
        Raises:
            FileNotFoundError: If VDB file does not exist
            IOError: If backup creation fails
        """
        # Validate VDB file exists
        if not os.path.exists(vdb_file_path):
            raise FileNotFoundError("VDB file not found: {}".format(vdb_file_path))
        
        # Get backup directory path (Requirement 23.3)
        backup_dir = self._get_backup_directory(org_id)
        
        # Create backup directory if it doesn't exist
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir, mode=0o755)
            logger.info("Created backup directory: {}".format(backup_dir))
        
        # Construct backup file path with timestamp (Requirement 23.3)
        backup_path = self.get_backup_path(vdb_file_path, org_id, vdb_type, user_id)
        
        try:
            # Copy VDB file to backup location (Requirement 23.1, 23.2)
            shutil.copy2(vdb_file_path, backup_path)
            
            # Verify backup was created successfully
            if not os.path.exists(backup_path):
                raise IOError("Backup file was not created: {}".format(backup_path))
            
            logger.info("Created VDB backup: {} -> {}".format(vdb_file_path, backup_path))
            
            # Clean up old backups (Requirement 23.4)
            self._cleanup_old_backups(backup_dir)
            
            return backup_path
            
        except Exception as e:
            logger.error("Failed to create VDB backup: {}".format(str(e)))
            raise IOError("Failed to create VDB backup: {}".format(str(e)))
    
    def get_backup_path(self, vdb_file_path, org_id, vdb_type='private', user_id=None):
        """
        Construct the backup file path for a VDB file.
        
        The backup path includes:
        - Organization backup directory
        - VDB type (private/shared)
        - User ID (for private VDBs)
        - Original filename
        - Timestamp
        
        Requirements: 23.3
        
        Args:
            vdb_file_path (str): Path to the VDB file
            org_id (int): Organization ID
            vdb_type (str): Type of VDB ('private' or 'shared')
            user_id (int): User ID (required for private VDBs)
            
        Returns:
            str: Backup file path
        """
        # Get backup directory
        backup_dir = self._get_backup_directory(org_id)
        
        # Get filename from VDB path
        vdb_filename = os.path.basename(vdb_file_path)
        
        # Generate timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Construct backup filename
        if vdb_type == 'private' and user_id:
            backup_filename = "user_{}_{}_{}.backup".format(user_id, timestamp, vdb_filename)
        else:
            backup_filename = "shared_{}_{}.backup".format(timestamp, vdb_filename)
        
        # Construct full backup path
        backup_path = os.path.join(backup_dir, backup_filename)
        
        return backup_path
    
    def restore_from_backup(self, backup_path, target_path):
        """
        Restore a VDB file from backup.
        
        This method copies a backup file back to its original location,
        overwriting the current VDB file. This is used for rollback when
        migration fails.
        
        Requirements: 23.5
        
        Args:
            backup_path (str): Path to the backup file
            target_path (str): Path where VDB should be restored
            
        Raises:
            FileNotFoundError: If backup file does not exist
            IOError: If restore fails
        """
        # Validate backup file exists
        if not os.path.exists(backup_path):
            raise FileNotFoundError("Backup file not found: {}".format(backup_path))
        
        # Validate backup file (Requirement 23.5)
        if not self._validate_backup(backup_path):
            raise IOError("Backup file is invalid or corrupted: {}".format(backup_path))
        
        try:
            # Create target directory if it doesn't exist
            target_dir = os.path.dirname(target_path)
            if not os.path.exists(target_dir):
                os.makedirs(target_dir, mode=0o755)
            
            # Copy backup to target location
            shutil.copy2(backup_path, target_path)
            
            # Verify restore succeeded
            if not os.path.exists(target_path):
                raise IOError("Restore failed: target file not created")
            
            logger.info("Restored VDB from backup: {} -> {}".format(backup_path, target_path))
            
        except Exception as e:
            logger.error("Failed to restore VDB from backup: {}".format(str(e)))
            raise IOError("Failed to restore VDB from backup: {}".format(str(e)))
    
    def cleanup_old_backups(self, org_id):
        """
        Clean up backups older than retention period.
        
        This method removes backup files that are older than the configured
        retention period (30 days by default).
        
        Requirements: 23.4
        
        Args:
            org_id (int): Organization ID
            
        Returns:
            int: Number of backups deleted
        """
        backup_dir = self._get_backup_directory(org_id)
        
        if not os.path.exists(backup_dir):
            logger.debug("Backup directory does not exist: {}".format(backup_dir))
            return 0
        
        return self._cleanup_old_backups(backup_dir)
    
    def _get_backup_directory(self, org_id):
        """
        Get the backup directory path for an organization.
        
        Requirements: 23.3
        
        Args:
            org_id (int): Organization ID
            
        Returns:
            str: Backup directory path
        """
        return os.path.join(self.base_path, str(org_id), 'vdb', 'backup')
    
    def _cleanup_old_backups(self, backup_dir):
        """
        Remove backup files older than retention period.
        
        Requirements: 23.4
        
        Args:
            backup_dir (str): Path to backup directory
            
        Returns:
            int: Number of backups deleted
        """
        if not os.path.exists(backup_dir):
            return 0
        
        deleted_count = 0
        cutoff_date = datetime.now() - timedelta(days=self.retention_days)
        
        try:
            # Iterate through backup files
            for filename in os.listdir(backup_dir):
                if not filename.endswith('.backup'):
                    continue
                
                file_path = os.path.join(backup_dir, filename)
                
                # Get file modification time
                file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                
                # Delete if older than retention period
                if file_mtime < cutoff_date:
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                        logger.debug("Deleted old backup: {}".format(file_path))
                    except Exception as e:
                        logger.warning("Failed to delete old backup {}: {}".format(
                            file_path, str(e)
                        ))
            
            if deleted_count > 0:
                logger.info("Cleaned up {} old backups from {}".format(
                    deleted_count, backup_dir
                ))
            
        except Exception as e:
            logger.error("Failed to cleanup old backups: {}".format(str(e)))
        
        return deleted_count
    
    def _validate_backup(self, backup_path):
        """
        Validate that a backup file is valid.
        
        This performs basic validation to ensure the backup file:
        - Exists
        - Is not empty
        - Has valid XML structure (for VDB files)
        
        Requirements: 23.5
        
        Args:
            backup_path (str): Path to backup file
            
        Returns:
            bool: True if backup is valid, False otherwise
        """
        try:
            # Check file exists
            if not os.path.exists(backup_path):
                return False
            
            # Check file is not empty
            if os.path.getsize(backup_path) == 0:
                logger.warning("Backup file is empty: {}".format(backup_path))
                return False
            
            # Try to parse as XML (basic validation)
            import xml.etree.ElementTree as ET
            try:
                ET.parse(backup_path)
            except ET.ParseError as e:
                logger.warning("Backup file has invalid XML: {}".format(backup_path))
                return False
            
            return True
            
        except Exception as e:
            logger.error("Failed to validate backup: {}".format(str(e)))
            return False