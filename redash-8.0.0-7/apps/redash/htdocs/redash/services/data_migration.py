"""
Data Migration Orchestrator Service

Orchestrates the complete data migration process for shared projects.
Ensures transactional integrity and handles rollback on failure.

This service coordinates:
- File migration between private and shared directories
- VDB configuration migration (foreign tables and views)
- Database record updates
- VDB redeployment
- Transaction management and rollback

Requirements: 1.1-1.5, 2.1-2.7, 3.1-3.5, 4.1-4.6, 5.1-5.5, 6.1-6.5,
              9.1-9.5, 10.1-10.7, 11.1-11.5, 12.1-12.5, 13.1-13.5,
              14.1-14.5, 15.1-15.5, 16.1-16.6, 23.1-23.5
"""

import logging
from sqlalchemy.orm.attributes import flag_modified
from redash.services.file_migration import FileMigrationService
from redash.services.vdb_migration import VDBMigrationService
from redash.services.vdb_backup import VDBBackupService
from redash.services.migration_logger import MigrationLogger
from redash.services.migration_notifications import MigrationNotificationService
from redash.services.migration_lock import MigrationLockService
from redash.services.shared_vdb_provisioning import SharedVDBProvisioningService, SharedVDBProvisioningError
from redash.services.exceptions import (
    DataMigrationError,
    FileMigrationError,
    VDBMigrationError,
    VDBNotFoundError,
    ProjectNotFoundError,
    MigrationRollbackError,
    MigrationInProgressError
)
from redash.models.data_migration_log import DataMigrationLog
from redash import models

logger = logging.getLogger(__name__)


