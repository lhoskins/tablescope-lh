"""
Data Migration Logging Utility

Provides comprehensive logging for data migration operations.
Logs migration start/completion, file operations, VDB operations,
errors with stack traces, and rollback operations.

Requirements: 24.1, 24.2, 24.3, 24.4, 24.5, 24.6, 24.7
"""

import logging
import traceback
import sys
from datetime import datetime

logger = logging.getLogger(__name__)


class MigrationLogger(object):
    """
    Comprehensive logging utility for data migration operations.
    
    This class provides structured logging for all migration operations,
    including start/completion, file operations, VDB operations, errors,
    and rollback operations.
    
    Requirements: 24.1-24.7
    """
    
    def __init__(self, project_id, migration_type, user_id):
        """
        Initialize Migration Logger.
        
        Args:
            project_id (int): ID of the project being migrated
            migration_type (str): Type of migration ('share' or 'unshare')
            user_id (int): ID of the user initiating the migration
        """
        self.project_id = project_id
        self.migration_type = migration_type
        self.user_id = user_id
        self.start_time = datetime.now()
        self.operation_count = 0
    
    def log_migration_start(self):
        """
        Log the start of a migration operation.
        
        Requirements: 24.1
        """
        logger.info(
            "[MIGRATION START] Project: {}, Type: {}, User: {}, Time: {}".format(
                self.project_id,
                self.migration_type,
                self.user_id,
                self.start_time.isoformat()
            )
        )
        logger.info(
            "[MIGRATION START] Starting {} migration for project {}".format(
                self.migration_type, self.project_id
            )
        )
    
    def log_migration_completion(self, datasources_count, queries_count):
        """
        Log the successful completion of a migration operation.
        
        Requirements: 24.5
        
        Args:
            datasources_count (int): Number of datasources migrated
            queries_count (int): Number of queries migrated
        """
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()
        
        logger.info(
            "[MIGRATION COMPLETE] Project: {}, Type: {}, Duration: {:.2f}s".format(
                self.project_id,
                self.migration_type,
                duration
            )
        )
        logger.info(
            "[MIGRATION COMPLETE] Migrated {} datasources and {} queries".format(
                datasources_count, queries_count
            )
        )
        logger.info(
            "[MIGRATION COMPLETE] Total operations: {}".format(self.operation_count)
        )
    
    def log_file_operation(self, operation, source_path, dest_path=None, success=True, error=None):
        """
        Log a file operation (copy, move, delete).
        
        Requirements: 24.2
        
        Args:
            operation (str): Operation type ('copy', 'move', 'delete')
            source_path (str): Source file path
            dest_path (str): Destination file path (optional)
            success (bool): Whether the operation succeeded
            error (Exception): Error if operation failed (optional)
        """
        self.operation_count += 1
        
        if success:
            if dest_path:
                logger.info(
                    "[FILE {}] {} -> {}".format(
                        operation.upper(), source_path, dest_path
                    )
                )
            else:
                logger.info(
                    "[FILE {}] {}".format(operation.upper(), source_path)
                )
        else:
            if dest_path:
                logger.error(
                    "[FILE {} FAILED] {} -> {}: {}".format(
                        operation.upper(), source_path, dest_path, str(error)
                    )
                )
            else:
                logger.error(
                    "[FILE {} FAILED] {}: {}".format(
                        operation.upper(), source_path, str(error)
                    )
                )
    
    def log_vdb_operation(self, operation, vdb_type, entity_name=None, success=True, error=None):
        """
        Log a VDB operation (extract, insert, remove, redeploy).
        
        Requirements: 24.3, 24.4
        
        Args:
            operation (str): Operation type ('extract', 'insert', 'remove', 'redeploy')
            vdb_type (str): VDB type ('private' or 'shared')
            entity_name (str): Name of entity (table/view) being operated on (optional)
            success (bool): Whether the operation succeeded
            error (Exception): Error if operation failed (optional)
        """
        self.operation_count += 1
        
        if success:
            if entity_name:
                logger.info(
                    "[VDB {}] {} VDB: {}".format(
                        operation.upper(), vdb_type, entity_name
                    )
                )
            else:
                logger.info(
                    "[VDB {}] {} VDB".format(operation.upper(), vdb_type)
                )
        else:
            if entity_name:
                logger.error(
                    "[VDB {} FAILED] {} VDB: {}: {}".format(
                        operation.upper(), vdb_type, entity_name, str(error)
                    )
                )
            else:
                logger.error(
                    "[VDB {} FAILED] {} VDB: {}".format(
                        operation.upper(), vdb_type, str(error)
                    )
                )
    
    def log_error(self, error, context=None):
        """
        Log an error with full stack trace.
        
        Requirements: 24.6
        
        Args:
            error (Exception): The error that occurred
            context (str): Additional context about where the error occurred (optional)
        """
        error_type = type(error).__name__
        error_message = str(error)
        
        if context:
            logger.error(
                "[MIGRATION ERROR] Project: {}, Context: {}, Error: {} - {}".format(
                    self.project_id, context, error_type, error_message
                )
            )
        else:
            logger.error(
                "[MIGRATION ERROR] Project: {}, Error: {} - {}".format(
                    self.project_id, error_type, error_message
                )
            )
        
        # Log full stack trace
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if exc_traceback:
            stack_trace = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            logger.error("[STACK TRACE]\n{}".format(stack_trace))
        else:
            # If no current exception, try to get traceback from error object
            try:
                stack_trace = ''.join(traceback.format_tb(error.__traceback__))
                if stack_trace:
                    logger.error("[STACK TRACE]\n{}".format(stack_trace))
            except AttributeError:
                pass
    
    def log_rollback_start(self, reason=None):
        """
        Log the start of a rollback operation.
        
        Requirements: 24.7
        
        Args:
            reason (str): Reason for rollback (optional)
        """
        if reason:
            logger.warning(
                "[ROLLBACK START] Project: {}, Reason: {}".format(
                    self.project_id, reason
                )
            )
        else:
            logger.warning(
                "[ROLLBACK START] Project: {}".format(self.project_id)
            )
    
    def log_rollback_operation(self, operation, details, success=True, error=None):
        """
        Log a rollback operation.
        
        Requirements: 24.7
        
        Args:
            operation (str): Operation being rolled back
            details (str): Details about the rollback operation
            success (bool): Whether the rollback succeeded
            error (Exception): Error if rollback failed (optional)
        """
        if success:
            logger.info(
                "[ROLLBACK {}] {}".format(operation.upper(), details)
            )
        else:
            logger.error(
                "[ROLLBACK {} FAILED] {}: {}".format(
                    operation.upper(), details, str(error)
                )
            )
    
    def log_rollback_completion(self, success=True):
        """
        Log the completion of a rollback operation.
        
        Requirements: 24.7
        
        Args:
            success (bool): Whether the rollback completed successfully
        """
        if success:
            logger.info(
                "[ROLLBACK COMPLETE] Project: {} - System restored to previous state".format(
                    self.project_id
                )
            )
        else:
            logger.error(
                "[ROLLBACK FAILED] Project: {} - Manual intervention required".format(
                    self.project_id
                )
            )
    
    def log_database_operation(self, operation, table_name, record_id=None, success=True, error=None):
        """
        Log a database operation.
        
        Requirements: 24.3
        
        Args:
            operation (str): Operation type ('insert', 'update', 'delete')
            table_name (str): Name of the table
            record_id: ID of the record (optional)
            success (bool): Whether the operation succeeded
            error (Exception): Error if operation failed (optional)
        """
        self.operation_count += 1
        
        if success:
            if record_id:
                logger.debug(
                    "[DB {}] {}: ID={}".format(
                        operation.upper(), table_name, record_id
                    )
                )
            else:
                logger.debug(
                    "[DB {}] {}".format(operation.upper(), table_name)
                )
        else:
            if record_id:
                logger.error(
                    "[DB {} FAILED] {}: ID={}: {}".format(
                        operation.upper(), table_name, record_id, str(error)
                    )
                )
            else:
                logger.error(
                    "[DB {} FAILED] {}: {}".format(
                        operation.upper(), table_name, str(error)
                    )
                )
    
    def log_validation(self, validation_type, result, details=None):
        """
        Log a validation check.
        
        Args:
            validation_type (str): Type of validation
            result (bool): Validation result
            details (str): Additional details (optional)
        """
        if result:
            if details:
                logger.debug(
                    "[VALIDATION PASS] {}: {}".format(validation_type, details)
                )
            else:
                logger.debug(
                    "[VALIDATION PASS] {}".format(validation_type)
                )
        else:
            if details:
                logger.warning(
                    "[VALIDATION FAIL] {}: {}".format(validation_type, details)
                )
            else:
                logger.warning(
                    "[VALIDATION FAIL] {}".format(validation_type)
                )
    
    def log_progress(self, current, total, entity_type):
        """
        Log migration progress.
        
        Args:
            current (int): Current count
            total (int): Total count
            entity_type (str): Type of entity being migrated
        """
        percentage = (current / total * 100) if total > 0 else 0
        logger.info(
            "[PROGRESS] {}: {}/{} ({:.1f}%)".format(
                entity_type, current, total, percentage
            )
        )
    
    def log_warning(self, message, context=None):
        """
        Log a warning message.
        
        Args:
            message (str): Warning message
            context (str): Additional context (optional)
        """
        if context:
            logger.warning(
                "[MIGRATION WARNING] Project: {}, Context: {}, Message: {}".format(
                    self.project_id, context, message
                )
            )
        else:
            logger.warning(
                "[MIGRATION WARNING] Project: {}, Message: {}".format(
                    self.project_id, message
                )
            )
    
    def log_info(self, message, context=None):
        """
        Log an informational message.
        
        Args:
            message (str): Info message
            context (str): Additional context (optional)
        """
        if context:
            logger.info(
                "[MIGRATION INFO] Project: {}, Context: {}, Message: {}".format(
                    self.project_id, context, message
                )
            )
        else:
            logger.info(
                "[MIGRATION INFO] Project: {}, Message: {}".format(
                    self.project_id, message
                )
            )
    
    def get_duration(self):
        """
        Get the duration of the migration so far.
        
        Returns:
            float: Duration in seconds
        """
        return (datetime.now() - self.start_time).total_seconds()
    
    def get_summary(self):
        """
        Get a summary of the migration operation.
        
        Returns:
            dict: Summary information
        """
        return {
            'project_id': self.project_id,
            'migration_type': self.migration_type,
            'user_id': self.user_id,
            'start_time': self.start_time.isoformat(),
            'duration_seconds': self.get_duration(),
            'operation_count': self.operation_count
        }
