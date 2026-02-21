"""
Data Migration Exception Classes

Custom exception classes for data migration operations.
Provides specific error types for different failure scenarios.

Requirements: 16.5, 16.6, 24.6
"""


class DataMigrationError(Exception):
    """
    Base exception for data migration errors.
    
    This is the parent class for all data migration-related exceptions.
    It provides a common interface for catching any migration error.
    
    Requirements: 16.5, 16.6
    """
    
    def __init__(self, message, details=None):
        """
        Initialize DataMigrationError.
        
        Args:
            message (str): Error message
            details (dict): Optional dictionary with additional error details
        """
        super(DataMigrationError, self).__init__(message)
        self.message = message
        self.details = details or {}
    
    def __str__(self):
        """Return string representation of the error."""
        if self.details:
            return "{}: {}".format(self.message, self.details)
        return self.message
    
    def to_dict(self):
        """
        Convert error to dictionary for API responses.
        
        Returns:
            dict: Error information
        """
        return {
            'error_type': self.__class__.__name__,
            'message': self.message,
            'details': self.details
        }


class FileMigrationError(DataMigrationError):
    """
    Exception raised when file migration operations fail.
    
    This exception is raised for errors during:
    - File copying between directories
    - File moving operations
    - File validation failures
    - Permission errors
    - Disk space issues
    
    Requirements: 16.5, 16.6, 24.6
    """
    
    def __init__(self, message, file_path=None, operation=None, details=None):
        """
        Initialize FileMigrationError.
        
        Args:
            message (str): Error message
            file_path (str): Path to the file that caused the error
            operation (str): Operation that failed (e.g., 'copy', 'move', 'delete')
            details (dict): Optional dictionary with additional error details
        """
        error_details = details or {}
        if file_path:
            error_details['file_path'] = file_path
        if operation:
            error_details['operation'] = operation
        
        super(FileMigrationError, self).__init__(message, error_details)
        self.file_path = file_path
        self.operation = operation


class VDBMigrationError(DataMigrationError):
    """
    Exception raised when VDB configuration migration fails.
    
    This exception is raised for errors during:
    - VDB XML parsing
    - Foreign table extraction/insertion
    - View extraction/insertion
    - DDL transformation
    - VDB file writing
    
    Requirements: 16.5, 16.6, 24.6
    """
    
    def __init__(self, message, vdb_path=None, operation=None, details=None):
        """
        Initialize VDBMigrationError.
        
        Args:
            message (str): Error message
            vdb_path (str): Path to the VDB file that caused the error
            operation (str): Operation that failed (e.g., 'extract', 'insert', 'parse')
            details (dict): Optional dictionary with additional error details
        """
        error_details = details or {}
        if vdb_path:
            error_details['vdb_path'] = vdb_path
        if operation:
            error_details['operation'] = operation
        
        super(VDBMigrationError, self).__init__(message, error_details)
        self.vdb_path = vdb_path
        self.operation = operation


class ProjectNotFoundError(DataMigrationError):
    """
    Exception raised when a project cannot be found.
    
    This exception is raised when attempting to migrate a project
    that does not exist in the database.
    
    Requirements: 16.5, 16.6
    """
    
    def __init__(self, message, project_id=None, details=None):
        """
        Initialize ProjectNotFoundError.
        
        Args:
            message (str): Error message
            project_id (int): ID of the project that was not found
            details (dict): Optional dictionary with additional error details
        """
        error_details = details or {}
        if project_id:
            error_details['project_id'] = project_id
        
        super(ProjectNotFoundError, self).__init__(message, error_details)
        self.project_id = project_id


class VDBNotFoundError(DataMigrationError):
    """
    Exception raised when a VDB cannot be found.
    
    This exception is raised when:
    - A user's private VDB does not exist
    - An organization's shared VDB does not exist
    - A VDB file cannot be located on the filesystem
    
    Requirements: 16.5, 16.6
    """
    
    def __init__(self, message, vdb_id=None, vdb_type=None, details=None):
        """
        Initialize VDBNotFoundError.
        
        Args:
            message (str): Error message
            vdb_id (str): ID of the VDB that was not found
            vdb_type (str): Type of VDB ('private' or 'shared')
            details (dict): Optional dictionary with additional error details
        """
        error_details = details or {}
        if vdb_id:
            error_details['vdb_id'] = vdb_id
        if vdb_type:
            error_details['vdb_type'] = vdb_type
        
        super(VDBNotFoundError, self).__init__(message, error_details)
        self.vdb_id = vdb_id
        self.vdb_type = vdb_type


