# redash/handlers/roles.py

"""
Role management API endpoints for RBAC security model.

This module provides endpoints for:
- Listing available roles
- Getting user role assignments
- Assigning roles to users
- Removing role assignments
- Assigning project admins
"""

import logging
from flask import request, jsonify
from flask_restful import abort
from sqlalchemy.exc import IntegrityError

from redash.handlers.base import BaseResource
from redash.handlers.permissions import require_permission, require_project_access
from redash.models import db, User
from redash.models.users import Group
from redash.models.role_assignment import RoleAssignment
from redash.models.organizations import Organization
from redash.services.permission_service import PermissionService

logger = logging.getLogger(__name__)


def get_current_organization():
    """Fetches the organization for the current request based on the slug."""
    slug = request.view_args.get('org_slug') or 'default'
    organization = Organization.query.filter_by(slug=slug).first()
    if not organization:
        raise Exception("Organization not found")
    return organization


class RolesListResource(BaseResource):
    """
    Resource for listing all available roles with their permissions.
    
    GET /api/roles
    Returns list of all available roles with permissions and descriptions.
    """
    
    def get(self):
        """
        List all available roles with permissions.
        
        Returns:
            JSON array of role objects with:
            - role_type: Role identifier
            - name: Human-readable role name
            - permissions: List of permission strings
            - description: Role description
            
        Requirements: 1.1, 3.1, 4.1, 5.1, 6.1, 7.1
        """
        try:
            # Define role descriptions
            role_descriptions = {
                Group.ROLE_DEFAULT: "Default role for all users. Can create and manage own resources.",
                Group.ROLE_DESIGNER: "Can edit queries in shared projects. Inherits all default permissions.",
                Group.ROLE_PROJECT_OWNER: "Automatically assigned when creating a project. Full control over owned projects.",
                Group.ROLE_PROJECT_ADMIN: "Assigned to help manage specific projects. Cannot delete projects.",
                Group.ROLE_ORG_ADMIN: "Organization-wide administrator. Can manage all projects and users within the organization.",
                Group.ROLE_SUPER_ADMIN: "Platform administrator. Can manage VDBs and provision organizations."
            }
            
            # Define role names
            role_names = {
                Group.ROLE_DEFAULT: "Default",
                Group.ROLE_DESIGNER: "Designer",
                Group.ROLE_PROJECT_OWNER: "Project Owner",
                Group.ROLE_PROJECT_ADMIN: "Project Admin",
                Group.ROLE_ORG_ADMIN: "Organization Admin",
                Group.ROLE_SUPER_ADMIN: "Super Admin"
            }
            
            # Build response with all roles
            roles = []
            for role_type, permissions in Group.ROLE_PERMISSIONS.items():
                role_data = {
                    'role_type': role_type,
                    'name': role_names.get(role_type, role_type.replace('_', ' ').title()),
                    'permissions': permissions,
                    'description': role_descriptions.get(role_type, ''),
                    'is_project_specific': role_type in [Group.ROLE_PROJECT_OWNER, Group.ROLE_PROJECT_ADMIN]
                }
                roles.append(role_data)
            
            logger.info("Successfully fetched %d roles", len(roles))
            return jsonify(roles)
            
        except Exception as e:
            logger.error("Error fetching roles: %s", str(e), exc_info=True)
            return {"error": "Failed to fetch roles: {}".format(str(e))}, 500