class DataMigrationOrchestrator(object):
    """
    Orchestrates the complete data migration process for shared projects.
    
    This class ensures transactional integrity by coordinating all migration
    operations and handling rollback on failure. It manages:
    - File migration between directories
    - VDB configuration updates
    - Database record updates
    - VDB redeployment
    - Error handling and rollback
    """
    
    def __init__(self):
        """Initialize Data Migration Orchestrator."""
        self.file_service = FileMigrationService()
        self.vdb_service = VDBMigrationService()
        self.vdb_backup_service = VDBBackupService()
        self.notification_service = MigrationNotificationService()
        self.lock_service = MigrationLockService()
        self.shared_vdb_provisioning_service = SharedVDBProvisioningService()
    
    @staticmethod
    def is_migration_schema_ready():
        """
        Check if the database schema for migrations is ready.
        
        Returns:
            bool: True if migration tables exist, False otherwise
        """
        try:
            from sqlalchemy import inspect
            inspector = inspect(models.db.engine)
            tables = inspector.get_table_names()
            
            # Check if required tables exist
            required_tables = ['data_migration_logs']
            for table in required_tables:
                if table not in tables:
                    logger.warning("Migration table '{}' does not exist. Run database migrations first.".format(table))
                    return False
            
            return True
        except Exception as e:
            logger.error("Error checking migration schema: {}".format(str(e)))
            return False
    
    def migrate_project_to_shared(self, project_id, user_id):
        """
        Migrate a project from private to shared state.
        
        This method performs the following steps:
        1. Acquire migration lock (prevent concurrent migrations)
        2. Create migration log
        3. Begin database transaction
        4. Get all project datasources and queries
        5. Move datasource files to shared directory
        6. Update datasource records
        7. Create VDB backups (private and shared)
        8. Migrate VDB configurations (foreign tables and views)
        9. Redeploy VDBs
        10. Commit transaction
        11. Mark migration as completed
        12. Release migration lock
        
        On failure: Rollback all changes, restore VDB from backup, and release lock
        
        Requirements: 1.1-1.5, 2.1-2.7, 3.1-3.5, 4.1-4.6, 5.1-5.5, 6.1-6.5,
                      14.1-14.5, 15.1-15.5, 16.1-16.6, 22.1-22.5, 23.1-23.5
        
        Args:
            project_id (int): ID of the project to migrate
            user_id (int): ID of the user initiating the migration
            
        Raises:
            ProjectNotFoundError: If project does not exist
            MigrationInProgressError: If migration is already in progress
            DataMigrationError: If migration fails
        """
        # Check if migration schema is ready
        if not self.is_migration_schema_ready():
            error_msg = "Migration schema not ready. Please run database migrations 014, 015, 016 first."
            logger.error(error_msg)
            raise DataMigrationError(error_msg)
        
        migration_log = None
        backup_state = {}
        migration_logger = MigrationLogger(project_id, 'share', user_id)
        
        # Use context manager to ensure lock is always released (Requirements 22.1, 22.2, 22.4)
        try:
            # Acquire migration lock to prevent concurrent migrations (Requirement 22.1, 22.2)
            self.lock_service.acquire_lock(project_id)
            migration_logger.log_info("Acquired migration lock for project {}".format(project_id))
        except MigrationInProgressError as e:
            # Migration already in progress (Requirement 22.3)
            migration_logger.log_error(e, context="lock_acquisition")
            raise
        
        try:
            # Log migration start (Requirement 24.1)
            migration_logger.log_migration_start()
            
            # Create migration log
            migration_log = DataMigrationLog.create_log(
                project_id=project_id,
                migration_type='share',
                user_id=user_id
            )
            # Set total steps for progress tracking (Requirements: 21.1, 21.2)
            migration_log.set_total_steps(5)  # 1. Files, 2. Queries, 3. VDB backup, 4. VDB migration, 5. VDB redeploy
            migration_log.update_progress('initializing', 0)
            models.db.session.commit()
            migration_logger.log_database_operation('insert', 'data_migration_logs', migration_log.id)
            
            # Get project and validate (Requirement 1.1)
            project = models.Project.query.get(project_id)
            if not project:
                raise ProjectNotFoundError("Project {} not found".format(project_id), project_id=project_id)
            
            migration_logger.log_validation('project_exists', True, "Project ID: {}".format(project_id))
            
            org_id = project.org_id
            owner_id = project.owner_id
            
            # Get all datasources and queries (Requirements 1.2, 1.3)
            # Use project.data_sources relationship to get ProjectDataSource objects
            # Then extract the actual DataSource objects
            datasources = [pds.data_source for pds in project.data_sources]
            
            # Get queries associated with this project
            # Using project_id array column (not query_projects join table)
            queries = models.Query.query.filter(
                models.Query.project_id.any(project_id)
            ).all()
            
            migration_logger.log_info(
                "Found {} datasources and {} queries".format(len(datasources), len(queries))
            )
            
            # Validate project has datasources (Requirement 1.4)
            if not datasources:
                migration_logger.log_warning("No datasources to migrate")
                migration_log.mark_completed(0, len(queries))
                models.db.session.commit()
                migration_logger.log_migration_completion(0, len(queries))
                return
            
            # Log the migration event (Requirement 1.5)
            migration_logger.log_info(
                "Migrating {} datasources and {} queries".format(len(datasources), len(queries))
            )
            
            # Begin nested transaction for rollback capability (Requirement 16.1)
            models.db.session.begin_nested()
            
            # Step 1: Move datasource files to shared directory
            # Requirements: 2.1-2.7, 14.1-14.5
            migration_logger.log_info("Migrating {} datasources to shared folder".format(len(datasources)))
            migration_log.update_progress('copying_files', 1)
            models.db.session.commit()
            
            for idx, datasource in enumerate(datasources, 1):
                # Get current file path
                migration_logger.log_info("Processing datasource '{}' (type: {}, owner: {})".format(
                    datasource.name, datasource.type, datasource.owner
                ))
                file_path = self._get_datasource_file_path(datasource)
                migration_logger.log_info("Datasource '{}' file_path: {}".format(datasource.name, file_path))
                
                if file_path:
                    try:
                        migration_logger.log_progress(idx, len(datasources), 'datasources')
                        
                        # Move file to shared directory (Requirements 2.1-2.3)
                        shared_path = self.file_service.move_to_shared(
                            org_id=org_id,
                            user_id=owner_id,
                            file_path=file_path
                        )
                        
                        # Log file operation (Requirement 24.2)
                        migration_logger.log_file_operation('copy', file_path, shared_path, success=True)
                        
                        # Store backup state for rollback (Requirement 16.3)
                        backup_state[datasource.id] = {
                            'private_path': file_path,
                            'shared_path': shared_path,
                            'is_shared': datasource.options.get('is_shared', False) if datasource.options else False
                        }
                        
                        # Update datasource record (Requirements 2.4, 3.1-3.5)
                        self._mark_datasource_as_shared(datasource, file_path, shared_path)
                        migration_logger.log_database_operation('update', 'datasources', datasource.id)
                        
                    except FileMigrationError as e:
                        # Rollback on file migration failure (Requirement 14.4)
                        migration_logger.log_file_operation('copy', file_path, None, success=False, error=e)
                        migration_logger.log_error(e, context="datasource_file_migration")
                        raise DataMigrationError(
                            "Failed to migrate datasource {}: {}".format(datasource.id, str(e))
                        )
                else:
                    # No file path found - datasource might not have a physical file
                    # But we still need to ensure private_file_path and shared_file_path are set for VDB migration
                    # Construct the expected shared path even if file doesn't exist
                    migration_logger.log_warning("No file path found for datasource '{}', skipping file copy but will attempt VDB migration".format(datasource.name))
                    
                    # If private_file_path was auto-populated by _get_datasource_file_path, use it
                    if datasource.private_file_path:
                        # Construct shared path from private path
                        import os
                        filename = os.path.basename(datasource.private_file_path)
                        shared_dir = os.path.join(self.file_service.base_path, str(org_id), 'shared', 'uploads')
                        shared_path = os.path.join(shared_dir, filename)
                        
                        # Update datasource record for VDB migration
                        self._mark_datasource_as_shared(datasource, datasource.private_file_path, shared_path)
                        migration_logger.log_info("Set shared_file_path for datasource '{}' to enable VDB migration: {}".format(
                            datasource.name, shared_path
                        ))
                        migration_logger.log_database_operation('update', 'datasources', datasource.id)
            
            # Step 2: Mark queries as shared (Requirements 8.1-8.5, 15.1-15.5)
            migration_logger.log_info("Marking {} queries as shared".format(len(queries)))
            migration_log.update_progress('updating_queries', 2)
            models.db.session.commit()
            
            for query in queries:
                self._mark_query_as_shared(query)
                migration_logger.log_database_operation('update', 'queries', query.id)
            
            # Flush database changes before VDB migration
            models.db.session.flush()
            
            # Step 3: Create VDB backups before migration
            # Requirements: 23.1, 23.2, 23.3
            migration_logger.log_info("Creating VDB backups before migration")
            backup_paths = {}
            
            try:
                # Backup private VDB
                private_vdb_path = self.vdb_service._get_private_vdb_path(org_id, owner_id)
                private_backup_path = self.vdb_backup_service.create_backup(
                    vdb_file_path=private_vdb_path,
                    org_id=org_id,
                    vdb_type='private',
                    user_id=owner_id
                )
                backup_paths['private'] = private_backup_path
                migration_logger.log_info("Created private VDB backup: {}".format(private_backup_path))
                
                # Backup shared VDB
                shared_vdb_path = self.vdb_service._get_shared_vdb_path(org_id)
                shared_backup_path = self.vdb_backup_service.create_backup(
                    vdb_file_path=shared_vdb_path,
                    org_id=org_id,
                    vdb_type='shared'
                )
                backup_paths['shared'] = shared_backup_path
                migration_logger.log_info("Created shared VDB backup: {}".format(shared_backup_path))
                
            except Exception as e:
                migration_logger.log_warning("Failed to create VDB backups: {}".format(str(e)))
                # Continue with migration even if backup fails
                # Backups are a safety measure but not critical
            
            # Step 4: Migrate VDB configurations
            # Requirements: 4.1-4.6, 5.1-5.5, 26.1-26.6
            migration_logger.log_info("Migrating VDB configurations to shared VDB")
            migration_log.update_progress('updating_vdb', 4)
            models.db.session.commit()
            
            # Check and auto-provision shared VDB if needed (Requirements 26.1, 26.2, 26.3, 26.6)
            try:
                migration_logger.log_info("Checking shared VDB provisioning status")
                shared_vdb = self.shared_vdb_provisioning_service.check_and_provision_if_needed(org_id)
                
                if not shared_vdb:
                    # No VDB file exists - this is an error condition
                    error_msg = "No shared VDB file found for organization {}. Cannot proceed with migration.".format(org_id)
                    migration_logger.log_error(error_msg, context="shared_vdb_check")
                    raise VDBNotFoundError(error_msg)
                
                migration_logger.log_info("Shared VDB ready: {}".format(shared_vdb.vdb_id))
                
            except SharedVDBProvisioningError as e:
                # Auto-provisioning failed
                error_msg = "Failed to provision shared VDB for organization {}: {}".format(org_id, str(e))
                migration_logger.log_error(error_msg, context="shared_vdb_provisioning")
                raise VDBNotFoundError(error_msg)
            
            # Refresh datasource objects to ensure they have updated file paths
            # This is critical because _mark_datasource_as_shared() updated the paths
            # but the objects in the datasources list might not reflect those changes
            models.db.session.flush()
            for ds in datasources:
                models.db.session.refresh(ds)
                migration_logger.log_info("Datasource '{}': private_file_path={}, shared_file_path={}".format(
                    ds.name, ds.private_file_path, ds.shared_file_path
                ))
            
            try:
                self.vdb_service.migrate_to_shared_vdb(
                    org_id=org_id,
                    user_id=owner_id,
                    datasources=datasources,
                    queries=queries,
                    migration_logger=migration_logger
                )
            except (VDBMigrationError, VDBNotFoundError) as e:
                migration_logger.log_error(e, context="vdb_migration")
                
                # Attempt to restore from backup if available (Requirement 23.5)
                if backup_paths:
                    migration_logger.log_info("Attempting to restore VDB from backup")
                    try:
                        if 'private' in backup_paths:
                            self.vdb_backup_service.restore_from_backup(
                                backup_paths['private'],
                                private_vdb_path
                            )
                            migration_logger.log_info("Restored private VDB from backup")
                        
                        if 'shared' in backup_paths:
                            self.vdb_backup_service.restore_from_backup(
                                backup_paths['shared'],
                                shared_vdb_path
                            )
                            migration_logger.log_info("Restored shared VDB from backup")
                    except Exception as restore_error:
                        migration_logger.log_error(restore_error, context="vdb_restore")
                
                raise DataMigrationError("VDB migration failed: {}".format(str(e)))
            
            # Step 5: VDB Redeployment (Requirements 6.1-6.5)
            # Note: The VDBMigrationServlet now handles redeployment automatically
            # This step is kept for progress tracking and logging purposes
            migration_logger.log_info("VDB redeployment handled by servlet")
            migration_log.update_progress('redeploying', 5)
            models.db.session.commit()
            
            # Commit transaction (Requirement 16.1)
            models.db.session.commit()
            
            # Mark project as shared (CRITICAL FIX)
            # This flag is used by file_upload.py to determine where to save uploaded files
            # Without this, new files uploaded by members go to their private folders instead of shared
            project.is_shared = True
            models.db.session.add(project)
            models.db.session.commit()
            migration_logger.log_info("Marked project {} as shared (is_shared=True)".format(project_id))
            migration_logger.log_database_operation('update', 'projects', project_id)
            
            # Mark migration as completed (Requirement 24.5)
            migration_log.mark_completed(len(datasources), len(queries))
            models.db.session.commit()
            migration_logger.log_database_operation('update', 'data_migration_logs', migration_log.id)
            
            # Log migration completion
            migration_logger.log_migration_completion(len(datasources), len(queries))
            
            # Release migration lock (Requirement 22.4)
            self.lock_service.release_lock(project_id)
            migration_logger.log_info("Released migration lock for project {}".format(project_id))
            
            # Send success notification (Requirement 21.3)
            try:
                self.notification_service.notify_migration_success(
                    project_id=project_id,
                    user_id=user_id,
                    migration_type='share',
                    datasources_count=len(datasources),
                    queries_count=len(queries)
                )
            except Exception as notif_error:
                migration_logger.log_warning("Failed to send success notification: {}".format(str(notif_error)))
            
        except Exception as e:
            # Log error with stack trace (Requirement 24.6)
            migration_logger.log_error(e, context="migration_to_shared")
            
            # Log rollback start (Requirement 24.7)
            migration_logger.log_rollback_start(reason=str(e))
            
            # Rollback database changes (Requirement 16.2)
            models.db.session.rollback()
            migration_logger.log_rollback_operation('database', 'Rolling back database transaction', success=True)
            
            # Rollback file changes (Requirement 16.3)
            rollback_failed = False
            try:
                self._rollback_file_migration(backup_state, org_id, migration_logger)
                migration_logger.log_rollback_completion(success=True)
            except Exception as rollback_error:
                rollback_failed = True
                migration_logger.log_error(rollback_error, context="rollback")
                migration_logger.log_rollback_completion(success=False)
            
            # Mark migration as failed (Requirements 16.5, 24.6)
            if migration_log:
                try:
                    migration_log.mark_failed(str(e))
                    migration_log.mark_rolled_back()
                    models.db.session.commit()
                    migration_logger.log_database_operation('update', 'data_migration_logs', migration_log.id)
                except Exception as log_error:
                    migration_logger.log_error(log_error, context="update_migration_log")
            
            # Release migration lock (Requirement 22.4)
            try:
                self.lock_service.release_lock(project_id)
                migration_logger.log_info("Released migration lock for project {}".format(project_id))
            except Exception as lock_error:
                migration_logger.log_error(lock_error, context="lock_release")
            
            # Send failure notification to project owner (Requirement 16.6, 21.4)
            try:
                self.notification_service.notify_migration_failure(
                    project_id=project_id,
                    user_id=user_id,
                    migration_type='share',
                    error=e,
                    migration_log_id=migration_log.id if migration_log else None
                )
            except Exception as notif_error:
                migration_logger.log_error(notif_error, context="send_failure_notification")
            
            # Send critical error notification to admins if rollback failed (Requirement 16.6)
            if rollback_failed:
                try:
                    self.notification_service.notify_critical_error(
                        project_id=project_id,
                        user_id=user_id,
                        migration_type='share',
                        error=e,
                        rollback_failed=True
                    )
                except Exception as notif_error:
                    migration_logger.log_error(notif_error, context="send_critical_notification")
            
            raise DataMigrationError("Failed to migrate project: {}".format(str(e)))
    
    def migrate_project_to_private(self, project_id, user_id):
        """
        Migrate a project from shared to private state.
        
        This is the reverse of migrate_project_to_shared. It performs:
        1. Acquire migration lock (prevent concurrent migrations)
        2. Create migration log
        3. Begin database transaction
        4. Get all project datasources and queries
        5. Move datasource files back to private directory
        6. Update datasource records
        7. Create VDB backups (private and shared)
        8. Migrate VDB configurations back
        9. Redeploy VDBs
        10. Commit transaction
        11. Mark migration as completed
        12. Release migration lock
        
        On failure: Rollback all changes, restore VDB from backup, and release lock
        
        Requirements: 9.1-9.5, 10.1-10.7, 11.1-11.5, 12.1-12.5, 13.1-13.5,
                      14.1-14.5, 15.1-15.5, 16.1-16.6, 22.1-22.5, 23.1-23.5
        
        Args:
            project_id (int): ID of the project to migrate
            user_id (int): ID of the user initiating the migration
            
        Raises:
            ProjectNotFoundError: If project does not exist
            MigrationInProgressError: If migration is already in progress
            DataMigrationError: If migration fails
        """
        # Ensure project_id is an integer (API may pass it as string)
        # This is critical for array membership checks later
        project_id = int(project_id)
        user_id = int(user_id)
        
        migration_log = None
        backup_state = {}
        migration_logger = MigrationLogger(project_id, 'unshare', user_id)
        
        # Use context manager to ensure lock is always released (Requirements 22.1, 22.2, 22.4)
        try:
            # Acquire migration lock to prevent concurrent migrations (Requirement 22.1, 22.2)
            self.lock_service.acquire_lock(project_id)
            migration_logger.log_info("Acquired migration lock for project {}".format(project_id))
        except MigrationInProgressError as e:
            # Migration already in progress (Requirement 22.3)
            migration_logger.log_error(e, context="lock_acquisition")
            raise
        
        try:
            # Log migration start (Requirement 24.1)
            migration_logger.log_migration_start()
            
            # Create migration log
            migration_log = DataMigrationLog.create_log(
                project_id=project_id,
                migration_type='unshare',
                user_id=user_id
            )
            # Set total steps for progress tracking (Requirements: 21.1, 21.2)
            migration_log.set_total_steps(5)  # 1. Files, 2. Queries, 3. VDB backup, 4. VDB migration, 5. VDB redeploy
            migration_log.update_progress('initializing', 0)
            models.db.session.commit()
            migration_logger.log_database_operation('insert', 'data_migration_logs', migration_log.id)
            
            # Get project and validate (Requirement 9.1)
            project = models.Project.query.get(project_id)
            if not project:
                raise ProjectNotFoundError("Project {} not found".format(project_id), project_id=project_id)
            
            migration_logger.log_validation('project_exists', True, "Project ID: {}".format(project_id))
            
            org_id = project.org_id
            owner_id = project.owner_id
            
            # Validate project owner exists (Requirement 9.4)
            owner = models.User.query.get(owner_id)
            if not owner:
                raise DataMigrationError("Project owner {} not found".format(owner_id))
            
            migration_logger.log_validation('project_owner_exists', True, "Owner ID: {}".format(owner_id))
            
            # Get all shared datasources and queries (Requirements 9.2, 9.3)
            # Use project.data_sources relationship and filter for shared ones
            # Check the is_shared column (not options) as that's what gets updated
            datasources = [
                pds.data_source for pds in project.data_sources
                if pds.data_source.is_shared
            ]
            
            # Get queries associated with this project
            # Using project_id array column (not query_projects join table)
            queries = models.Query.query.filter(
                models.Query.project_id.any(project_id)
            ).all()
            
            # Log the migration event (Requirement 9.5)
            migration_logger.log_info(
                "Migrating {} datasources and {} queries back to private".format(len(datasources), len(queries))
            )
            
            # Begin nested transaction for rollback capability (Requirement 16.1)
            models.db.session.begin_nested()
            
            # Step 1: Move datasource files back to private directory
            # Requirements: 10.1-10.7, 14.1-14.5
            logger.info("Migrating {} datasources back to private folder".format(len(datasources)))
            migration_log.update_progress('copying_files', 1)
            models.db.session.commit()
            
            for datasource in datasources:
                # Get current file path
                file_path = self._get_datasource_file_path(datasource)
                
                # Get the datasource owner (not project owner!)
                # This is critical for multi-owner unshare scenarios
                datasource_owner_id = datasource.original_owner_id or datasource.owner
                
                if file_path:
                    try:
                        # Move file to private directory (Requirements 10.1-10.3)
                        # IMPORTANT: Use datasource owner, not project owner!
                        private_path = self.file_service.move_to_private(
                            org_id=org_id,
                            user_id=datasource_owner_id,
                            file_path=file_path
                        )
                        
                        # Store backup state for rollback (Requirement 16.3)
                        backup_state[datasource.id] = {
                            'shared_path': file_path,
                            'private_path': private_path,
                            'is_shared': datasource.options.get('is_shared', False) if datasource.options else False
                        }
                        
                        # Update datasource record BUT preserve shared_file_path for VDB migration
                        # (Requirement 10.4)
                        # CRITICAL: Don't clear shared_file_path yet - VDB migration needs it!
                        datasource.is_shared = False
                        datasource.private_file_path = private_path
                        # shared_file_path will be cleared after VDB migration completes
                        
                        # Also update options if they exist (for backwards compatibility)
                        if hasattr(datasource, 'options') and datasource.options:
                            if isinstance(datasource.options, dict):
                                datasource.options['is_shared'] = False
                                datasource.options['file'] = private_path
                        
                        # Mark as modified to trigger SQLAlchemy update
                        models.db.session.add(datasource)
                        
                        logger.debug("Migrated datasource {}: {} -> {}".format(
                            datasource.id, file_path, private_path
                        ))
                        
                    except FileMigrationError as e:
                        # Log warning and skip datasource with missing files (Requirement 14.4)
                        # Don't fail the entire migration for missing files
                        error_msg = str(e)
                        if "Source file not found" in error_msg or "not found" in error_msg.lower():
                            migration_logger.log_warning(
                                "Skipping datasource {} - file missing: {}".format(
                                    datasource.id, error_msg
                                )
                            )
                            # Remove this datasource from the list so it's not tracked
                            if datasource in datasources:
                                datasources.remove(datasource)
                            continue
                        else:
                            # For other file errors, still fail
                            logger.error("Failed to migrate datasource {}: {}".format(
                                datasource.id, error_msg
                            ))
                            raise DataMigrationError(
                                "Failed to migrate datasource {}: {}".format(datasource.id, error_msg)
                            )
            
            # Step 2: Mark queries as private (Requirements 15.1-15.5)
            logger.info("Marking {} queries as private".format(len(queries)))
            migration_log.update_progress('updating_queries', 2)
            models.db.session.commit()
            
            for query in queries:
                self._mark_query_as_private(query)
            
            # Flush database changes before VDB migration
            models.db.session.flush()
            
            # Step 3: Create VDB backups before migration
            # Requirements: 23.1, 23.2, 23.3
            migration_logger.log_info("Creating VDB backups before migration")
            migration_log.update_progress('backing_up_vdb', 3)
            models.db.session.commit()
            backup_paths = {}
            
            try:
                # Backup private VDB
                private_vdb_path = self.vdb_service._get_private_vdb_path(org_id, owner_id)
                private_backup_path = self.vdb_backup_service.create_backup(
                    vdb_file_path=private_vdb_path,
                    org_id=org_id,
                    vdb_type='private',
                    user_id=owner_id
                )
                backup_paths['private'] = private_backup_path
                migration_logger.log_info("Created private VDB backup: {}".format(private_backup_path))
                
                # Backup shared VDB
                shared_vdb_path = self.vdb_service._get_shared_vdb_path(org_id)
                shared_backup_path = self.vdb_backup_service.create_backup(
                    vdb_file_path=shared_vdb_path,
                    org_id=org_id,
                    vdb_type='shared'
                )
                backup_paths['shared'] = shared_backup_path
                migration_logger.log_info("Created shared VDB backup: {}".format(shared_backup_path))
                
            except Exception as e:
                migration_logger.log_warning("Failed to create VDB backups: {}".format(str(e)))
                # Continue with migration even if backup fails
                # Backups are a safety measure but not critical
            
            # Step 4: Migrate VDB configurations back
            # Requirements: 11.1-11.5, 12.1-12.5
            # CRITICAL FIX: Group datasources by owner for multi-owner support
            migration_logger.log_info("Migrating VDB configurations back to private VDBs")
            migration_log.update_progress('updating_vdb', 4)
            models.db.session.commit()
            
            # Group datasources by their actual owner (not project owner)
            datasources_by_owner = {}
            for ds in datasources:
                ds_owner = ds.original_owner_id or ds.owner
                if ds_owner not in datasources_by_owner:
                    datasources_by_owner[ds_owner] = []
                datasources_by_owner[ds_owner].append(ds)
            
            migration_logger.log_info("Grouped {} datasources into {} owner groups".format(
                len(datasources), len(datasources_by_owner)
            ))
            for ds_owner, owner_datasources in datasources_by_owner.items():
                migration_logger.log_info("  Owner {}: {} datasources".format(ds_owner, len(owner_datasources)))
            
            try:
                # Migrate VDB for each datasource owner
                for datasource_owner_id, owner_datasources in datasources_by_owner.items():
                    migration_logger.log_info("Migrating {} datasources for owner {} to their private VDB".format(
                        len(owner_datasources), datasource_owner_id
                    ))
                    
                    # Get queries for this owner
                    owner_queries = [q for q in queries if q.user_id == datasource_owner_id]
                    
                    self.vdb_service.migrate_to_private_vdb(
                        org_id=org_id,
                        user_id=datasource_owner_id,  # Use datasource owner, not project owner
                        datasources=owner_datasources,
                        queries=owner_queries,
                        migration_logger=migration_logger
                    )
                    
                    migration_logger.log_info("Successfully migrated VDB for owner {}".format(datasource_owner_id))
                
                # NOW clear shared_file_path after VDB migration is complete
                # This ensures VDB migration had access to the path information it needed
                migration_logger.log_info("Clearing shared_file_path from datasources after VDB migration")
                for datasource in datasources:
                    datasource.shared_file_path = None
                    
                    # Also remove from options if present
                    if hasattr(datasource, 'options') and datasource.options:
                        if isinstance(datasource.options, dict):
                            if 'shared_file_path' in datasource.options:
                                del datasource.options['shared_file_path']
                    
                    models.db.session.add(datasource)
                
                migration_logger.log_info("Cleared shared_file_path from {} datasources".format(len(datasources)))
                
            except (VDBMigrationError, VDBNotFoundError) as e:
                migration_logger.log_error(e, context="vdb_migration")
                
                # Attempt to restore from backup if available (Requirement 23.5)
                if backup_paths:
                    migration_logger.log_info("Attempting to restore VDB from backup")
                    try:
                        if 'private' in backup_paths:
                            self.vdb_backup_service.restore_from_backup(
                                backup_paths['private'],
                                private_vdb_path
                            )
                            migration_logger.log_info("Restored private VDB from backup")
                        
                        if 'shared' in backup_paths:
                            self.vdb_backup_service.restore_from_backup(
                                backup_paths['shared'],
                                shared_vdb_path
                            )
                            migration_logger.log_info("Restored shared VDB from backup")
                    except Exception as restore_error:
                        migration_logger.log_error(restore_error, context="vdb_restore")
                
                raise DataMigrationError("VDB migration failed: {}".format(str(e)))
            
            # Step 5: VDB Redeployment (Requirements 6.1-6.5)
            # Note: The VDBMigrationServlet now handles redeployment automatically
            # This step is kept for progress tracking and logging purposes
            migration_logger.log_info("VDB redeployment handled by servlet")
            migration_log.update_progress('redeploying', 5)
            models.db.session.commit()
            
            # Commit transaction (Requirement 16.1)
            models.db.session.commit()
            
            # NEW: Migrate non-owner queries to their private VDBs and clean up project associations
            # When project reverts to private, queries owned by other users need to be:
            # 1. Migrated back to their owners' private VDBs
            # 2. Removed from the project
            migration_logger.log_info("=== CLEANUP SECTION STARTED ===")
            migration_logger.log_info("Project owner: {}, Project ID: {}".format(owner_id, project_id))
            migration_logger.log_info("=== CLEANUP: Migrating non-owner queries and removing non-owner resources from project ===")
            
            removed_datasources = []
            removed_queries = []
            queries_to_migrate = {}  # Map of user_id -> list of queries
            
            # Remove datasources that don't belong to project owner
            for pds in list(project.data_sources):
                datasource = pds.data_source
                datasource_owner = datasource.original_owner_id or datasource.owner
                
                if datasource_owner and datasource_owner != owner_id:
                    migration_logger.log_info("Removing datasource '{}' (ID: {}, owner: {}) from project (owner: {})".format(
                        datasource.name, datasource.id, datasource_owner, owner_id
                    ))
                    models.db.session.delete(pds)
                    removed_datasources.append(datasource.name)
                    migration_logger.log_database_operation('delete', 'project_data_sources', 
                                                           "project_id={},data_source_id={}".format(project_id, datasource.id))
            
            # Identify queries that don't belong to project owner and need migration
            # Get fresh query list since we're modifying project_id arrays
            project_queries = models.Query.query.filter(
                models.Query.project_id.any(project_id)
            ).all()
            
            migration_logger.log_info("Found {} total queries in project {}".format(len(project_queries), project_id))
            migration_logger.log_info("Checking each query for non-owner status...")
            
            for query in project_queries:
                query_owner = query.user_id
                
                migration_logger.log_info("Checking query {} '{}' (owner: {}) against project owner {}".format(
                    query.id, query.name, query_owner, owner_id
                ))
                
                if query_owner and query_owner != owner_id:
                    migration_logger.log_info("Found non-owner query '{}' (ID: {}, owner: {}) to migrate and remove from project".format(
                        query.name, query.id, query_owner
                    ))
                    
                    # Group queries by owner for batch migration
                    if query_owner not in queries_to_migrate:
                        queries_to_migrate[query_owner] = []
                    queries_to_migrate[query_owner].append(query)
                else:
                    migration_logger.log_info("Query {} is owned by project owner - keeping in project".format(query.id))
            
            # Log summary of queries to migrate
            total_queries_to_migrate = sum(len(queries) for queries in queries_to_migrate.values())
            migration_logger.log_info("Total non-owner queries to migrate: {}".format(total_queries_to_migrate))
            for owner_id_key, owner_queries in queries_to_migrate.items():
                migration_logger.log_info("  User {}: {} queries - {}".format(
                    owner_id_key, 
                    len(owner_queries),
                    [q.id for q in owner_queries]
                ))
            
            # Migrate queries back to their owners' private VDBs
            if queries_to_migrate:
                migration_logger.log_info("Migrating {} users' queries back to their private VDBs".format(len(queries_to_migrate)))
                
                for query_owner_id, owner_queries in queries_to_migrate.items():
                    try:
                        migration_logger.log_info("Migrating {} queries for user {} to their private VDB".format(
                            len(owner_queries), query_owner_id
                        ))
                        
                        # Get the datasources associated with these queries
                        query_datasources = []
                        for query in owner_queries:
                            if query.data_source_id:
                                ds = models.DataSource.query.get(query.data_source_id)
                                if ds and ds not in query_datasources:
                                    query_datasources.append(ds)
                        
                        # Migrate queries to owner's private VDB
                        # This will create foreign tables and views in the owner's private VDB
                        self.vdb_service.migrate_to_private_vdb(
                            org_id=org_id,
                            user_id=query_owner_id,
                            datasources=query_datasources,
                            queries=owner_queries,
                            migration_logger=migration_logger
                        )
                        
                        migration_logger.log_info("Successfully migrated {} queries to user {}'s private VDB".format(
                            len(owner_queries), query_owner_id
                        ))
                        
                        # Refresh query objects after VDB migration to ensure we have latest state
                        # The VDB migration may have modified the queries or caused session changes
                        for query in owner_queries:
                            models.db.session.refresh(query)
                            migration_logger.log_info("Refreshed query {} - current project_id: {}".format(
                                query.id, query.project_id
                            ))
                        
                        # Now remove these queries from the project
                        for query in owner_queries:
                            if query.project_id and project_id in query.project_id:
                                migration_logger.log_info("Removing query {} from project {} (current project_id: {})".format(
                                    query.id, project_id, query.project_id
                                ))
                                query.project_id.remove(project_id)
                                flag_modified(query, 'project_id')  # CRITICAL: Tell SQLAlchemy the array changed
                                models.db.session.add(query)
                                removed_queries.append(query.name)
                                migration_logger.log_database_operation('update', 'queries', query.id)
                                migration_logger.log_info("Query {} project_id after removal: {}".format(
                                    query.id, query.project_id
                                ))
                            else:
                                migration_logger.log_warning("Query {} not in project {} (project_id: {})".format(
                                    query.id, project_id, query.project_id
                                ))
                        
                    except Exception as e:
                        migration_logger.log_error(e, context="migrate_non_owner_queries_user_{}".format(query_owner_id))
                        # Continue with other users' queries even if one fails
                        migration_logger.log_warning("Failed to migrate queries for user {}, but continuing with cleanup".format(query_owner_id))
                        
                        # Still remove from project even if migration failed
                        # The queries will remain in shared VDB but won't be associated with this project
                        # Refresh query objects to ensure we have latest state
                        for query in owner_queries:
                            try:
                                models.db.session.refresh(query)
                                migration_logger.log_info("Refreshed query {} after migration failure - current project_id: {}".format(
                                    query.id, query.project_id
                                ))
                            except Exception as refresh_error:
                                migration_logger.log_warning("Failed to refresh query {}: {}".format(
                                    query.id, str(refresh_error)
                                ))
                        
                        for query in owner_queries:
                            if query.project_id and project_id in query.project_id:
                                migration_logger.log_info("Removing query {} from project {} after migration failure (current project_id: {})".format(
                                    query.id, project_id, query.project_id
                                ))
                                query.project_id.remove(project_id)
                                flag_modified(query, 'project_id')  # CRITICAL: Tell SQLAlchemy the array changed
                                models.db.session.add(query)
                                removed_queries.append(query.name)
                                migration_logger.log_database_operation('update', 'queries', query.id)
                                migration_logger.log_info("Query {} project_id after removal: {}".format(
                                    query.id, query.project_id
                                ))
            
            # Commit cleanup changes
            migration_logger.log_info("Committing cleanup changes to database...")
            models.db.session.commit()
            migration_logger.log_info("Cleanup changes committed successfully")
            
            if removed_datasources or removed_queries:
                migration_logger.log_info("Cleanup complete: Removed {} datasources and {} queries from project".format(
                    len(removed_datasources), len(removed_queries)
                ))
            else:
                migration_logger.log_info("Cleanup complete: No non-owner resources to remove")
            
            # Commit cleanup operations and refresh project to clear stale references
            # This prevents "Instance has been deleted" errors when updating project
            models.db.session.commit()
            models.db.session.refresh(project)
            
            # FINAL STEP: Ensure ALL non-owner queries are removed from project
            # This is a final safety check to guarantee no orphan queries remain
            migration_logger.log_info("=== FINAL CLEANUP: Ensuring all non-owner queries are removed from project ===")
            
            # Get fresh list of all queries still associated with this project
            final_project_queries = models.Query.query.filter(
                models.Query.project_id.any(project_id)
            ).all()
            
            final_removed_queries = []
            for query in final_project_queries:
                query_owner = query.user_id
                
                if query_owner and query_owner != owner_id:
                    migration_logger.log_info("FINAL CLEANUP: Found orphan query '{}' (ID: {}, owner: {})".format(
                        query.name, query.id, query_owner
                    ))
                    
                    # CRITICAL FIX: Refresh from database to get actual state
                    # The query object may have stale in-memory state from earlier operations
                    models.db.session.refresh(query)
                    migration_logger.log_info("FINAL CLEANUP: Refreshed query {} from database. Current project_id: {}".format(
                        query.id, query.project_id
                    ))
                    
                    # Remove project_id from query's project_id array
                    if query.project_id and project_id in query.project_id:
                        migration_logger.log_info("FINAL CLEANUP: Removing query {} from project {}".format(
                            query.id, project_id
                        ))
                        query.project_id.remove(project_id)
                        flag_modified(query, 'project_id')  # CRITICAL: Tell SQLAlchemy the array changed
                        models.db.session.add(query)
                        final_removed_queries.append(query.name)
                        migration_logger.log_database_operation('update', 'queries', query.id)
                        migration_logger.log_info("FINAL CLEANUP: Query {} removed from project. Remaining projects: {}".format(
                            query.id, query.project_id
                        ))
                    else:
                        migration_logger.log_info("FINAL CLEANUP: Query {} already removed from project (project_id: {})".format(
                            query.id, query.project_id
                        ))
            
            if final_removed_queries:
                migration_logger.log_info("FINAL CLEANUP: Removed {} additional orphan queries: {}".format(
                    len(final_removed_queries), final_removed_queries
                ))
                # Commit final cleanup
                models.db.session.commit()
            else:
                migration_logger.log_info("FINAL CLEANUP: No additional orphan queries found - project is clean")
            
            migration_logger.log_info("=== FINAL CLEANUP COMPLETE ===")
            
            # Mark project as NOT shared (CRITICAL FIX)
            # This flag is used by file_upload.py to determine where to save uploaded files
            # When project reverts to private, new files should go to owner's private folder
            project.is_shared = False
            models.db.session.add(project)
            models.db.session.commit()
            migration_logger.log_info("Marked project {} as NOT shared (is_shared=False)".format(project_id))
            migration_logger.log_database_operation('update', 'projects', project_id)
            
            # Mark migration as completed (Requirement 24.5)
            migration_log.mark_completed(len(datasources), len(queries))
            models.db.session.commit()
            migration_logger.log_database_operation('update', 'data_migration_logs', migration_log.id)
            
            # Log migration completion
            migration_logger.log_migration_completion(len(datasources), len(queries))
            
            # Release migration lock (Requirement 22.4)
            self.lock_service.release_lock(project_id)
            migration_logger.log_info("Released migration lock for project {}".format(project_id))
            
            # Send success notification (Requirement 21.3)
            try:
                self.notification_service.notify_migration_success(
                    project_id=project_id,
                    user_id=user_id,
                    migration_type='unshare',
                    datasources_count=len(datasources),
                    queries_count=len(queries)
                )
            except Exception as notif_error:
                migration_logger.log_warning("Failed to send success notification: {}".format(str(notif_error)))
            
        except Exception as e:
            # Log error with stack trace (Requirement 24.6)
            migration_logger.log_error(e, context="migration_to_private")
            
            # Log rollback start (Requirement 24.7)
            migration_logger.log_rollback_start(reason=str(e))
            
            # Rollback database changes (Requirement 16.2)
            models.db.session.rollback()
            migration_logger.log_rollback_operation('database', 'Rolling back database transaction', success=True)
            
            # Rollback file changes (Requirement 16.3)
            rollback_failed = False
            try:
                self._rollback_unshare_migration(backup_state, org_id, owner_id, migration_logger)
                migration_logger.log_rollback_completion(success=True)
            except Exception as rollback_error:
                rollback_failed = True
                migration_logger.log_error(rollback_error, context="rollback")
                migration_logger.log_rollback_completion(success=False)
            
            # Mark migration as failed (Requirements 16.5, 24.6)
            if migration_log:
                try:
                    migration_log.mark_failed(str(e))
                    migration_log.mark_rolled_back()
                    models.db.session.commit()
                    migration_logger.log_database_operation('update', 'data_migration_logs', migration_log.id)
                except Exception as log_error:
                    migration_logger.log_error(log_error, context="update_migration_log")
            
            # Release migration lock (Requirement 22.4)
            try:
                self.lock_service.release_lock(project_id)
                migration_logger.log_info("Released migration lock for project {}".format(project_id))
            except Exception as lock_error:
                migration_logger.log_error(lock_error, context="lock_release")
            
            # Send failure notification to project owner (Requirement 16.6, 21.4)
            try:
                self.notification_service.notify_migration_failure(
                    project_id=project_id,
                    user_id=user_id,
                    migration_type='unshare',
                    error=e,
                    migration_log_id=migration_log.id if migration_log else None
                )
            except Exception as notif_error:
                migration_logger.log_error(notif_error, context="send_failure_notification")
            
            # Send critical error notification to admins if rollback failed (Requirement 16.6)
            if rollback_failed:
                try:
                    self.notification_service.notify_critical_error(
                        project_id=project_id,
                        user_id=user_id,
                        migration_type='unshare',
                        error=e,
                        rollback_failed=True
                    )
                except Exception as notif_error:
                    migration_logger.log_error(notif_error, context="send_critical_notification")
            
            raise DataMigrationError("Failed to migrate project: {}".format(str(e)))
    
    def _rollback_file_migration(self, backup_state, org_id, migration_logger=None):
        """
        Rollback file moves on migration failure.
        
        This method restores files to their original locations when a
        share migration fails.
        
        Requirements: 16.3, 16.4, 24.7
        
        Args:
            backup_state (dict): Dictionary mapping datasource IDs to backup state
            org_id (int): Organization ID
            migration_logger (MigrationLogger): Logger instance (optional)
        """
        if migration_logger:
            migration_logger.log_info("Rolling back file migration for {} datasources".format(len(backup_state)))
        else:
            logger.info("Rolling back file migration for {} datasources".format(len(backup_state)))
        
        for datasource_id, state in backup_state.items():
            try:
                datasource = models.DataSource.query.get(datasource_id)
                if datasource and state.get('shared_path'):
                    # Move file back to private
                    self.file_service.move_file(
                        state['shared_path'],
                        state['private_path']
                    )
                    
                    if migration_logger:
                        migration_logger.log_rollback_operation(
                            'file_move',
                            "Datasource {}: {} -> {}".format(
                                datasource_id, state['shared_path'], state['private_path']
                            ),
                            success=True
                        )
                    
                    # Remove from shared (cleanup)
                    try:
                        self.file_service.delete_file(state['shared_path'])
                        if migration_logger:
                            migration_logger.log_rollback_operation(
                                'file_delete',
                                "Deleted shared file: {}".format(state['shared_path']),
                                success=True
                            )
                    except Exception as e:
                        if migration_logger:
                            migration_logger.log_rollback_operation(
                                'file_delete',
                                "Failed to delete shared file: {}".format(state['shared_path']),
                                success=False,
                                error=e
                            )
                        
            except Exception as e:
                if migration_logger:
                    migration_logger.log_rollback_operation(
                        'file_move',
                        "Datasource {}".format(datasource_id),
                        success=False,
                        error=e
                    )
                else:
                    logger.error("Failed to rollback datasource {}: {}".format(
                        datasource_id, str(e)
                    ))
    
    def _rollback_unshare_migration(self, backup_state, org_id, user_id, migration_logger=None):
        """
        Rollback file moves on unshare migration failure.
        
        This method restores files to their shared locations when an
        unshare migration fails.
        
        Requirements: 16.3, 16.4, 24.7
        
        Args:
            backup_state (dict): Dictionary mapping datasource IDs to backup state
            org_id (int): Organization ID
            user_id (int): User ID
            migration_logger (MigrationLogger): Logger instance (optional)
        """
        if migration_logger:
            migration_logger.log_info("Rolling back unshare migration for {} datasources".format(len(backup_state)))
        else:
            logger.info("Rolling back unshare migration for {} datasources".format(len(backup_state)))
        
        for datasource_id, state in backup_state.items():
            try:
                datasource = models.DataSource.query.get(datasource_id)
                if datasource and state.get('private_path'):
                    # Move file back to shared
                    self.file_service.move_file(
                        state['private_path'],
                        state['shared_path']
                    )
                    
                    if migration_logger:
                        migration_logger.log_rollback_operation(
                            'file_move',
                            "Datasource {}: {} -> {}".format(
                                datasource_id, state['private_path'], state['shared_path']
                            ),
                            success=True
                        )
                    
                    # Remove from private (cleanup)
                    try:
                        self.file_service.delete_file(state['private_path'])
                        if migration_logger:
                            migration_logger.log_rollback_operation(
                                'file_delete',
                                "Deleted private file: {}".format(state['private_path']),
                                success=True
                            )
                    except Exception as e:
                        if migration_logger:
                            migration_logger.log_rollback_operation(
                                'file_delete',
                                "Failed to delete private file: {}".format(state['private_path']),
                                success=False,
                                error=e
                            )
                        
            except Exception as e:
                if migration_logger:
                    migration_logger.log_rollback_operation(
                        'file_move',
                        "Datasource {}".format(datasource_id),
                        success=False,
                        error=e
                    )
                else:
                    logger.error("Failed to rollback datasource {}: {}".format(
                        datasource_id, str(e)
                    ))
    
    def _get_datasource_file_path(self, datasource):
        """
        Get the current file path for a datasource.
        
        For external datasources, the file path is stored in the VDB XML,
        not in the datasource options. This method tries multiple sources:
        1. private_file_path column (if already populated)
        2. shared_file_path column (if datasource is shared)
        3. datasource options (legacy)
        4. VDB XML (for external datasources)
        
        Also auto-populates private_file_path if found elsewhere.
        
        Args:
            datasource: DataSource object
            
        Returns:
            str: File path, or None if datasource has no file
        """
        # Check if datasource is already shared (use shared_file_path)
        if hasattr(datasource, 'is_shared') and datasource.is_shared:
            if hasattr(datasource, 'shared_file_path') and datasource.shared_file_path:
                return self._ensure_absolute_path(datasource.shared_file_path)
        
        # Check private_file_path column (primary location for private datasources)
        if hasattr(datasource, 'private_file_path') and datasource.private_file_path:
            return self._ensure_absolute_path(datasource.private_file_path)
        
        # Legacy: Check if datasource has options with file path (for backwards compatibility)
        file_path = None
        if hasattr(datasource, 'options') and datasource.options:
            if isinstance(datasource.options, dict):
                if 'file' in datasource.options:
                    file_path = datasource.options['file']
                elif 'path' in datasource.options:
                    file_path = datasource.options['path']
                elif 'file_path' in datasource.options:
                    file_path = datasource.options['file_path']
        
        # Ensure legacy paths are absolute
        if file_path:
            file_path = self._ensure_absolute_path(file_path)
        
        # For external datasources, try to extract file path from VDB
        if not file_path and hasattr(datasource, 'type') and datasource.type == 'external':
            file_path = self._get_file_path_from_vdb(datasource)
        
        # Auto-populate file paths if we found a path
        # This ensures migration can proceed for legacy datasources
        if file_path and hasattr(datasource, 'private_file_path'):
            if '/shared/' not in file_path:
                # This is a private path
                if not datasource.private_file_path:
                    datasource.private_file_path = file_path
                    logger.info("Auto-populated private_file_path for datasource '{}': {}".format(
                        datasource.name, file_path
                    ))
                    models.db.session.add(datasource)
            else:
                # This is a shared path - set both shared_file_path and private_file_path
                # so VDB migration can proceed correctly
                logger.info("Found shared path for datasource '{}', setting file paths for migration: {}".format(
                    datasource.name, file_path
                ))
                
                # Set shared_file_path if not already set
                if hasattr(datasource, 'shared_file_path') and not datasource.shared_file_path:
                    # Extract relative path (e.g., "52/shared/uploads/file.xlsx")
                    import re
                    match = re.search(r'(\d+/shared/uploads/[^/]+)$', file_path)
                    if match:
                        datasource.shared_file_path = match.group(1)
                        logger.info("Set shared_file_path for datasource '{}': {}".format(
                            datasource.name, datasource.shared_file_path
                        ))
                
                # Set private_file_path by converting shared path to private path for the datasource owner
                if not datasource.private_file_path:
                    datasource_owner_id = datasource.original_owner_id or datasource.owner
                    # Convert "/shared/" to "/{owner_id}/"
                    private_path = file_path.replace('/shared/', '/{}/'.format(datasource_owner_id))
                    # Extract relative path
                    match = re.search(r'(\d+/\d+/uploads/[^/]+)$', private_path)
                    if match:
                        datasource.private_file_path = match.group(1)
                        logger.info("Set private_file_path for datasource '{}': {}".format(
                            datasource.name, datasource.private_file_path
                        ))
                
                models.db.session.add(datasource)
        
        return file_path
    
    def _ensure_absolute_path(self, file_path):
        """
        Ensure a file path is absolute by prepending the base path if needed.
        
        Args:
            file_path: File path (may be relative or absolute)
            
        Returns:
            str: Absolute file path
        """
        if not file_path:
            return file_path
        
        # If already absolute, return as-is
        if file_path.startswith('/'):
            return file_path
        
        # Get base path
        base_path = self.file_service.base_path
        
        # Prepend base path
        full_path = "{}/{}".format(base_path, file_path)
        logger.debug("Converted relative path to absolute: {} -> {}".format(file_path, full_path))
        return full_path
    
    def _get_file_path_from_vdb(self, datasource):
        """
        Extract file path from VDB XML for external datasources.
        
        The file path is stored in the FOREIGN TABLE DDL within the VDB.
        
        Args:
            datasource: DataSource object
            
        Returns:
            str: File path, or None if not found
        """
        try:
            from redash.utils.vdb_xml_parser import VDBXMLParser
            
            # Get the user's VDB path
            org_id = datasource.org_id
            owner_id = datasource.owner
            
            logger.info("_get_file_path_from_vdb: datasource='{}', org_id={}, owner_id={}".format(
                datasource.name, org_id, owner_id
            ))
            
            if not owner_id:
                logger.warning("Datasource {} has no owner, cannot get VDB path".format(datasource.name))
                return None
            
            # Get VDB path from database
            result = models.db.session.execute(
                """
                SELECT vdb_id FROM user_vdbs 
                WHERE user_id = :user_id AND organization_id = :org_id
                """,
                {'user_id': owner_id, 'org_id': org_id}
            ).fetchone()
            
            if not result:
                logger.warning("No VDB found for user {} in org {}".format(owner_id, org_id))
                return None
            
            vdb_id = result[0]
            logger.info("Found VDB ID: {}".format(vdb_id))
            
            # Get base path from config
            base_path = '/opt/wildfly/teiidfiles/customers'
            try:
                config_result = models.db.session.execute(
                    "SELECT customer_base_path FROM teiid_config WHERE id = 1"
                ).fetchone()
                if config_result and config_result[0]:
                    base_path = config_result[0]
            except Exception as e:
                logger.debug("Could not get base path from config: {}".format(str(e)))
            
            vdb_path = "{}/{}/{}/vdb/{}-vdb.xml".format(base_path, org_id, owner_id, vdb_id)
            logger.info("VDB path: {}".format(vdb_path))
            
            # Parse VDB and extract file path
            parser = VDBXMLParser()
            xml_tree = parser.read_vdb(vdb_path)
            
            # Try to find foreign table by datasource name (with various suffixes)
            # Generate base variations
            base_variations = [
                datasource.name,
                datasource.name.replace('_XLSX', ''),
                datasource.name.replace('_CSV', ''),
                datasource.name.replace('_TXT', ''),
                datasource.name.replace(' ', '_'),
            ]
            
            # Enhanced case variations to handle mixed case scenarios
            # This fixes issues where datasource name casing doesn't match VDB table name casing
            # Example: datasource "Sales_PLAN_XLSX" should match VDB table "Sales_Plan"
            table_names_to_try = []
            for name in base_variations:
                # Original case
                table_names_to_try.append(name)
                
                # All lowercase
                table_names_to_try.append(name.lower())
                
                # All uppercase
                table_names_to_try.append(name.upper())
                
                # Title case (first letter uppercase, rest lowercase)
                table_names_to_try.append(name.title())
                
                # Mixed case with underscores preserved
                # Convert "Sales_PLAN_XLSX" to "Sales_Plan" by title-casing each part
                if '_' in name:
                    parts = name.split('_')
                    # Title case each part
                    title_parts = [part.title() for part in parts]
                    table_names_to_try.append('_'.join(title_parts))
                    
                    # Also try with first part title-cased, rest lowercase
                    if len(parts) > 1:
                        mixed_parts = [parts[0].title()] + [p.lower() for p in parts[1:]]
                        table_names_to_try.append('_'.join(mixed_parts))
                
                # Capitalize (first letter uppercase, rest as-is)
                table_names_to_try.append(name.capitalize())
            
            # Remove duplicates while preserving order
            seen = set()
            table_names_to_try = [x for x in table_names_to_try if not (x in seen or seen.add(x))]
            
            logger.info("Trying table names: {}".format(table_names_to_try))
            
            import re
            
            for table_name in table_names_to_try:
                # First try to extract as FOREIGN TABLE (for Excel files)
                ddl = parser.extract_foreign_table(xml_tree, table_name)
                logger.info("Trying FOREIGN TABLE '{}': found DDL = {}".format(table_name, bool(ddl)))
                if ddl:
                    # Extract file path from FOREIGN TABLE DDL
                    # Look for patterns like: FILE '/path/to/file.xlsx' or "teiid_excel:FILE" '34/78/uploads/file.xlsx'
                    # Try teiid_excel:FILE pattern first (for Excel files)
                    match = re.search(r'"teiid_excel:FILE"\s+\'([^\']+)\'', ddl, re.IGNORECASE)
                    if not match:
                        # Try generic FILE pattern
                        match = re.search(r"FILE\s+'([^']+)'", ddl, re.IGNORECASE)
                    if match:
                        file_path = match.group(1)
                        logger.info("Extracted file path from FOREIGN TABLE for datasource '{}': {}".format(
                            datasource.name, file_path
                        ))
                        
                        # If the path is relative (doesn't start with /), prepend the base path
                        if file_path and not file_path.startswith('/'):
                            full_path = "{}/{}".format(base_path, file_path)
                            logger.info("Converted relative path to absolute: {} -> {}".format(
                                file_path, full_path
                            ))
                            return full_path
                        
                        return file_path
                
                # If not found as FOREIGN TABLE, try to extract as VIEW (for CSV/TXT files)
                view_ddl = parser.extract_view(xml_tree, table_name)
                logger.info("Trying VIEW '{}': found DDL = {}".format(table_name, bool(view_ddl)))
                if view_ddl:
                    # Extract file path from VIEW DDL
                    # Look for pattern: getTextFiles('path/to/file.txt')
                    match = re.search(r'getTextFiles\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)', view_ddl, re.IGNORECASE)
                    if match:
                        file_path = match.group(1)
                        logger.info("Extracted file path from VIEW for datasource '{}': {}".format(
                            datasource.name, file_path
                        ))
                        
                        # If the path is relative (doesn't start with /), prepend the base path
                        if file_path and not file_path.startswith('/'):
                            full_path = "{}/{}".format(base_path, file_path)
                            logger.info("Converted relative path to absolute: {} -> {}".format(
                                file_path, full_path
                            ))
                            return full_path
                        
                        return file_path
            
            logger.warning("Could not find foreign table or view for datasource '{}' in VDB".format(datasource.name))
            
            # FALLBACK: Try to find the table in the shared VDB
            # This handles the case where a non-owner uploaded a file to a shared project
            # The table definition exists in the shared VDB, not the user's private VDB
            logger.info("Trying fallback: checking shared VDB for datasource '{}'".format(datasource.name))
            
            try:
                import os
                
                # First try the shared VDB directory (new structure)
                shared_vdb_dir = os.path.join(base_path, str(org_id), 'shared', 'vdb')
                shared_vdb_path = None
                
                if os.path.exists(shared_vdb_dir) and os.path.isdir(shared_vdb_dir):
                    vdb_files = [f for f in os.listdir(shared_vdb_dir) if f.endswith('-vdb.xml')]
                    if vdb_files:
                        shared_vdb_path = os.path.join(shared_vdb_dir, vdb_files[0])
                        logger.info("Found shared VDB in shared/vdb directory: {}".format(shared_vdb_path))
                
                # Fallback to organization_vdbs table
                if not shared_vdb_path:
                    shared_vdb_result = models.db.session.execute(
                        """
                        SELECT vdb_id FROM organization_vdbs 
                        WHERE organization_id = :org_id
                        """,
                        {'org_id': org_id}
                    ).fetchone()
                    
                    if shared_vdb_result:
                        shared_vdb_id = shared_vdb_result[0]
                        shared_vdb_path = "{}/{}/vdb/{}-vdb.xml".format(base_path, org_id, shared_vdb_id)
                        logger.info("Found shared VDB from organization_vdbs: {}".format(shared_vdb_path))
                
                if shared_vdb_path and os.path.exists(shared_vdb_path):
                    logger.info("Checking shared VDB: {}".format(shared_vdb_path))
                    shared_xml_tree = parser.read_vdb(shared_vdb_path)
                    
                    for table_name in table_names_to_try:
                        # Try FOREIGN TABLE
                        ddl = parser.extract_foreign_table(shared_xml_tree, table_name)
                        if ddl:
                            match = re.search(r'"teiid_excel:FILE"\s+\'([^\']+)\'', ddl, re.IGNORECASE)
                            if not match:
                                match = re.search(r"FILE\s+'([^']+)'", ddl, re.IGNORECASE)
                            if match:
                                file_path = match.group(1)
                                logger.info("Found file path in shared VDB FOREIGN TABLE: {}".format(file_path))
                                if file_path and not file_path.startswith('/'):
                                    return "{}/{}".format(base_path, file_path)
                                return file_path
                        
                        # Try VIEW
                        view_ddl = parser.extract_view(shared_xml_tree, table_name)
                        if view_ddl:
                            match = re.search(r'getTextFiles\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)', view_ddl, re.IGNORECASE)
                            if match:
                                file_path = match.group(1)
                                logger.info("Found file path in shared VDB VIEW: {}".format(file_path))
                                if file_path and not file_path.startswith('/'):
                                    return "{}/{}".format(base_path, file_path)
                                return file_path
                    
                    logger.warning("Table not found in shared VDB either")
                else:
                    logger.warning("Shared VDB file does not exist or not found")
            except Exception as shared_e:
                logger.warning("Failed to check shared VDB: {}".format(str(shared_e)))
                import traceback
                logger.warning("Shared VDB fallback traceback: {}".format(traceback.format_exc()))
            
            return None
            
        except Exception as e:
            logger.warning("Failed to extract file path from VDB for datasource '{}': {}".format(
                datasource.name, str(e)
            ))
            import traceback
            logger.warning("Traceback: {}".format(traceback.format_exc()))
            return None
    
    def _mark_datasource_as_shared(self, datasource, private_path, shared_path):
        """
        Mark a datasource as shared and update paths.
        
        Requirements: 3.1-3.5
        
        Args:
            datasource: DataSource object
            private_path (str): Original private file path
            shared_path (str): New shared file path
        """
        # Update datasource columns directly (not options)
        datasource.is_shared = True
        datasource.private_file_path = private_path
        datasource.shared_file_path = shared_path
        
        # Also update options if they exist (for backwards compatibility)
        if hasattr(datasource, 'options') and datasource.options:
            if isinstance(datasource.options, dict):
                datasource.options['is_shared'] = True
                datasource.options['private_file_path'] = private_path
                datasource.options['shared_file_path'] = shared_path
                datasource.options['file'] = shared_path  # Update current file path
        
        # Mark as modified to trigger SQLAlchemy update
        models.db.session.add(datasource)
    
    def _mark_datasource_as_private(self, datasource, private_path):
        """
        Mark a datasource as private and update paths.
        
        Args:
            datasource: DataSource object
            private_path (str): New private file path
        """
        # Update datasource columns directly (not options)
        datasource.is_shared = False
        datasource.private_file_path = private_path
        datasource.shared_file_path = None  # Clear shared path
        
        # Also update options if they exist (for backwards compatibility)
        if hasattr(datasource, 'options') and datasource.options:
            if isinstance(datasource.options, dict):
                datasource.options['is_shared'] = False
                datasource.options['file'] = private_path  # Update current file path
                
                # Remove shared path references
                if 'shared_file_path' in datasource.options:
                    del datasource.options['shared_file_path']
        
        # Mark as modified to trigger SQLAlchemy update
        models.db.session.add(datasource)
    
    def _mark_query_as_shared(self, query):
        """
        Mark a query as shared.
        
        Requirements: 8.1-8.5
        
        Args:
            query: Query object
        """
        # Update query is_shared flag directly
        # This ensures routing logic can use query.is_shared for correct VDB selection
        query.is_shared = True
        
        # Also update query options for backwards compatibility
        if not query.options:
            query.options = {}
        
        query.options['is_shared'] = True
        
        # Mark as modified to trigger SQLAlchemy update
        models.db.session.add(query)
    
    def _mark_query_as_private(self, query):
        """
        Mark a query as private.
        
        Args:
            query: Query object
        """
        # Update query is_shared flag directly
        # This ensures routing logic can use query.is_shared for correct VDB selection
        query.is_shared = False
        
        # Also update query options for backwards compatibility
        if not query.options:
            query.options = {}
        
        query.options['is_shared'] = False
        
        # Mark as modified to trigger SQLAlchemy update
        models.db.session.add(query)
    
    def _redeploy_vdbs(self, org_id, user_id, migration_logger=None):
        """
        Redeploy both private and shared VDBs to Teiid.
        
        After updating VDB XML files, we need to redeploy them to Teiid
        so the changes take effect.
        
        Requirements: 6.1-6.5, 24.4
        
        Args:
            org_id (int): Organization ID
            user_id (int): User ID
            migration_logger (MigrationLogger): Logger instance (optional)
            
        Raises:
            Exception: If redeployment fails
        """
        from redash.services.vdb_management import VDBManagementService, VDBProvisioningError
        
        try:
            vdb_service = VDBManagementService()
            
            # Redeploy user VDB
            if migration_logger:
                migration_logger.log_info("Redeploying private VDB for user {}".format(user_id))
            else:
                logger.info("Redeploying private VDB for user {}".format(user_id))
            
            try:
                result = vdb_service.redeploy_user_vdb(user_id)
                if result.get('success'):
                    if migration_logger:
                        migration_logger.log_vdb_operation('redeploy', 'private', success=True)
                    else:
                        logger.info("Successfully redeployed private VDB")
                else:
                    error_msg = result.get('error', 'Unknown error')
                    if migration_logger:
                        migration_logger.log_warning("Private VDB redeployment returned error: {}".format(error_msg))
                    else:
                        logger.warning("Private VDB redeployment returned error: {}".format(error_msg))
            except VDBProvisioningError as e:
                if migration_logger:
                    migration_logger.log_warning("Failed to redeploy private VDB: {}".format(str(e)))
                else:
                    logger.warning("Failed to redeploy private VDB: {}".format(str(e)))
            
            # Redeploy shared VDB
            if migration_logger:
                migration_logger.log_info("Redeploying shared VDB for organization {}".format(org_id))
            else:
                logger.info("Redeploying shared VDB for organization {}".format(org_id))
            
            try:
                result = vdb_service.redeploy_shared_vdb(org_id)
                if result.get('success'):
                    if migration_logger:
                        migration_logger.log_vdb_operation('redeploy', 'shared', success=True)
                    else:
                        logger.info("Successfully redeployed shared VDB")
                else:
                    error_msg = result.get('error', 'Unknown error')
                    if migration_logger:
                        migration_logger.log_warning("Shared VDB redeployment returned error: {}".format(error_msg))
                    else:
                        logger.warning("Shared VDB redeployment returned error: {}".format(error_msg))
            except VDBProvisioningError as e:
                if migration_logger:
                    migration_logger.log_warning("Failed to redeploy shared VDB: {}".format(str(e)))
                else:
                    logger.warning("Failed to redeploy shared VDB: {}".format(str(e)))
                    
        except Exception as e:
            error_msg = "VDB redeployment failed: {}".format(str(e))
            if migration_logger:
                migration_logger.log_error(e, context="vdb_redeployment")
            else:
                logger.error(error_msg)
            # Don't raise - allow migration to complete even if redeployment fails
            # VDBs can be manually redeployed later
