"""
Audit Service

Provides helper functions for logging security-relevant actions.
"""

import logging
import json
from flask import request, has_request_context
from redash.models import db
from redash.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


def audit_log(action, user=None, org_id=None, resource=None, resource_type=None, 
              resource_id=None, success=True, details=None):
    """
    Log a security-relevant action to the audit log.
    
    This function captures request context (IP address, user agent) and logs
    the action to the database. It handles exceptions gracefully to ensure
    that logging failures don't break the application.
    
    Args:
        action (str): Type of action being logged (e.g., 'permission_denied', 'role_assigned')
        user: User object or user ID (optional)
        org_id (int): Organization ID (optional, will be inferred from user if not provided)
        resource: Resource object (Query, DataSource, Project, etc.) (optional)
        resource_type (str): Type of resource (optional, will be inferred from resource if not provided)
        resource_id (int): ID of resource (optional, will be inferred from resource if not provided)
        success (bool): Whether the action was successful (default: True)
        details (dict): Additional context to log as JSON (optional)
    
    Returns:
        AuditLog: The created audit log entry, or None if logging failed
    
    Example:
        # Log a permission denial
        audit_log('permission_denied', user=current_user, resource=query, success=False)
        
        # Log a role assignment
        audit_log('role_assigned', user=admin_user, org_id=org.id, 
                  details={'target_user_id': target_user.id, 'role': 'designer'})
    """
    try:
        # Extract user_id and org_id
        user_id = None
        if user is not None:
            if isinstance(user, int):
                user_id = user
                # If org_id not provided and we only have user_id, we can't infer org_id
            else:
                user_id = user.id
                if org_id is None and hasattr(user, 'org_id'):
                    org_id = user.org_id
        
        # Extract resource information
        if resource is not None:
            if resource_type is None:
                resource_type = resource.__class__.__name__
            if resource_id is None and hasattr(resource, 'id'):
                resource_id = resource.id
        
        # Capture request context if available
        ip_address = None
        user_agent = None
        if has_request_context():
            try:
                ip_address = request.remote_addr
                if request.user_agent:
                    user_agent = request.user_agent.string
            except Exception as e:
                logger.debug("Failed to capture request context: %s", str(e))
        
        # Convert details to JSON string if provided
        details_json = None
        if details is not None:
            try:
                details_json = json.dumps(details)
            except Exception as e:
                logger.warning("Failed to serialize audit log details: %s", str(e))
                details_json = json.dumps({'error': 'Failed to serialize details'})
        
        # Create audit log entry
        audit_entry = AuditLog(
            action=action,
            success=success,
            user_id=user_id,
            org_id=org_id,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details_json
        )
        
        db.session.add(audit_entry)
        db.session.commit()
        
        logger.info(
            "Audit log created: action=%s, user_id=%s, org_id=%s, resource=%s:%s, success=%s",
            action, user_id, org_id, resource_type, resource_id, success
        )
        
        return audit_entry
        
    except Exception as e:
        # Log the error but don't fail the request
        logger.error("Failed to create audit log entry: %s", str(e), exc_info=True)
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


def audit_permission_check(user, permission, resource=None, granted=False):
    """
    Log a permission check to the audit log.
    
    This is a convenience wrapper around audit_log() specifically for
    permission checks.
    
    Args:
        user: User object
        permission (str): Permission being checked
        resource: Resource object (optional)
        granted (bool): Whether permission was granted
    """
    action = 'permission_granted' if granted else 'permission_denied'
    details = {'permission': permission}
    
    return audit_log(
        action=action,
        user=user,
        resource=resource,
        success=granted,
        details=details
    )


def audit_role_change(admin_user, target_user, role_type, action_type, resource=None):
    """
    Log a role assignment or removal to the audit log.
    
    Args:
        admin_user: User performing the role change
        target_user: User whose role is being changed
        role_type (str): Type of role (e.g., 'designer', 'project_admin')
        action_type (str): 'assigned' or 'removed'
        resource: Resource object for project-specific roles (optional)
    """
    action = 'role_assigned' if action_type == 'assigned' else 'role_removed'
    details = {
        'target_user_id': target_user.id,
        'target_user_email': target_user.email,
        'role_type': role_type
    }
    
    return audit_log(
        action=action,
        user=admin_user,
        org_id=admin_user.org_id,
        resource=resource,
        success=True,
        details=details
    )


def audit_project_membership_change(admin_user, target_user, project, action_type):
    """
    Log a project membership change to the audit log.
    
    Args:
        admin_user: User performing the membership change
        target_user: User being added/removed from project
        project: Project object
        action_type (str): 'added' or 'removed'
    """
    action = 'project_member_added' if action_type == 'added' else 'project_member_removed'
    details = {
        'target_user_id': target_user.id,
        'target_user_email': target_user.email,
        'project_name': project.name
    }
    
    return audit_log(
        action=action,
        user=admin_user,
        org_id=project.org_id,
        resource=project,
        success=True,
        details=details
    )


def audit_project_role_change(admin_user, target_user, project, old_role, new_role):
    """
    Log a project role change to the audit log.
    
    Args:
        admin_user: User performing the role change
        target_user: User whose role is being changed
        project: Project object
        old_role (str): Previous role (e.g., 'member', 'admin')
        new_role (str): New role (e.g., 'admin', 'owner')
    """
    details = {
        'target_user_id': target_user.id,
        'target_user_email': target_user.email,
        'project_name': project.name,
        'old_role': old_role,
        'new_role': new_role
    }
    
    return audit_log(
        action='project_role_changed',
        user=admin_user,
        org_id=project.org_id,
        resource=project,
        success=True,
        details=details
    )
