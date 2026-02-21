"""
File Migration Service

Service for migrating datasource files between private and shared directories
during project sharing operations. Handles file copying, moving, validation,
and rollback operations.
"""

import os
import shutil
import logging
from datetime import datetime
from redash.services.exceptions import FileMigrationError, DiskSpaceError
from redash.utils.file_permissions import FilePermissionManager

logger = logging.getLogger(__name__)


class FileMigrationService:
    """
    Handles physical file movement between private and shared directories.
    
    Supports:
    - Moving files from user's private directory to shared directory
    - Moving files from shared directory back to user's private directory
    - Filename conflict resolution with timestamp appending
    - File validation and error handling
    - Rollback operations
    """
    
    def __init__(self, base_path=None):
        """
        Initialize File Migration Service.
        
        Args:
            base_path: Base path for customer folders (defaults to database config)
        """
        if base_path:
            self.base_path = base_path
        else:
            # Get base path from database configuration
            self.base_path = self._get_base_path_from_db()
    
    def _find_file_case_insensitive(self, file_path):
        """
        Find a file with case-insensitive matching.
        
        This handles cases where the database has the wrong case stored
        (e.g., upload_USERS.csv vs upload_users.csv).
        
        Args:
            file_path: The file path to find
            
        Returns:
            Actual file path if found, None otherwise
        """
        # First try exact match
        if os.path.exists(file_path):
            return file_path
        
        # Try case-insensitive match
        directory = os.path.dirname(file_path)
        filename = os.path.basename(file_path)
        
        if not os.path.exists(directory):
            return None
        
        # List all files in directory and compare case-insensitively
        try:
            for actual_filename in os.listdir(directory):
                if actual_filename.lower() == filename.lower():
                    actual_path = os.path.join(directory, actual_filename)
                    logger.info("Found file with different case: {} -> {}".format(
                        file_path, actual_path
                    ))
                    return actual_path
        except Exception as e:
            logger.error("Error searching for file: {}".format(str(e)))
        
        return None
    
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
    
    def move_to_shared(self, org_id, user_id, file_path):
        """
        Move a file from user's private directory to shared directory.
        
        This method copies the file to the shared directory (keeping the original
        as a backup) and handles filename conflicts by appending a timestamp.
        
        Args:
            org_id: Organization ID
            user_id: User ID (file owner)
            file_path: Current file path in private directory
        
        Returns:
            New file path in shared directory
            
        Raises:
            FileMigrationError: If file operation fails
        """
        try:
            # Validate source file exists
            if not os.path.exists(file_path):
                raise FileMigrationError("Source file not found: {}".format(file_path))
            
            # Validate source file is readable
            if not os.access(file_path, os.R_OK):
                raise FileMigrationError("Source file is not readable: {}".format(file_path))
            
            # Get filename
            filename = os.path.basename(file_path)
            
            # Construct shared directory path
            shared_dir = os.path.join(self.base_path, str(org_id), 'shared', 'uploads')
            
            # Create shared directory if it doesn't exist
            if not os.path.exists(shared_dir):
                FilePermissionManager.create_directory_with_permissions(shared_dir)
                logger.info("Created shared directory with permissions: {}".format(shared_dir))
            
            # Handle filename conflicts
            shared_path = os.path.join(shared_dir, filename)
            if os.path.exists(shared_path):
                # Append timestamp to make unique
                name, ext = os.path.splitext(filename)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = "{}_{}{}".format(name, timestamp, ext)
                shared_path = os.path.join(shared_dir, filename)
                logger.info("File conflict detected, using unique filename: {}".format(filename))
            
            # Copy file to shared directory
            logger.info("Copying file from {} to {}".format(file_path, shared_path))
            shutil.copy2(file_path, shared_path)
            
            # Verify copy succeeded
            if not os.path.exists(shared_path):
                raise FileMigrationError("Failed to copy file to {}".format(shared_path))
            
            # Verify file size matches
            source_size = os.path.getsize(file_path)
            dest_size = os.path.getsize(shared_path)
            if source_size != dest_size:
                # Cleanup failed copy
                os.remove(shared_path)
                raise FileMigrationError(
                    "File size mismatch after copy: source={}, dest={}".format(
                        source_size, dest_size
                    )
                )
            
            # Set appropriate permissions for shared access
            FilePermissionManager.set_file_permissions(shared_path)
            
            # Delete source file after successful copy and verification
            logger.info("Deleting source file after successful copy: {}".format(file_path))
            try:
                os.remove(file_path)
                logger.info("Successfully deleted source file: {}".format(file_path))
            except Exception as e:
                # Log warning but don't fail the migration if deletion fails
                # The file was successfully copied, which is the primary goal
                logger.warning("Failed to delete source file {}: {}".format(file_path, str(e)))
            
            logger.info("Successfully moved file to shared directory: {}".format(shared_path))
            return shared_path
            
        except FileMigrationError:
            raise
        except Exception as e:
            logger.error("Failed to move file to shared directory: {}".format(str(e)))
            raise FileMigrationError("Failed to move file to shared directory: {}".format(str(e)))
    
    def move_to_private(self, org_id, user_id, file_path):
        """
        Move a file from shared directory to user's private directory.
        
        This method moves the file from the shared directory back to the user's
        private directory. If the file already exists in the private directory,
        it uses the existing file and removes the shared copy.
        
        Args:
            org_id: Organization ID
            user_id: User ID (file owner)
            file_path: Current file path in shared directory
        
        Returns:
            New file path in private directory
            
        Raises:
            FileMigrationError: If file operation fails
        """
        try:
            # Try to find the file with case-insensitive matching
            actual_file_path = self._find_file_case_insensitive(file_path)
            if not actual_file_path:
                raise FileMigrationError("Source file not found: {}".format(file_path))
            
            # Use the actual file path found
            file_path = actual_file_path
            
            # Validate source file is readable
            if not os.access(file_path, os.R_OK):
                raise FileMigrationError("Source file is not readable: {}".format(file_path))
            
            # Get filename
            filename = os.path.basename(file_path)
            
            # Construct private directory path
            private_dir = os.path.join(self.base_path, str(org_id), str(user_id), 'uploads')
            
            # Create private directory if it doesn't exist
            if not os.path.exists(private_dir):
                os.makedirs(private_dir, mode=0o750)
                logger.info("Created private directory: {}".format(private_dir))
            
            # Construct private file path
            private_path = os.path.join(private_dir, filename)
            
            # If file already exists in private directory, use it
            if os.path.exists(private_path):
                logger.info("File already exists in private directory: {}".format(private_path))
                
                # Verify file size matches
                source_size = os.path.getsize(file_path)
                existing_size = os.path.getsize(private_path)
                if source_size == existing_size:
                    # Remove from shared directory
                    os.remove(file_path)
                    logger.info("Removed file from shared directory: {}".format(file_path))
                    return private_path
                else:
                    logger.warning(
                        "File size mismatch between shared and private: shared={}, private={}".format(
                            source_size, existing_size
                        )
                    )
                    # Continue with move operation to overwrite
            
            # Move file to private directory
            logger.info("Moving file from {} to {}".format(file_path, private_path))
            shutil.move(file_path, private_path)
            
            # Verify move succeeded
            if not os.path.exists(private_path):
                raise FileMigrationError("Failed to move file to {}".format(private_path))
            
            # Set appropriate permissions (read/write for owner only)
            os.chmod(private_path, 0o600)
            
            logger.info("Successfully moved file to private directory: {}".format(private_path))
            return private_path
            
        except FileMigrationError:
            raise
        except Exception as e:
            logger.error("Failed to move file to private directory: {}".format(str(e)))
            raise FileMigrationError("Failed to move file to private directory: {}".format(str(e)))
    
    def move_file(self, source_path, dest_path):
        """
        Generic file move operation for rollback.
        
        This method is used during rollback operations to restore files
        to their original locations.
        
        Args:
            source_path: Source file path
            dest_path: Destination file path
            
        Raises:
            FileMigrationError: If file operation fails
        """
        try:
            # Try to find the file with case-insensitive matching
            actual_source = self._find_file_case_insensitive(source_path)
            if not actual_source:
                raise FileMigrationError("Source file not found: {}".format(source_path))
            
            # Create destination directory if needed
            dest_dir = os.path.dirname(dest_path)
            if not os.path.exists(dest_dir):
                os.makedirs(dest_dir, mode=0o750)
                logger.info("Created destination directory: {}".format(dest_dir))
            
            # Move file
            logger.info("Moving file from {} to {}".format(source_path, dest_path))
            shutil.move(source_path, dest_path)
            
            # Verify move succeeded
            if not os.path.exists(dest_path):
                raise FileMigrationError("Failed to move file to {}".format(dest_path))
            
            logger.info("Successfully moved file: {}".format(dest_path))
            
        except FileMigrationError:
            raise
        except Exception as e:
            logger.error("Failed to move file: {}".format(str(e)))
            raise FileMigrationError("Failed to move file: {}".format(str(e)))
    
    def delete_file(self, file_path):
        """
        Delete a file.
        
        This method is used during rollback operations to clean up
        files that were created during a failed migration.
        
        Args:
            file_path: File path to delete
            
        Raises:
            FileMigrationError: If file operation fails
        """
        try:
            if os.path.exists(file_path):
                logger.info("Deleting file: {}".format(file_path))
                os.remove(file_path)
                logger.info("Successfully deleted file: {}".format(file_path))
            else:
                logger.warning("File does not exist, skipping deletion: {}".format(file_path))
                
        except Exception as e:
            logger.error("Failed to delete file {}: {}".format(file_path, str(e)))
            raise FileMigrationError("Failed to delete file: {}".format(str(e)))
    
    def validate_file_exists(self, file_path):
        """
        Validate that a file exists and is readable.
        
        Args:
            file_path: File path to validate
            
        Returns:
            True if file exists and is readable, False otherwise
        """
        try:
            if not os.path.exists(file_path):
                logger.warning("File does not exist: {}".format(file_path))
                return False
            
            if not os.path.isfile(file_path):
                logger.warning("Path is not a file: {}".format(file_path))
                return False
            
            if not os.access(file_path, os.R_OK):
                logger.warning("File is not readable: {}".format(file_path))
                return False
            
            return True
            
        except Exception as e:
            logger.error("Error validating file {}: {}".format(file_path, str(e)))
            return False
    
    def verify_destination_file(self, file_path, expected_size=None):
        """
        Verify that a destination file was created successfully.
        
        Args:
            file_path: File path to verify
            expected_size: Expected file size in bytes (optional)
            
        Returns:
            True if file exists and matches expected size, False otherwise
        """
        try:
            if not os.path.exists(file_path):
                logger.error("Destination file does not exist: {}".format(file_path))
                return False
            
            if not os.path.isfile(file_path):
                logger.error("Destination path is not a file: {}".format(file_path))
                return False
            
            if expected_size is not None:
                actual_size = os.path.getsize(file_path)
                if actual_size != expected_size:
                    logger.error(
                        "File size mismatch: expected={}, actual={}".format(
                            expected_size, actual_size
                        )
                    )
                    return False
            
            return True
            
        except Exception as e:
            logger.error("Error verifying destination file {}: {}".format(file_path, str(e)))
            return False
    
    def get_file_size(self, file_path):
        """
        Get the size of a file in bytes.
        
        Args:
            file_path: File path
            
        Returns:
            File size in bytes, or None if file doesn't exist
        """
        try:
            if os.path.exists(file_path):
                return os.path.getsize(file_path)
            else:
                return None
        except Exception as e:
            logger.error("Error getting file size for {}: {}".format(file_path, str(e)))
            return None
    
    def check_disk_space(self, directory, required_bytes):
        """
        Check if there is sufficient disk space available.
        
        Args:
            directory: Directory to check
            required_bytes: Required space in bytes
            
        Returns:
            True if sufficient space is available, False otherwise
        """
        try:
            import platform
            
            if platform.system() == 'Windows':
                import ctypes
                free_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    ctypes.c_wchar_p(directory),
                    None,
                    None,
                    ctypes.pointer(free_bytes)
                )
                available = free_bytes.value
            else:
                # Unix/Linux
                stat = os.statvfs(directory)
                available = stat.f_bavail * stat.f_frsize
            
            if available < required_bytes:
                logger.error(
                    "Insufficient disk space: required={}, available={}".format(
                        required_bytes, available
                    )
                )
                return False
            
            return True
            
        except Exception as e:
            logger.error("Error checking disk space for {}: {}".format(directory, str(e)))
            # Return True to allow operation to proceed (fail later if disk is full)
            return True
    
    def handle_permission_error(self, file_path, operation):
        """
        Handle permission errors during file operations.
        
        Args:
            file_path: File path that caused the error
            operation: Operation that failed (e.g., 'read', 'write', 'delete')
            
        Returns:
            Error message string
        """
        error_msg = "Permission denied for {} operation on file: {}".format(
            operation, file_path
        )
        logger.error(error_msg)
        
        # Log additional diagnostic information
        try:
            if os.path.exists(file_path):
                stat_info = os.stat(file_path)
                logger.error("File permissions: {}".format(oct(stat_info.st_mode)))
                logger.error("File owner UID: {}".format(stat_info.st_uid))
                logger.error("File owner GID: {}".format(stat_info.st_gid))
        except Exception as e:
            logger.error("Could not get file stat info: {}".format(str(e)))
        
        return error_msg