class MigrationRollbackError(DataMigrationError):
    """
    Exception raised when migration rollback fails.
    
    This is a critical error that indicates the system may be in an
    inconsistent state. It requires immediate attention and manual
    intervention.
    
    Requirements: 16.5, 16.6, 24.6
    """
    
    def __init__(self, message, original_error=None, rollback_error=None, details=None):
        """
        Initialize MigrationRollbackError.
        
        Args:
            message (str): Error message
            original_error (Exception): The original error that triggered rollback
            rollback_error (Exception): The error that occurred during rollback
            details (dict): Optional dictionary with additional error details
        """
        error_details = details or {}
        if original_error:
            error_details['original_error'] = str(original_error)
        if rollback_error:
            error_details['rollback_error'] = str(rollback_error)
        
        super(MigrationRollbackError, self).__init__(message, error_details)
        self.original_error = original_error
        self.rollback_error = rollback_error


class InsufficientPermissionsError(DataMigrationError):
    """
    Exception raised when user lacks permissions for migration.
    
    This exception is raised when:
    - User is not the project owner
    - User lacks file system permissions
    - User lacks database permissions
    
    Requirements: 16.6
    """
    
    def __init__(self, message, user_id=None, required_permission=None, details=None):
        """
        Initialize InsufficientPermissionsError.
        
        Args:
            message (str): Error message
            user_id (int): ID of the user who lacks permissions
            required_permission (str): The permission that is required
            details (dict): Optional dictionary with additional error details
        """
        error_details = details or {}
        if user_id:
            error_details['user_id'] = user_id
        if required_permission:
            error_details['required_permission'] = required_permission
        
        super(InsufficientPermissionsError, self).__init__(message, error_details)
        self.user_id = user_id
        self.required_permission = required_permission


class MigrationInProgressError(DataMigrationError):
    """
    Exception raised when attempting to start a migration that is already in progress.
    
    This exception prevents concurrent migrations for the same project,
    which could lead to race conditions and data corruption.
    
    Requirements: 22.1, 22.2, 22.3
    """
    
    def __init__(self, message, project_id=None, existing_migration_id=None, details=None):
        """
        Initialize MigrationInProgressError.
        
        Args:
            message (str): Error message
            project_id (int): ID of the project with migration in progress
            existing_migration_id (int): ID of the existing migration
            details (dict): Optional dictionary with additional error details
        """
        error_details = details or {}
        if project_id:
            error_details['project_id'] = project_id
        if existing_migration_id:
            error_details['existing_migration_id'] = existing_migration_id
        
        super(MigrationInProgressError, self).__init__(message, error_details)
        self.project_id = project_id
        self.existing_migration_id = existing_migration_id


class VDBRedeploymentError(DataMigrationError):
    """
    Exception raised when VDB redeployment fails.
    
    This exception is raised when:
    - VDB redeployment times out
    - VDB fails to start after redeployment
    - VDB redeployment service is unavailable
    
    Requirements: 6.5, 16.5, 16.6
    """
    
    def __init__(self, message, vdb_id=None, vdb_type=None, details=None):
        """
        Initialize VDBRedeploymentError.
        
        Args:
            message (str): Error message
            vdb_id (str): ID of the VDB that failed to redeploy
            vdb_type (str): Type of VDB ('private' or 'shared')
            details (dict): Optional dictionary with additional error details
        """
        error_details = details or {}
        if vdb_id:
            error_details['vdb_id'] = vdb_id
        if vdb_type:
            error_details['vdb_type'] = vdb_type
        
        super(VDBRedeploymentError, self).__init__(message, error_details)
        self.vdb_id = vdb_id
        self.vdb_type = vdb_type


class DiskSpaceError(FileMigrationError):
    """
    Exception raised when there is insufficient disk space for migration.
    
    This exception is raised when:
    - Destination directory has insufficient space
    - File copy would exceed disk quota
    
    Requirements: 16.5, 16.6
    """
    
    def __init__(self, message, required_bytes=None, available_bytes=None, details=None):
        """
        Initialize DiskSpaceError.
        
        Args:
            message (str): Error message
            required_bytes (int): Required disk space in bytes
            available_bytes (int): Available disk space in bytes
            details (dict): Optional dictionary with additional error details
        """
        error_details = details or {}
        if required_bytes:
            error_details['required_bytes'] = required_bytes
        if available_bytes:
            error_details['available_bytes'] = available_bytes
        
        super(DiskSpaceError, self).__init__(
            message,
            operation='disk_space_check',
            details=error_details
        )
        self.required_bytes = required_bytes
        self.available_bytes = available_bytes
