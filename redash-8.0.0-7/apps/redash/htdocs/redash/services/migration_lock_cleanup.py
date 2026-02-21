"""
Migration Lock Cleanup Utility

This script provides utilities for cleaning up stale migration locks.
It can be run as a scheduled task or manually by administrators.

Requirements: 22.5
"""

import logging
from redash.services.migration_lock import MigrationLockService

logger = logging.getLogger(__name__)


def cleanup_stale_locks(timeout_seconds=None):
    """
    Clean up stale migration locks.
    
    This function finds all migrations that have been in 'started' status
    for longer than the timeout period and releases their locks.
    
    This should be run periodically as a maintenance task (e.g., via cron).
    
    Requirements: 22.5
    
    Args:
        timeout_seconds (int): Timeout in seconds (default: 300)
        
    Returns:
        int: Number of locks released
    """
    lock_service = MigrationLockService(lock_timeout=timeout_seconds)
    
    try:
        released_count = lock_service.cleanup_stale_locks(timeout_seconds)
        
        if released_count > 0:
            logger.info("Successfully cleaned up {} stale migration locks".format(released_count))
        else:
            logger.info("No stale migration locks found")
        
        return released_count
        
    except Exception as e:
        logger.error("Failed to cleanup stale locks: {}".format(str(e)))
        raise


def force_release_project_lock(project_id):
    """
    Force release a migration lock for a specific project.
    
    This should only be used by administrators when a migration has
    clearly failed or timed out but the lock was not released.
    
    Requirements: 22.5
    
    Args:
        project_id (int): Project ID to unlock
        
    Returns:
        bool: True if lock was released
    """
    lock_service = MigrationLockService()
    
    try:
        result = lock_service.force_release_lock(project_id)
        
        if result:
            logger.info("Successfully force-released lock for project {}".format(project_id))
        else:
            logger.warning("Lock was not held for project {}".format(project_id))
        
        return result
        
    except Exception as e:
        logger.error("Failed to force-release lock for project {}: {}".format(
            project_id, str(e)
        ))
        raise


if __name__ == '__main__':
    """
    Run cleanup when executed as a script.
    
    Usage:
        python -m redash.services.migration_lock_cleanup
    """
    import sys
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Check for command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == 'cleanup':
            # Run cleanup with optional timeout
            timeout = int(sys.argv[2]) if len(sys.argv) > 2 else None
            released = cleanup_stale_locks(timeout)
            print("Cleaned up {} stale locks".format(released))
            
        elif sys.argv[1] == 'force-release':
            # Force release a specific project lock
            if len(sys.argv) < 3:
                print("Usage: python -m redash.services.migration_lock_cleanup force-release <project_id>")
                sys.exit(1)
            
            project_id = int(sys.argv[2])
            result = force_release_project_lock(project_id)
            
            if result:
                print("Successfully released lock for project {}".format(project_id))
            else:
                print("Lock was not held for project {}".format(project_id))
        else:
            print("Unknown command: {}".format(sys.argv[1]))
            print("Available commands: cleanup, force-release")
            sys.exit(1)
    else:
        # Default: run cleanup
        released = cleanup_stale_locks()
        print("Cleaned up {} stale locks".format(released))