class UserRolesResource(BaseResource):
    """
    Resource for managing role assignments for a specific user.
    
    GET /api/users/{user_id}/roles
    Returns all role assignments for the user.
    
    POST /api/users/{user_id}/roles
    Assigns a role to the user.
    """
    
    def get(self, user_id):
        """
        Get all role assignments for a user.
        
        Returns both global and project-specific roles.
        Requires organization admin or super admin permission.
        
        Args:
            user_id (int): User ID
            
        Returns:
            JSON array of role assignment objects
            
        Requirements: 8.1-8.5
        """
        try:
            # Check if current user has permission to view role assignments
            # Organization admins can view roles in their org
            # Super admins can view all roles
            if not (PermissionService.has_organization_admin_role(self.current_user) or
                    PermissionService.has_super_admin_role(self.current_user)):
                abort(403, message="Insufficient permissions to view user roles")
            
            org = get_current_organization()
            
            # Verify the target user exists and belongs to the same organization
            # (unless current user is super admin)
            target_user = User.query.get(user_id)
            if not target_user:
                abort(404, message="User not found")
            
            if not PermissionService.has_super_admin_role(self.current_user):
                if target_user.org_id != org.id:
                    abort(404, message="User not found")
            
            # Get all role assignments for the user
            role_assignments = RoleAssignment.get_user_roles(user_id, org.id)
            
            # Build response with role details
            result = []
            for assignment in role_assignments:
                assignment_dict = assignment.to_dict()
                
                # Add role name and description
                role_names = {
                    Group.ROLE_DEFAULT: "Default",
                    Group.ROLE_DESIGNER: "Designer",
                    Group.ROLE_PROJECT_OWNER: "Project Owner",
                    Group.ROLE_PROJECT_ADMIN: "Project Admin",
                    Group.ROLE_ORG_ADMIN: "Organization Admin",
                    Group.ROLE_SUPER_ADMIN: "Super Admin"
                }
                assignment_dict['role_name'] = role_names.get(
                    assignment.role_type,
                    assignment.role_type.replace('_', ' ').title()
                )
                
                # Add resource details if project-specific
                if assignment.resource_type == 'project' and assignment.resource_id:
                    from redash.models.project import Project
                    project = Project.query.get(assignment.resource_id)
                    if project:
                        assignment_dict['resource_name'] = project.name
                
                result.append(assignment_dict)
            
            logger.info("Successfully fetched %d role assignments for user %s", len(result), user_id)
            return jsonify(result)
            
        except Exception as e:
            logger.error("Error fetching user roles: %s", str(e), exc_info=True)
            return {"error": "Failed to fetch user roles: {}".format(str(e))}, 500
    
    def post(self, user_id):
        """
        Assign a role to a user.
        
        Requires organization admin or super admin permission.
        Invalidates permission cache for the user after assignment.
        
        Args:
            user_id (int): User ID
            
        Request body:
            {
                "role_type": "designer",  # Required
                "resource_type": "project",  # Optional, for project-specific roles
                "resource_id": 123  # Optional, for project-specific roles
            }
            
        Returns:
            JSON object with created role assignment
            
        Requirements: 6.3, 8.4
        """
        try:
            # Check if current user has permission to assign roles
            if not (PermissionService.has_organization_admin_role(self.current_user) or
                    PermissionService.has_super_admin_role(self.current_user)):
                abort(403, message="Insufficient permissions to assign roles")
            
            org = get_current_organization()
            
            # Verify the target user exists and belongs to the same organization
            target_user = User.query.filter_by(id=user_id, org_id=org.id).first()
            if not target_user:
                abort(404, message="User not found in this organization")
            
            # Get request data
            data = request.get_json()
            if not data:
                abort(400, message="No data provided")
            
            role_type = data.get('role_type')
            if not role_type:
                abort(400, message="role_type is required")
            
            # Validate role type
            if role_type not in Group.ROLE_PERMISSIONS:
                abort(400, message="Invalid role type: {}".format(role_type))
            
            resource_type = data.get('resource_type')
            resource_id = data.get('resource_id')
            
            # Validate project-specific roles
            if role_type in [Group.ROLE_PROJECT_OWNER, Group.ROLE_PROJECT_ADMIN]:
                if not resource_type or not resource_id:
                    abort(400, message="Project-specific roles require resource_type and resource_id")
                if resource_type != 'project':
                    abort(400, message="Invalid resource_type for project-specific role")
                
                # Verify project exists and belongs to the organization
                from redash.models.project import Project
                project = Project.query.filter_by(id=resource_id, org_id=org.id).first()
                if not project:
                    abort(404, message="Project not found")
            
            # Check if assignment already exists
            existing = RoleAssignment.query.filter(
                RoleAssignment.user_id == user_id,
                RoleAssignment.role_type == role_type,
                RoleAssignment.resource_type == resource_type,
                RoleAssignment.resource_id == resource_id
            ).first()
            
            if existing:
                return {"message": "Role assignment already exists", "role_assignment": existing.to_dict()}, 200
            
            # Create role assignment
            assignment = RoleAssignment.assign_role(
                user_id=user_id,
                role_type=role_type,
                org_id=org.id,
                resource_type=resource_type,
                resource_id=resource_id,
                assigned_by_id=self.current_user.id
            )
            
            db.session.commit()
            
            # Log role assignment to audit log
            from redash.services.audit_service import audit_role_change
            resource = None
            if resource_type == 'project' and resource_id:
                from redash.models.project import Project
                resource = Project.query.get(resource_id)
            audit_role_change(self.current_user, target_user, role_type, 'assigned', resource)
            
            # Invalidate permission cache for the user
            PermissionService.invalidate_permission_cache(user_id=user_id)
            
            logger.info(
                "Role %s assigned to user %s by user %s",
                role_type, user_id, self.current_user.id
            )
            
            return assignment.to_dict(), 201
            
        except IntegrityError as e:
            db.session.rollback()
            logger.error("IntegrityError assigning role: %s", str(e), exc_info=True)
            return {"error": "Role assignment already exists"}, 400
        except Exception as e:
            db.session.rollback()
            logger.error("Error assigning role: %s", str(e), exc_info=True)
            return {"error": "Failed to assign role: {}".format(str(e))}, 500


