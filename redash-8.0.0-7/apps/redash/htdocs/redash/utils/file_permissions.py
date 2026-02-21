"""
File Permissions Utility

Automatically sets correct permissions on files and directories
to ensure Redash can read/write VDB files and upload directories.

This prevents permission issues when new organizations, users, or VDB files are created.
"""

import os
import logging
import grp
import pwd

logger = logging.getLogger(__name__)


class FilePermissionManager(object):
    """
    Manages file and directory permissions for VDB files and upload directories.
    
    Ensures that:
    - Redash can read/write VDB files
    - Wildfly can read/write VDB files
    - Both services can access shared directories
    """
    
    # Default permissions
    FILE_MODE = 0o664  # rw-rw-r-- (owner and group can write)
    DIR_MODE = 0o775   # rwxrwxr-x (owner and group can write/execute)
    
    # Default group for shared access
    SHARED_GROUP = 'wildfly'
    
    @classmethod
    def set_file_permissions(cls, file_path, mode=None, group=None):
        """
        Set permissions on a file to allow shared access.
        
        Args:
            file_path (str): Path to the file
            mode (int, optional): Permission mode (default: 0o664)
            group (str, optional): Group name (default: 'wildfly')
            
        Returns:
            bool: True if successful, False otherwise
        """
        if mode is None:
            mode = cls.FILE_MODE
        if group is None:
            group = cls.SHARED_GROUP
            
        try:
            # Check if file exists
            if not os.path.exists(file_path):
                logger.warning("File does not exist: {}".format(file_path))
                return False
            
            # Set file permissions
            os.chmod(file_path, mode)
            logger.debug("Set file permissions {} on: {}".format(oct(mode), file_path))
            
            # Set group ownership
            try:
                gid = grp.getgrnam(group).gr_gid
                os.chown(file_path, -1, gid)  # -1 means don't change owner, only group
                logger.debug("Set group '{}' on: {}".format(group, file_path))
            except KeyError:
                logger.warning("Group '{}' does not exist, skipping group ownership".format(group))
            except OSError as e:
                logger.warning("Failed to set group ownership on {}: {}".format(file_path, str(e)))
            
            return True
            
        except OSError as e:
            logger.error("Failed to set permissions on {}: {}".format(file_path, str(e)))
            return False
    
    @classmethod
    def set_directory_permissions(cls, dir_path, mode=None, group=None, recursive=False):
        """
        Set permissions on a directory to allow shared access.
        
        Args:
            dir_path (str): Path to the directory
            mode (int, optional): Permission mode (default: 0o775)
            group (str, optional): Group name (default: 'wildfly')
            recursive (bool): If True, apply to all subdirectories and files
            
        Returns:
            bool: True if successful, False otherwise
        """
        if mode is None:
            mode = cls.DIR_MODE
        if group is None:
            group = cls.SHARED_GROUP
            
        try:
            # Check if directory exists
            if not os.path.exists(dir_path):
                logger.warning("Directory does not exist: {}".format(dir_path))
                return False
            
            # Set directory permissions
            os.chmod(dir_path, mode)
            logger.debug("Set directory permissions {} on: {}".format(oct(mode), dir_path))
            
            # Set group ownership
            try:
                gid = grp.getgrnam(group).gr_gid
                os.chown(dir_path, -1, gid)
                logger.debug("Set group '{}' on: {}".format(group, dir_path))
            except KeyError:
                logger.warning("Group '{}' does not exist, skipping group ownership".format(group))
            except OSError as e:
                logger.warning("Failed to set group ownership on {}: {}".format(dir_path, str(e)))
            
            # Recursively set permissions if requested
            if recursive:
                for root, dirs, files in os.walk(dir_path):
                    # Set permissions on subdirectories
                    for dir_name in dirs:
                        subdir_path = os.path.join(root, dir_name)
                        cls.set_directory_permissions(subdir_path, mode, group, recursive=False)
                    
                    # Set permissions on files
                    for file_name in files:
                        file_path = os.path.join(root, file_name)
                        cls.set_file_permissions(file_path, cls.FILE_MODE, group)
            
            return True
            
        except OSError as e:
            logger.error("Failed to set permissions on {}: {}".format(dir_path, str(e)))
            return False
    
    @classmethod
    def ensure_vdb_file_permissions(cls, vdb_file_path):
        """
        Ensure VDB file has correct permissions for shared access.
        
        This should be called after creating or modifying a VDB file.
        
        Args:
            vdb_file_path (str): Path to the VDB XML file
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.info("Ensuring VDB file permissions: {}".format(vdb_file_path))
        return cls.set_file_permissions(vdb_file_path)
    
    @classmethod
    def ensure_upload_directory_permissions(cls, upload_dir_path):
        """
        Ensure upload directory has correct permissions for shared access.
        
        This should be called after creating a new upload directory.
        
        Args:
            upload_dir_path (str): Path to the upload directory
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.info("Ensuring upload directory permissions: {}".format(upload_dir_path))
        return cls.set_directory_permissions(upload_dir_path, recursive=False)
    
    @classmethod
    def ensure_org_directory_permissions(cls, org_dir_path):
        """
        Ensure organization directory and all subdirectories have correct permissions.
        
        This should be called after creating a new organization.
        
        Args:
            org_dir_path (str): Path to the organization directory
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.info("Ensuring organization directory permissions: {}".format(org_dir_path))
        return cls.set_directory_permissions(org_dir_path, recursive=True)
    
    @classmethod
    def ensure_user_directory_permissions(cls, user_dir_path):
        """
        Ensure user directory and all subdirectories have correct permissions.
        
        This should be called after creating a new user directory.
        
        Args:
            user_dir_path (str): Path to the user directory
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.info("Ensuring user directory permissions: {}".format(user_dir_path))
        return cls.set_directory_permissions(user_dir_path, recursive=True)
    
    @classmethod
    def create_directory_with_permissions(cls, dir_path, mode=None, group=None):
        """
        Create a directory with correct permissions.
        
        Args:
            dir_path (str): Path to the directory to create
            mode (int, optional): Permission mode (default: 0o775)
            group (str, optional): Group name (default: 'wildfly')
            
        Returns:
            bool: True if successful, False otherwise
        """
        if mode is None:
            mode = cls.DIR_MODE
        if group is None:
            group = cls.SHARED_GROUP
            
        try:
            # Create directory if it doesn't exist
            if not os.path.exists(dir_path):
                os.makedirs(dir_path, mode)
                logger.info("Created directory with permissions {}: {}".format(oct(mode), dir_path))
            
            # Set group ownership
            try:
                gid = grp.getgrnam(group).gr_gid
                os.chown(dir_path, -1, gid)
                logger.debug("Set group '{}' on: {}".format(group, dir_path))
            except KeyError:
                logger.warning("Group '{}' does not exist, skipping group ownership".format(group))
            except OSError as e:
                logger.warning("Failed to set group ownership on {}: {}".format(dir_path, str(e)))
            
            return True
            
        except OSError as e:
            logger.error("Failed to create directory {}: {}".format(dir_path, str(e)))
            return False
