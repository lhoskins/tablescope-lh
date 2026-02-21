"""
Migration Lock Service

Provides database-level locking to prevent concurrent migrations for the same project.
Uses PostgreSQL row-level locks (SELECT FOR UPDATE) for transaction-scoped locking
that works correctly with connection pooling.

Requirements: 22.1, 22.2, 22.3, 22.4, 22.5
"""

import logging
import datetime
from contextlib import contextmanager
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import OperationalError
from redash import models
from redash.services.exceptions import MigrationInProgressError

logger = logging.getLogger(__name__)


class MigrationLockService(object):
    """
    Service for managing migration locks using PostgreSQL row-level locks.
    
    Row-level locks are transaction-scoped and automatically released when
    the transaction commits or rolls back. This works correctly with
    connection pooling, unlike session-scoped advisory locks.
    
    Requirements: 22.1, 22.2, 22.3, 22.4, 22.5
    """
    
    # Lock timeout in seconds (Requirement 22.5)
    DEFAULT_LOCK_TIMEOUT = 300  # 5 minutes
    
    def __init__(self, lock_timeout=None):
        """
        Initialize Migration Lock Service.
        
        Args:
            lock_timeout (int): Lock timeout in seconds (default: 300)
        """
        self.lock_timeout = lock_timeout or self.DEFAULT_LOCK_TIMEOUT
    
    def acquire_lock(self, project_id):
        """
        Acquire a row-level lock for a project migration.
        
        This method uses SELECT FOR UPDATE NOWAIT to acquire an exclusive
        row-level lock on the migration log. The lock is automatically
        released when the transaction commits or rolls back.
        
        Requirements: 22.1, 22.2, 22.3
        
        Args:
            project_id (int): Project ID to lock
            
        Returns:
            bool: True if lock was acquired
            
        Raises:
            MigrationInProgressError: If lock is already held by active migration
        """
        from redash.models.data_migration_log import DataMigrationLog
        
        try:
            # Try to acquire row-level lock on any active migration for this project
            # with_for_update(nowait=True) will raise OperationalError if lock is held
            active_migration = DataMigrationLog.query.filter_by(
                project_id=project_id,
                status='started'
            ).with_for_update(nowait=True).first()
            
            if active_migration:
                # We got the lock! Check if migration is stale
                if self._is_migration_stale(active_migration):
                    logger.warning(
                        "Stale migration detected for project {}: migration_id={}, elapsed={}s".format(
                            project_id,
                            active_migration.id,
                            self._get_elapsed_seconds(active_migration.started_at)
                        )
                    )
                    # Mark as failed and continue
                    self._mark_migration_failed(active_migration)
                    models.db.session.flush()
                else:
                    # Migration is still active (not stale)
                    logger.warning(
                        "Migration already in progress for project {}: migration_id={}".format(
                            project_id, active_migration.id
                        )
                    )
                    raise MigrationInProgressError(
                        "A migration is already in progress for this project. "
                        "Please wait for it to complete or retry later.",
                        project_id=project_id,
                        existing_migration_id=active_migration.id
                    )
            
            # No active migration found, we can proceed
            logger.info("Acquired migration lock for project {}".format(project_id))
            return True
            
        except OperationalError as e:
            # Lock is held by another transaction
            error_msg = str(e)
            if 'could not obtain lock' in error_msg.lower() or 'lock_not_available' in error_msg.lower():
                logger.warning(
                    "Could not acquire lock for project {} - another migration is in progress".format(project_id)
                )
                raise MigrationInProgressError(
                    "A migration is already in progress for this project. "
                    "Please wait for it to complete or retry later.",
                    project_id=project_id
                )
            else:
                # Some other operational error
                logger.error("Operational error acquiring lock for project {}: {}".format(project_id, error_msg))
                raise
    
    def release_lock(self, project_id):
        """
        Release the migration lock for a project.
        
        With row-level locking, the lock is automatically released when
        the transaction commits or rolls back. This method is kept for
        API compatibility but doesn't need to do anything explicit.
        
        Requirements: 22.4
        
        Args:
            project_id (int): Project ID to unlock
        """
        # Lock is automatically released on transaction commit/rollback
        # No explicit action needed
        logger.info("Migration lock for project {} will be released on transaction commit".format(project_id))
    
    def release_all_locks(self):
        """
        Release all locks held by the current transaction.
        
        With row-level locking, all locks are automatically released when
        the transaction commits or rolls back. This method is kept for
        API compatibility.
        
        Requirements: 22.4
        """
        # All locks automatically released on transaction commit/rollback
        logger.info("All migration locks will be released on transaction commit")
    
    @contextmanager
    def lock(self, project_id):
        """
        Context manager for acquiring and releasing migration locks.
        
        This provides a convenient way to ensure locks are properly managed
        within a transaction context.
        
        Requirements: 22.1, 22.2, 22.3, 22.4
        
        Usage:
            with lock_service.lock(project_id):
                # Perform migration
                pass
        
        Args:
            project_id (int): Project ID to lock
            
        Yields:
            None
            
        Raises:
            MigrationInProgressError: If lock cannot be acquired
        """
        try:
            # Acquire lock
            self.acquire_lock(project_id)
            yield
        finally:
            # Lock automatically released on transaction commit/rollback
            # No explicit release needed
            pass
    
    def check_lock_timeout(self, project_id, started_at):
        """
        Check if a migration has exceeded the timeout period.
        
        This method checks if a migration has been running longer than
        the configured timeout.
        
        Requirements: 22.5
        
        Args:
            project_id (int): Project ID
            started_at (datetime): When the migration started
            
        Returns:
            bool: True if migration has timed out
        """
        if not started_at:
            return False
        
        # Calculate elapsed time
        now = datetime.datetime.now(started_at.tzinfo) if started_at.tzinfo else datetime.datetime.now()
        elapsed = (now - started_at).total_seconds()
        
        if elapsed > self.lock_timeout:
            logger.warning(
                "Migration timeout detected for project {}: elapsed={}s, timeout={}s".format(
                    project_id, elapsed, self.lock_timeout
                )
            )
            return True
        
        return False
    
    def force_release_lock(self, project_id):
        """
        Force release a lock by marking the migration as failed.
        
        With row-level locking, we can't force-release locks held by other
        transactions. Instead, we mark the migration as failed in the database,
        which will allow the next attempt to proceed.
        
        Requirements: 22.5
        
        Args:
            project_id (int): Project ID to unlock
            
        Returns:
            bool: True if migration was marked as failed
        """
        from redash.models.data_migration_log import DataMigrationLog
        
        try:
            # Find and mark stale migrations as failed
            stale_migration = DataMigrationLog.query.filter_by(
                project_id=project_id,
                status='started'
            ).first()
            
            if stale_migration and self._is_migration_stale(stale_migration):
                logger.warning("Force releasing lock for project {} by marking migration as failed".format(project_id))
                self._mark_migration_failed(stale_migration)
                models.db.session.commit()
                return True
            
            return False
            
        except Exception as e:
            logger.error("Error force releasing lock for project {}: {}".format(project_id, str(e)))
            models.db.session.rollback()
            return False
    
    def _is_migration_stale(self, migration_log):
        """
        Check if a migration is stale (older than timeout).
        
        Args:
            migration_log (DataMigrationLog): Migration log to check
            
        Returns:
            bool: True if migration is stale
        """
        if not migration_log or not migration_log.started_at:
            return False
        
        elapsed_seconds = self._get_elapsed_seconds(migration_log.started_at)
        return elapsed_seconds > self.lock_timeout
    
    def _get_elapsed_seconds(self, started_at):
        """
        Get elapsed seconds since a migration started.
        
        Args:
            started_at (datetime): When migration started
            
        Returns:
            float: Elapsed seconds
        """
        if not started_at:
            return 0
        
        now = datetime.datetime.now(started_at.tzinfo) if started_at.tzinfo else datetime.datetime.now()
        return (now - started_at).total_seconds()
    
    def _mark_migration_failed(self, migration_log):
        """
        Mark a stale migration as failed.
        
        This updates the migration log to indicate that the migration
        timed out or was interrupted.
        
        Args:
            migration_log (DataMigrationLog): Migration log to mark as failed
        """
        try:
            migration_log.status = 'failed'
            migration_log.completed_at = datetime.datetime.now()
            migration_log.error_message = 'Migration timed out or was interrupted. Automatically marked as failed.'
            # Don't commit here - let the caller handle transaction
            
            logger.info(
                "Marked stale migration {} as failed for project {}".format(
                    migration_log.id, migration_log.project_id
                )
            )
        except Exception as e:
            logger.error("Failed to mark migration as failed: {}".format(str(e)))
            raise
    
    def cleanup_stale_locks(self, timeout_seconds=None):
        """
        Clean up stale locks for migrations that have timed out.
        
        This method finds all migrations that have been in 'started' status
        for longer than the timeout period and marks them as failed.
        
        This should be run periodically as a maintenance task.
        
        Requirements: 22.5
        
        Args:
            timeout_seconds (int): Timeout in seconds (default: use instance timeout)
            
        Returns:
            int: Number of stale migrations cleaned up
        """
        from redash.models.data_migration_log import DataMigrationLog
        
        timeout = timeout_seconds or self.lock_timeout
        cutoff_time = datetime.datetime.now() - datetime.timedelta(seconds=timeout)
        
        # Find stale migrations
        stale_migrations = DataMigrationLog.query.filter(
            DataMigrationLog.status == 'started',
            DataMigrationLog.started_at < cutoff_time
        ).all()
        
        cleaned_count = 0
        for migration in stale_migrations:
            try:
                # Mark migration as failed
                migration.status = 'failed'
                migration.completed_at = datetime.datetime.now()
                migration.error_message = 'Migration timed out after {} seconds'.format(timeout)
                models.db.session.commit()
                
                cleaned_count += 1
                logger.info(
                    "Cleaned up stale migration for project {}: migration_id={}".format(
                        migration.project_id, migration.id
                    )
                )
            except Exception as e:
                logger.error(
                    "Failed to cleanup stale migration for project {}: {}".format(
                        migration.project_id, str(e)
                    )
                )
                models.db.session.rollback()
        
        if cleaned_count > 0:
            logger.info("Cleaned up {} stale migrations".format(cleaned_count))
        
        return cleaned_count