class UserRoleResource(BaseResource):
    """
    Resource for managing a specific role assignment.
    
    DELETE /api/users/{user_id}/roles/{role_id}
    Removes a role assignment from the user.
    """
    
    def delete(self, user_id, role_id):
        """
        Remove a role assignment from a user.
        
        Requires organization admin or super admin permission.
        Invalidates permission cache for the user after removal.
        
        Args:
            user_id (int): User ID
            role_id (int): Role assignment ID
            
        Returns:
            204 No Content on success
            
        Requirements: 6.3, 8.4
        """
        try:
            # Check if current user has permission to remove roles
            if not (PermissionService.has_organization_admin_role(self.current_user) or
                    PermissionService.has_super_admin_role(self.current_user)):
                abort(403, message="Insufficient permissions to remove roles")
            
            org = get_current_organization()
            
            # Find the role assignment
            assignment = RoleAssignment.query.filter_by(
                id=role_id,
                user_id=user_id
            ).first()
            
            if not assignment:
                abort(404, message="Role assignment not found")
            
            # Verify organization boundary (unless super admin)
            if not PermissionService.has_super_admin_role(self.current_user):
                if assignment.org_id != org.id:
                    abort(404, message="Role assignment not found")
            
            # Prevent removing the last organization admin
            if assignment.role_type == Group.ROLE_ORG_ADMIN:
                # Count other org admins in the organization
                other_admins = RoleAssignment.query.filter(
                    RoleAssignment.org_id == assignment.org_id,
                    RoleAssignment.role_type == Group.ROLE_ORG_ADMIN,
                    RoleAssignment.id != role_id
                ).count()
                
                if other_admins == 0:
                    abort(400, message="Cannot remove the last organization admin")
            
            # Log role removal to audit log before deleting
            from redash.services.audit_service import audit_role_change
            target_user = User.query.get(user_id)
            resource = None
            if assignment.resource_type == 'project' and assignment.resource_id:
                from redash.models.project import Project
                resource = Project.query.get(assignment.resource_id)
            audit_role_change(self.current_user, target_user, assignment.role_type, 'removed', resource)
            
            # Remove the assignment
            db.session.delete(assignment)
            db.session.commit()
            
            # Invalidate permission cache for the user
            PermissionService.invalidate_permission_cache(user_id=user_id)
            
            logger.info(
                "Role assignment %s removed from user %s by user %s",
                role_id, user_id, self.current_user.id
            )
            
            return '', 204
            
        except Exception as e:
            db.session.rollback()
            logger.error("Error removing role: %s", str(e), exc_info=True)
            return {"error": "Failed to remove role: {}".format(str(e))}, 500


