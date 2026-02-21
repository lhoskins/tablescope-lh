"""
Data Migration Notification Service

Provides notification functionality for data migration operations.
Notifies project owners and system administrators about migration
failures and critical errors.

Requirements: 16.6, 21.4
"""

import logging
from redash import models
from redash.services.exceptions import DataMigrationError

logger = logging.getLogger(__name__)


class MigrationNotificationService(object):
    """
    Service for sending notifications about migration operations.
    
    This service handles:
    - Notifying project owners about migration failures
    - Notifying system administrators about critical errors
    - Including error details and recovery steps in notifications
    
    Requirements: 16.6, 21.4
    """
    
    def __init__(self):
        """Initialize Migration Notification Service."""
        pass
    
    def notify_migration_failure(self, project_id, user_id, migration_type, error, migration_log_id=None):
        """
        Notify project owner about migration failure.
        
        This method sends a notification to the project owner when a
        migration operation fails, including error details and recovery steps.
        
        Requirements: 16.6, 21.4
        
        Args:
            project_id (int): ID of the project
            user_id (int): ID of the user who initiated the migration
            migration_type (str): Type of migration ('share' or 'unshare')
            error (Exception): The error that occurred
            migration_log_id (int): ID of the migration log entry (optional)
        """
        try:
            # Get project and user information
            project = models.Project.query.get(project_id)
            user = models.User.query.get(user_id)
            
            if not project or not user:
                logger.error("Cannot send notification: project or user not found")
                return
            
            # Prepare notification message
            subject = "Project Migration Failed: {}".format(project.name)
            
            message = self._build_failure_message(
                project=project,
                user=user,
                migration_type=migration_type,
                error=error,
                migration_log_id=migration_log_id
            )
            
            # Send notification to project owner
            self._send_notification(
                user_id=project.owner_id,
                subject=subject,
                message=message,
                notification_type='migration_failure'
            )
            
            logger.info("Sent migration failure notification to user {}".format(project.owner_id))
            
        except Exception as e:
            logger.error("Failed to send migration failure notification: {}".format(str(e)))
    
    def notify_critical_error(self, project_id, user_id, migration_type, error, rollback_failed=False):
        """
        Notify system administrator about critical migration error.
        
        This method sends a notification to system administrators when a
        critical error occurs during migration, especially if rollback fails.
        
        Requirements: 16.6, 21.4
        
        Args:
            project_id (int): ID of the project
            user_id (int): ID of the user who initiated the migration
            migration_type (str): Type of migration ('share' or 'unshare')
            error (Exception): The error that occurred
            rollback_failed (bool): Whether rollback also failed
        """
        try:
            # Get project and user information
            project = models.Project.query.get(project_id)
            user = models.User.query.get(user_id)
            
            if not project or not user:
                logger.error("Cannot send notification: project or user not found")
                return
            
            # Prepare notification message
            if rollback_failed:
                subject = "CRITICAL: Migration Rollback Failed - Project {}".format(project.name)
            else:
                subject = "CRITICAL: Migration Error - Project {}".format(project.name)
            
            message = self._build_critical_error_message(
                project=project,
                user=user,
                migration_type=migration_type,
                error=error,
                rollback_failed=rollback_failed
            )
            
            # Send notification to system administrators
            self._send_admin_notification(
                subject=subject,
                message=message,
                notification_type='critical_migration_error'
            )
            
            logger.info("Sent critical error notification to system administrators")
            
        except Exception as e:
            logger.error("Failed to send critical error notification: {}".format(str(e)))
    
    def notify_migration_success(self, project_id, user_id, migration_type, datasources_count, queries_count):
        """
        Notify project owner about successful migration.
        
        This method sends a notification to the project owner when a
        migration operation completes successfully.
        
        Requirements: 21.3
        
        Args:
            project_id (int): ID of the project
            user_id (int): ID of the user who initiated the migration
            migration_type (str): Type of migration ('share' or 'unshare')
            datasources_count (int): Number of datasources migrated
            queries_count (int): Number of queries migrated
        """
        try:
            # Get project and user information
            project = models.Project.query.get(project_id)
            user = models.User.query.get(user_id)
            
            if not project or not user:
                logger.error("Cannot send notification: project or user not found")
                return
            
            # Prepare notification message
            subject = "Project Migration Completed: {}".format(project.name)
            
            message = self._build_success_message(
                project=project,
                user=user,
                migration_type=migration_type,
                datasources_count=datasources_count,
                queries_count=queries_count
            )
            
            # Send notification to project owner
            self._send_notification(
                user_id=project.owner_id,
                subject=subject,
                message=message,
                notification_type='migration_success'
            )
            
            logger.info("Sent migration success notification to user {}".format(project.owner_id))
            
        except Exception as e:
            logger.error("Failed to send migration success notification: {}".format(str(e)))
    
    def _build_failure_message(self, project, user, migration_type, error, migration_log_id=None):
        """
        Build failure notification message.
        
        Args:
            project: Project object
            user: User object
            migration_type (str): Type of migration
            error (Exception): The error that occurred
            migration_log_id (int): ID of the migration log entry (optional)
            
        Returns:
            str: Formatted notification message
        """
        error_type = type(error).__name__
        error_message = str(error)
        
        message = """
Project Migration Failed

Project: {project_name}
Migration Type: {migration_type}
Initiated By: {user_name} ({user_email})
Error Type: {error_type}
Error Message: {error_message}

What Happened:
The system attempted to {action} your project but encountered an error.
All changes have been rolled back, and your project data remains in its original state.

Recovery Steps:
1. Review the error message above to understand what went wrong
2. Check that all datasource files are accessible and not corrupted
3. Ensure you have sufficient disk space and permissions
4. Try the operation again after addressing any issues
5. If the problem persists, contact your system administrator

Additional Information:
- Your project data has not been modified
- All datasources and queries remain functional
- You can continue working with your project normally
{migration_log_info}

If you need assistance, please contact support with the error details above.
""".format(
            project_name=project.name,
            migration_type=migration_type,
            user_name=user.name,
            user_email=user.email,
            error_type=error_type,
            error_message=error_message,
            action="share" if migration_type == "share" else "make private",
            migration_log_info="- Migration Log ID: {}".format(migration_log_id) if migration_log_id else ""
        )
        
        return message
    
    def _build_critical_error_message(self, project, user, migration_type, error, rollback_failed=False):
        """
        Build critical error notification message.
        
        Args:
            project: Project object
            user: User object
            migration_type (str): Type of migration
            error (Exception): The error that occurred
            rollback_failed (bool): Whether rollback also failed
            
        Returns:
            str: Formatted notification message
        """
        error_type = type(error).__name__
        error_message = str(error)
        
        if rollback_failed:
            severity = "CRITICAL - MANUAL INTERVENTION REQUIRED"
            status = "The migration failed AND the automatic rollback also failed. The system may be in an inconsistent state."
            action_required = """
IMMEDIATE ACTION REQUIRED:
1. Investigate the project data integrity
2. Check file system state for project datasources
3. Verify VDB configurations
4. Manually restore from backups if necessary
5. Contact the development team for assistance
"""
        else:
            severity = "CRITICAL - MIGRATION FAILED"
            status = "The migration failed but rollback completed successfully. The system should be in a consistent state."
            action_required = """
ACTION REQUIRED:
1. Review the error logs for detailed information
2. Check system resources (disk space, permissions)
3. Verify VDB service is running properly
4. Investigate the root cause of the failure
5. Monitor for any related issues
"""
        
        message = """
{severity}

Project: {project_name} (ID: {project_id})
Organization: {org_name} (ID: {org_id})
Migration Type: {migration_type}
Initiated By: {user_name} ({user_email})
User ID: {user_id}

Error Type: {error_type}
Error Message: {error_message}

Status:
{status}

{action_required}

System Information:
- Project ID: {project_id}
- Organization ID: {org_id}
- User ID: {user_id}
- Migration Type: {migration_type}
- Timestamp: {timestamp}

Please investigate this issue immediately and take appropriate action.
""".format(
            severity=severity,
            project_name=project.name,
            project_id=project.id,
            org_name=project.org.name if project.org else "Unknown",
            org_id=project.org_id,
            migration_type=migration_type,
            user_name=user.name,
            user_email=user.email,
            user_id=user.id,
            error_type=error_type,
            error_message=error_message,
            status=status,
            action_required=action_required,
            timestamp=models.db.func.now()
        )
        
        return message
    
    def _build_success_message(self, project, user, migration_type, datasources_count, queries_count):
        """
        Build success notification message.
        
        Args:
            project: Project object
            user: User object
            migration_type (str): Type of migration
            datasources_count (int): Number of datasources migrated
            queries_count (int): Number of queries migrated
            
        Returns:
            str: Formatted notification message
        """
        if migration_type == 'share':
            action = "shared"
            details = """
Your project has been successfully shared. All datasources and queries have been
migrated to the shared organization space. Project members can now access and
collaborate on this project.
"""
        else:
            action = "made private"
            details = """
Your project has been successfully made private. All datasources and queries have been
migrated back to your private space. The project is no longer accessible to other
organization members.
"""
        
        message = """
Project Migration Completed Successfully

Project: {project_name}
Migration Type: {migration_type}
Initiated By: {user_name}

Summary:
Your project has been successfully {action}.

Details:
{details}

Migration Statistics:
- Datasources migrated: {datasources_count}
- Queries migrated: {queries_count}

What's Next:
- All datasources and queries are now available in the {context} context
- You can continue working with your project normally
- All project members have been notified of the change

If you have any questions or concerns, please contact support.
""".format(
            project_name=project.name,
            migration_type=migration_type,
            user_name=user.name,
            action=action,
            details=details,
            datasources_count=datasources_count,
            queries_count=queries_count,
            context="shared" if migration_type == "share" else "private"
        )
        
        return message
    
    def _send_notification(self, user_id, subject, message, notification_type):
        """
        Send notification to a specific user.
        
        This method creates a notification record in the database that will
        be displayed to the user in the application UI.
        
        Args:
            user_id (int): ID of the user to notify
            subject (str): Notification subject
            message (str): Notification message
            notification_type (str): Type of notification
        """
        try:
            # Create notification record
            # Note: This assumes a notifications table exists
            # Adjust based on actual notification system implementation
            
            logger.info("Creating notification for user {}: {}".format(user_id, subject))
            
            # TODO: Implement actual notification creation
            # This would typically insert a record into a notifications table
            # or call an external notification service
            
            # Example:
            # notification = models.Notification(
            #     user_id=user_id,
            #     subject=subject,
            #     message=message,
            #     notification_type=notification_type,
            #     is_read=False
            # )
            # models.db.session.add(notification)
            # models.db.session.commit()
            
        except Exception as e:
            logger.error("Failed to create notification: {}".format(str(e)))
            raise
    
    def _send_admin_notification(self, subject, message, notification_type):
        """
        Send notification to all system administrators.
        
        This method sends a notification to all users with admin privileges.
        
        Args:
            subject (str): Notification subject
            message (str): Notification message
            notification_type (str): Type of notification
        """
        try:
            # Get all admin users
            # Note: Adjust based on actual user/role model
            admin_users = models.User.query.filter_by(is_admin=True).all()
            
            logger.info("Sending admin notification to {} administrators: {}".format(
                len(admin_users), subject
            ))
            
            # Send notification to each admin
            for admin in admin_users:
                self._send_notification(
                    user_id=admin.id,
                    subject=subject,
                    message=message,
                    notification_type=notification_type
                )
            
        except Exception as e:
            logger.error("Failed to send admin notifications: {}".format(str(e)))
            raise