class ProjectAdminsResource(BaseResource):
    """
    Resource for assigning project admin role to users.
    
    POST /api/projects/{project_id}/admins
    Assigns project_admin role to a user for a specific project.
    """
    
    @require_project_access('manage')
    def post(self, project_id, project_obj=None):
        """
        Assign project_admin role to a user for a specific project.
        
        Requires project owner, organization admin, or super admin permission.
        Records assignment in role_assignments table with resource_type='project'.
        Invalidates permission cache for the assigned user.
        
        Args:
            project_id (int): Project ID
            project_obj: Project object (provided by decorator)
            
        Request body:
            {
                "user_id": 123  # Required
            }
            
        Returns:
            JSON object with created role assignment
            
        Requirements: 5.1-5.9
        """
        try:
            org = get_current_organization()
            project = project_obj  # Provided by decorator
            
            # Get request data
            data = request.get_json()
            if not data:
                abort(400, message="No data provided")
            
            target_user_id = data.get('user_id')
            if not target_user_id:
                abort(400, message="user_id is required")
            
            # Verify the target user exists and belongs to the same organization
            target_user = User.query.filter_by(id=target_user_id, org_id=org.id).first()
            if not target_user:
                abort(404, message="User not found in this organization")
            
            # Check if user is already a project admin for this project
            existing = RoleAssignment.query.filter(
                RoleAssignment.user_id == target_user_id,
                RoleAssignment.role_type == Group.ROLE_PROJECT_ADMIN,
                RoleAssignment.resource_type == 'project',
                RoleAssignment.resource_id == project_id
            ).first()
            
            if existing:
                return {"message": "User is already a project admin", "role_assignment": existing.to_dict()}, 200
            
            # Create role assignment
            assignment = RoleAssignment.assign_role(
                user_id=target_user_id,
                role_type=Group.ROLE_PROJECT_ADMIN,
                org_id=org.id,
                resource_type='project',
                resource_id=project_id,
                assigned_by_id=self.current_user.id
            )
            
            # Also ensure user is a project member
            from redash.models.project import ProjectMember
            member = ProjectMember.query.filter_by(
                project_id=project_id,
                user_id=target_user_id
            ).first()
            
            if not member:
                # Add as project member with admin role
                member = ProjectMember(
                    project_id=project_id,
                    user_id=target_user_id,
                    role='admin',
                    added_by_id=self.current_user.id
                )
                db.session.add(member)
            else:
                # Update existing member to admin role
                member.role = 'admin'
                db.session.add(member)
            
            db.session.commit()
            
            # Log role assignment to audit log
            from redash.services.audit_service import audit_role_change
            audit_role_change(self.current_user, target_user, Group.ROLE_PROJECT_ADMIN, 'assigned', project)
            
            # Invalidate permission cache for the user
            PermissionService.invalidate_permission_cache(user_id=target_user_id)
            
            logger.info(
                "Project admin role assigned to user %s for project %s by user %s",
                target_user_id, project_id, self.current_user.id
            )
            
            return assignment.to_dict(), 201
            
        except IntegrityError as e:
            db.session.rollback()
            logger.error("IntegrityError assigning project admin: %s", str(e), exc_info=True)
            return {"error": "Role assignment already exists"}, 400
        except Exception as e:
            db.session.rollback()
            logger.error("Error assigning project admin: %s", str(e), exc_info=True)
            return {"error": "Failed to assign project admin: {}".format(str(e))}, 500
