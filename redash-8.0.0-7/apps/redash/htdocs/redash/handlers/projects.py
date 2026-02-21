import json
import requests
from flask import request, jsonify
from flask_restful import abort
from werkzeug.exceptions import HTTPException
from datetime import datetime
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from sqlalchemy.dialects.postgresql import Any, array
from redash.handlers.base import BaseResource
from redash.permissions import require_admin, require_permission, require_object_modify_permission, require_admin_or_owner
from redash.handlers.permissions import require_project_access
from redash.models import Project, ProjectMember, ProjectDataSource, DataSource, DataSourceApproval, User, db, Query, Dashboard, TableScope
from redash.models.organizations import Organization
from redash.utils import json_dumps, json_loads
from sqlalchemy.orm.exc import NoResultFound
import os
import logging

# Set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

# Load environment variables
REDASH_API_URL = os.environ.get("REDASH_API_URL")
REDASH_API_KEY = os.environ.get("REDASH_API_KEY")

def get_current_organization():
    """Fetches the organization for the current request based on the slug."""
    slug = request.view_args.get('org_slug') or 'default'
    organization = Organization.query.filter_by(slug=slug).first()
    if not organization:
        raise Exception("Organization not found")
    return organization

class ProjectListResource(BaseResource):
    def get(self):
        """List all projects accessible to the current user."""
        try:
            from redash.services.access_control import AccessControl
            from redash.services.permission_service import PermissionService
            
            org = get_current_organization()
            
            # Get accessible projects using AccessControl service
            accessible_projects_query = AccessControl.get_accessible_projects(
                self.current_user, org
            )
            projects = accessible_projects_query.all()
            
            # Check if migration status should be included (optional query parameter)
            include_migration_status = request.args.get('include_migration_status', 'false').lower() == 'true'
            
            # Enrich project data with ownership and membership information
            result = []
            for project in projects:
                project_dict = project.to_dict(include_migration_status=include_migration_status)
                
                # Add ownership indicator
                project_dict['is_owner'] = PermissionService.is_project_owner(
                    self.current_user, project
                )
                
                # Add admin indicator
                project_dict['is_admin'] = PermissionService.is_project_admin(
                    self.current_user, project
                )
                
                # Add member indicator
                project_dict['is_member'] = PermissionService.is_project_member(
                    self.current_user, project
                )
                
                # Add management permission indicator
                project_dict['can_manage'] = PermissionService.can_manage_project(
                    self.current_user, project
                )
                
                # Add delete permission indicator
                project_dict['can_delete'] = PermissionService.can_delete_project(
                    self.current_user, project
                )
                
                result.append(project_dict)
            
            return jsonify(result)
        except Exception as e:
            logger.error("Error fetching projects: %s", str(e), exc_info=True)
            return {"error": str(e)}, 500

    def post(self):
        """Create a new project with the current user as the owner."""
        from redash.handlers.permissions import require_permission
        from redash.models.role_assignment import RoleAssignment
        from redash.models.users import Group
        from redash.services.permission_service import PermissionService
        
        # All authenticated users can create projects
        logger.info("PROJECT CREATE: user_id=%s, email=%s",
                   self.current_user.id, self.current_user.email)
        
        data = request.get_json()
        org = get_current_organization()
        if not org:
            return {"error": "No organization found"}, 404

        name = data.get("name")
        if not name:
            abort(400, message="The 'name' field is required.")

        # Create project with current user as owner
        project = Project(
            org_id=org.id,
            name=name,
            description=data.get("description", ""),
            type=data.get("type", "default_type"),
            owner_id=self.current_user.id,
        )

        try:
            db.session.add(project)
            db.session.flush()  # Flush to get project ID
            
            # Automatically assign project_owner role to the creator
            role_assignment = RoleAssignment(
                user_id=self.current_user.id,
                role_type=Group.ROLE_PROJECT_OWNER,
                resource_type='project',
                resource_id=project.id,
                org_id=org.id,
                assigned_by_id=self.current_user.id
            )
            db.session.add(role_assignment)
            
            # Also add the user as a project member with 'owner' role
            project_member = ProjectMember(
                project_id=project.id,
                user_id=self.current_user.id,
                role='owner',
                added_by_id=self.current_user.id
            )
            db.session.add(project_member)
            
            db.session.commit()
            
            # Invalidate permission cache for the user
            PermissionService.invalidate_permission_cache(user_id=self.current_user.id)
            
            logger.info(
                "Project %s created by user %s with project_owner role",
                project.id, self.current_user.id
            )
        except Exception as e:
            db.session.rollback()
            logger.error("Error creating project: %s", str(e), exc_info=True)
            return {"error": "Failed to create project: {}".format(str(e))}, 500

        return project.to_dict(), 201

class ProjectResource(BaseResource):
    def get(self, project_id):
        """Get a specific project with migration status."""
        logger.info("Fetching project with ID %s", project_id)
        try:
            org = get_current_organization()
            project = Project.query.filter(Project.org_id == org.id, Project.id == project_id).first_or_404()
            
            # Include migration status in the response
            project_dict = project.to_dict(include_migration_status=True)
            
            logger.debug("Project details: %s", project_dict)
            return jsonify(project_dict)
        except Exception as e:
            logger.error("Error fetching project %s: %s", project_id, str(e), exc_info=True)
            return {"error": "Failed to fetch project: {}".format(str(e))}, 500

    def put(self, project_id):
        """Update a specific project."""
        from redash.handlers.permissions import require_project_access
        from redash.services.permission_service import PermissionService
        
        logger.info("Updating project with ID %s", project_id)
        
        try:
            org = get_current_organization()
            project = Project.query.filter(Project.org_id == org.id, Project.id == project_id).first_or_404()
            
            # Check if user can manage the project
            if not PermissionService.can_manage_project(self.current_user, project):
                abort(403, message="Insufficient permissions to edit this project")
            
            # Get update data
            data = request.get_json()
            if not data:
                abort(400, message="No data provided")
            
            # Update allowed fields
            if 'name' in data:
                name = data['name'].strip()
                if not name:
                    abort(400, message="Project name cannot be empty")
                project.name = name
            
            if 'description' in data:
                project.description = data['description']
            
            if 'type' in data:
                project.type = data['type']
            
            db.session.add(project)
            db.session.commit()
            
            logger.info("Project %s updated successfully by user %s", project_id, self.current_user.id)
            return jsonify(project.to_dict())
            
        except Exception as e:
            db.session.rollback()
            logger.error("Error updating project %s: %s", project_id, str(e), exc_info=True)
            return {"error": "Failed to update project: {}".format(str(e))}, 500

    def delete(self, project_id):
        """Delete a specific project, handling dependencies."""
        from redash.services.permission_service import PermissionService
        from redash.models.role_assignment import RoleAssignment
        
        logger.info("Attempting to delete project with ID %s", project_id)
        try:
            org = get_current_organization()
            project = Project.query.filter(Project.org_id == org.id, Project.id == project_id).first_or_404()

            # Check if user can delete the project
            # Only project owners, organization admins, and super admins can delete
            # Project admins cannot delete projects
            if not PermissionService.can_delete_project(self.current_user, project):
                abort(403, message="Insufficient permissions to delete this project. Only project owners and organization admins can delete projects.")

            # --- Final Deletion Logic ---
            
            # Use db.session.query() for TableScope
            logger.info("Un-assigning table scopes from project %s", project_id)
            db.session.query(TableScope).filter_by(project_id=project_id).update({"project_id": None})

            # Un-assign this project from any dashboards
            logger.info("Un-assigning dashboards from project %s", project_id)
            Dashboard.query.filter_by(project_id=project_id).update({"project_id": None})

            # Un-assign this project from any queries
            logger.info("Un-assigning queries from project %s", project_id)
            queries_to_update = Query.query.filter(Query.project_id.contains([int(project_id)])).all()
            for query in queries_to_update:
                updated_project_ids = [pid for pid in query.project_id if pid != int(project_id)]
                query.project_id = updated_project_ids if updated_project_ids else None
                db.session.add(query)

            # Delete role assignments for this project
            logger.info("Deleting role assignments for project %s", project_id)
            RoleAssignment.query.filter_by(
                resource_type='project',
                resource_id=project_id
            ).delete()

            # Finally, delete the project itself.
            # Its direct members and data_sources will be deleted by the cascade.
            db.session.delete(project)
            db.session.commit()
            
            # Invalidate permission cache for all users who were members
            # This ensures their cached permissions are updated
            members = ProjectMember.query.filter_by(project_id=project_id).all()
            for member in members:
                PermissionService.invalidate_permission_cache(user_id=member.user_id)

            logger.info("Successfully deleted project with ID %s", project_id)
            return '', 204
        except Exception as e:
            db.session.rollback()
            logger.error("Error deleting project %s: %s", project_id, str(e), exc_info=True)
            return {"error": "Failed to delete project: {}".format(str(e))}, 500


class ProjectMigrationStatusResource(BaseResource):
    """
    Resource for retrieving migration progress and status.
    
    Requirements: 21.1, 21.2, 21.3, 21.4
    """
    
    @require_project_access('view')
    def get(self, project_id, user_id=None, project_obj=None):
        """
        Get the current migration status and progress for a project.
        
        Returns the most recent migration log entry with progress information,
        including current step, percentage complete, and any error details.
        
        Requirements: 21.1, 21.2, 21.3, 21.4
        
        Args:
            project_id (int): ID of the project
            
        Returns:
            dict: Migration status information including:
                - status: Current migration status ('started', 'completed', 'failed', 'rolled_back', or 'none')
                - current_step: Name of the current migration step
                - progress_percentage: Percentage complete (0-100)
                - completed_steps: Number of completed steps
                - total_steps: Total number of steps
                - migration_type: Type of migration ('share' or 'unshare')
                - error_message: Error details if migration failed
                - started_at: When migration started
                - completed_at: When migration completed (if applicable)
        """
        from redash.models.data_migration_log import DataMigrationLog
        
        try:
            # Get the most recent migration log for this project
            migration_log = DataMigrationLog.query.filter_by(
                project_id=project_id
            ).order_by(
                DataMigrationLog.started_at.desc()
            ).first()
            
            if not migration_log:
                # No migration has been performed for this project
                return {
                    'status': 'none',
                    'message': 'No migration has been performed for this project'
                }, 200
            
            # Return migration status with progress information (Requirements: 21.1, 21.2)
            response = migration_log.to_dict()
            
            # Add estimated time remaining if migration is in progress (Requirement: 21.4)
            if migration_log.status == 'started' and migration_log.started_at:
                from datetime import datetime, timedelta
                
                elapsed_time = datetime.utcnow() - migration_log.started_at
                
                # Estimate time remaining based on progress
                if migration_log.progress_percentage > 0:
                    total_estimated_time = elapsed_time / (migration_log.progress_percentage / 100.0)
                    remaining_time = total_estimated_time - elapsed_time
                    
                    # Convert to seconds for easier consumption
                    response['estimated_time_remaining_seconds'] = int(remaining_time.total_seconds())
                    response['elapsed_time_seconds'] = int(elapsed_time.total_seconds())
                else:
                    response['estimated_time_remaining_seconds'] = None
                    response['elapsed_time_seconds'] = int(elapsed_time.total_seconds())
            
            return response, 200
            
        except Exception as e:
            logger.error("Error fetching migration status for project %s: %s", project_id, str(e), exc_info=True)
            return {"error": "Failed to fetch migration status: {}".format(str(e))}, 500


class ProjectMembersResource(BaseResource):
    @require_project_access('view')
    def get(self, project_id, user_id=None, project_obj=None):
        """Get project members with roles and audit information."""
        logger.info("Fetching members for project %s", project_id)
        
        try:
            # Project object is already validated and available from decorator
            project = project_obj if project_obj else Project.query.get(project_id)
            
            # If user_id is provided, return single member (for DELETE endpoint)
            if user_id:
                member = ProjectMember.query.filter_by(
                    project_id=project_id,
                    user_id=user_id
                ).first_or_404()
                
                member_dict = {
                    'user_id': member.user_id,
                    'user': member.user.to_dict() if member.user else None,
                    'role': member.role,
                    'added_at': member.added_at.isoformat() if member.added_at else None,
                    'added_by_id': member.added_by_id,
                    'added_by': member.added_by.to_dict() if member.added_by else None
                }
                return jsonify(member_dict)
            
            # Return all members with roles and audit info
            members_data = []
            for member in project.members:
                member_dict = {
                    'user_id': member.user_id,
                    'user': member.user.to_dict() if member.user else None,
                    'role': member.role,
                    'added_at': member.added_at.isoformat() if member.added_at else None,
                    'added_by_id': member.added_by_id,
                    'added_by': member.added_by.to_dict() if member.added_by else None
                }
                members_data.append(member_dict)
            
            logger.info("Successfully fetched %d members for project %s", len(members_data), project_id)
            return jsonify(members_data)
            
        except Exception as e:
            logger.error("Error fetching project members: %s", str(e), exc_info=True)
            return {"error": "Failed to fetch project members: {}".format(str(e))}, 500

    @require_project_access('manage')
    def post(self, project_id, user_id=None, project_obj=None):
        """Add a member to the project."""
        from redash.services.permission_service import PermissionService
        
        logger.info("Adding member to project %s", project_id)
        
        try:
            org = get_current_organization()
            # Project is already validated by decorator
            project = project_obj if project_obj else Project.query.filter(
                Project.org_id == org.id,
                Project.id == project_id
            ).first_or_404()
            
            # Permission check is now handled by the @require_project_access('manage') decorator
            # The decorator validates: project owner, project admin, or organization admin
            
            data = request.get_json()
            new_user_id = data.get("user_id")
            if not new_user_id:
                abort(400, message="The 'user_id' field is required.")
            
            # Verify the user exists and belongs to the same organization
            new_user = User.query.filter_by(id=new_user_id, org_id=org.id).first()
            if not new_user:
                abort(404, message="User not found in this organization.")
            
            # Check if user is already a member
            existing_member = ProjectMember.query.filter_by(
                project_id=project_id,
                user_id=new_user_id
            ).first()
            
            if existing_member:
                logger.info("User %s is already a member of project %s", new_user_id, project_id)
                # Return success with existing member data instead of error
                # This makes the operation idempotent - adding an existing member is not an error
                member_dict = {
                    'user_id': existing_member.user_id,
                    'user': existing_member.user.to_dict() if existing_member.user else None,
                    'role': existing_member.role,
                    'added_at': existing_member.added_at.isoformat() if existing_member.added_at else None,
                    'added_by_id': existing_member.added_by_id,
                    'added_by': existing_member.added_by.to_dict() if existing_member.added_by else None,
                    'already_member': True  # Flag to indicate this user was already a member
                }
                return member_dict, 200  # Return 200 instead of 400
            
            # Check if this is the first member being added (making project shared)
            # Count existing members (excluding the owner if they're not in the members table)
            current_member_count = ProjectMember.query.filter_by(project_id=project_id).count()
            
            # DEBUG: Comprehensive logging to diagnose trigger condition
            logger.error("=" * 80)
            logger.error("MIGRATION TRIGGER CHECK")
            logger.error("=" * 80)
            logger.error("Project ID: %s", project_id)
            logger.error("New user being added: %s", new_user_id)
            logger.error("Current user (adding member): %s", self.current_user.id)
            logger.error("Current member count BEFORE adding: %s", current_member_count)
            logger.error("Trigger condition (count <= 1): %s", current_member_count <= 1)
            logger.error("Will trigger migration: %s", "YES" if current_member_count <= 1 else "NO")
            
            # Log all current members for debugging
            existing_members = ProjectMember.query.filter_by(project_id=project_id).all()
            logger.error("Existing members:")
            for member in existing_members:
                logger.error("  - User ID: %s, Role: %s, Added: %s", member.user_id, member.role, member.added_at)
            logger.error("=" * 80)
            
            logger.info("Current member count for project %s: %s", project_id, current_member_count)
            
            # If this is the first member being added (project is becoming shared), migrate data
            if current_member_count <= 1:  # 0 or 1 member (just owner)
                logger.error("MIGRATION TRIGGERED! Starting migration for project %s", project_id)
                logger.info("First member being added to project %s, triggering data migration to shared state", project_id)
                
                try:
                    from redash.services.data_migration import DataMigrationOrchestrator
                    
                    orchestrator = DataMigrationOrchestrator()
                    
                    # Migrate project data to shared folder and shared VDB
                    orchestrator.migrate_project_to_shared(project_id, self.current_user.id)
                    
                    logger.info(
                        "Project data migrated successfully to shared state: project_id=%s, initiated_by=%s",
                        project_id, self.current_user.id
                    )
                    
                except Exception as e:
                    error_msg = "Failed to migrate project data to shared state: {}".format(str(e))
                    logger.error(error_msg, exc_info=True)
                    # CRITICAL: Rollback any failed transaction to clear the error state
                    # This ensures the subsequent INSERT can proceed
                    try:
                        db.session.rollback()
                        logger.info("Rolled back failed migration transaction")
                    except Exception as rollback_error:
                        logger.error("Error during rollback: %s", str(rollback_error))
                    # Don't fail the member addition, but log the error
                    # Admin can manually retry migration
                    logger.warning("Member addition will proceed despite migration failure")
                    # Store error for potential user notification
                    # This allows the member to be added even if migration fails
            else:
                # Migration not triggered because project already has multiple members
                logger.error("MIGRATION NOT TRIGGERED - Project already has %s members (condition requires <= 1)", current_member_count)
                logger.info("Project %s already shared, skipping migration", project_id)
            
            # Add member with 'member' role and record who added them
            new_member = ProjectMember(
                project_id=project_id,
                user_id=new_user_id,
                role='member',
                added_by_id=self.current_user.id
            )
            db.session.add(new_member)
            db.session.commit()
            
            # Log project membership change to audit log
            # TODO: Implement audit_project_membership_change function
            # from redash.services.audit_service import audit_project_membership_change
            # audit_project_membership_change(self.current_user, new_user, project, 'added')
            
            # Invalidate permission cache for the new member
            PermissionService.invalidate_permission_cache(user_id=new_user_id)
            
            logger.info(
                "User %s added to project %s by user %s",
                new_user_id, project_id, self.current_user.id
            )
            
            # Return member data with audit info
            member_dict = {
                'user_id': new_member.user_id,
                'user': new_member.user.to_dict() if new_member.user else None,
                'role': new_member.role,
                'added_at': new_member.added_at.isoformat() if new_member.added_at else None,
                'added_by_id': new_member.added_by_id,
                'added_by': new_member.added_by.to_dict() if new_member.added_by else None
            }
            
            return member_dict, 201
            
        except HTTPException:
            # Re-raise HTTP exceptions (like abort(400, 404))
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            logger.error("Error adding project member: %s", str(e), exc_info=True)
            return {"error": "Failed to add project member: {}".format(str(e))}, 500

    @require_project_access('manage')
    def delete(self, project_id, user_id, project_obj=None):
        """Remove a member from the project."""
        from redash.services.permission_service import PermissionService
        
        logger.info("Removing user %s from project %s", user_id, project_id)
        
        try:
            # Project object is provided by the decorator and permission is already checked
            project = project_obj
            
            # Find the member
            member = ProjectMember.query.filter_by(
                project_id=project_id,
                user_id=user_id
            ).first_or_404()
            
            # Prevent removing the project owner
            if member.role == 'owner':
                logger.warning("Attempted to remove project owner (user %s) from project %s", user_id, project_id)
                abort(400, message="Cannot remove the project owner. Transfer ownership first or delete the project.")
            
            # Log project membership change to audit log before removing
            # TODO: Implement audit_project_membership_change function
            # from redash.services.audit_service import audit_project_membership_change
            # removed_user = User.query.get(user_id)
            # if removed_user:
            #     audit_project_membership_change(self.current_user, removed_user, project, 'removed')
            
            # Check if this is the last member (excluding owner)
            # Count members BEFORE deletion
            remaining_member_count = ProjectMember.query.filter_by(project_id=project_id).count()
            logger.info("Project %s has %d members before deletion", project_id, remaining_member_count)
            # After deletion, count will be remaining_member_count - 1
            # We want to trigger unshare if only owner remains (count becomes 0)
            # or if only owner + 1 other remains (count becomes 1, but that other might be owner)
            members_after_deletion = remaining_member_count - 1
            is_last_member = (members_after_deletion <= 1)
            logger.info("Project %s: is_last_member = %s (members_after_deletion=%d)", project_id, is_last_member, members_after_deletion)
            
            # Remove the member
            db.session.delete(member)
            db.session.commit()
            
            # If this was the last member (project becoming private), trigger migration
            if is_last_member:
                logger.info("Last member removed from project %s, triggering data migration to private state", project_id)
                
                try:
                    from redash.services.data_migration import DataMigrationOrchestrator
                    
                    orchestrator = DataMigrationOrchestrator()
                    
                    # Migrate project data back to private folder and private VDB
                    orchestrator.migrate_project_to_private(project_id, self.current_user.id)
                    
                    logger.info(
                        "Project data migrated successfully to private state: project_id=%s, initiated_by=%s",
                        project_id, self.current_user.id
                    )
                    
                except Exception as e:
                    error_msg = "Failed to migrate project data to private state: {}".format(str(e))
                    logger.error(error_msg, exc_info=True)
                    # CRITICAL: Rollback any failed transaction to clear the error state
                    try:
                        db.session.rollback()
                        logger.info("Rolled back failed migration transaction")
                    except Exception as rollback_error:
                        logger.error("Error during rollback: %s", str(rollback_error))
                    # Don't fail the member removal, but log the error
                    # Admin can manually retry migration
                    logger.warning("Member removal completed despite migration failure")
            
            # Invalidate permission cache for the removed member
            PermissionService.invalidate_permission_cache(user_id=user_id)
            
            logger.info(
                "User %s removed from project %s by user %s",
                user_id, project_id, self.current_user.id
            )
            
            return '', 204
            
        except HTTPException:
            # Re-raise HTTP exceptions (like abort(400))
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            logger.error("Error removing project member: %s", str(e), exc_info=True)
            return {"error": "Failed to remove project member: {}".format(str(e))}, 500

class ProjectUnshareImpactResource(BaseResource):
    """
    Resource for fetching unshare impact data.
    
    GET /api/projects/<project_id>/unshare/impact
    Returns lists of members, queries, and datasources that will be affected by unsharing.
    
    Requirements: 7.1, 7.2, 7.3
    """
    
    @require_project_access('manage')
    def get(self, project_id, user_id=None, project_obj=None):
        """
        Get impact data for unshare operation.
        
        Returns:
            - List of members who will be removed (exclude owner)
            - List of queries that will be removed from project
            - List of datasources that will be removed from project
        """
        logger.info("Fetching unshare impact data for project %s", project_id)
        
        try:
            org = get_current_organization()
            project = project_obj if project_obj else Project.query.filter(
                Project.org_id == org.id,
                Project.id == project_id
            ).first_or_404()
            
            # Verify project is currently shared
            if not project.is_shared:
                return {
                    'members': [],
                    'queries': [],
                    'datasources': []
                }, 200
            
            # Get members (exclude owner)
            members = ProjectMember.query.filter(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id != project.owner_id
            ).all()
            
            members_data = []
            for member in members:
                if member.user:
                    members_data.append({
                        'id': member.user_id,
                        'name': member.user.name,
                        'email': member.user.email
                    })
            
            # Get queries associated with this project
            queries = Query.query.filter(
                Query.project_id.any(int(project_id))
            ).all()
            
            queries_data = []
            for query in queries:
                # Check if query is owned by non-owner members
                if query.user_id != project.owner_id:
                    queries_data.append({
                        'id': query.id,
                        'name': query.name,
                        'created_by': query.user.name if query.user else 'Unknown',
                        'updated_at': query.updated_at.isoformat() if query.updated_at else None
                    })
            
            # Get datasources associated with this project
            project_datasources = ProjectDataSource.query.filter(
                ProjectDataSource.project_id == project_id
            ).all()
            
            datasources_data = []
            for pds in project_datasources:
                if pds.data_source:
                    # Check if datasource is owned by non-owner members
                    if pds.data_source.owner != project.owner_id:
                        datasources_data.append({
                            'id': pds.data_source_id,
                            'name': pds.data_source.name,
                            'type': pds.data_source.type
                        })
            
            logger.info(
                "Unshare impact for project %s: %d members, %d queries, %d datasources",
                project_id, len(members_data), len(queries_data), len(datasources_data)
            )
            
            return {
                'members': members_data,
                'queries': queries_data,
                'datasources': datasources_data
            }, 200
            
        except Exception as e:
            logger.error("Error fetching unshare impact data: %s", str(e), exc_info=True)
            return {"error": "Failed to fetch unshare impact data: {}".format(str(e))}, 500




class ProjectMemberRoleResource(BaseResource):
    """Resource for updating a project member's role."""
    
    @require_project_access('manage')
    def put(self, project_id, user_id, project_obj=None):
        """Update a project member's role."""
        from redash.services.permission_service import PermissionService
        # TODO: Implement audit_project_role_change function
        # from redash.services.audit_service import audit_project_role_change
        
        logger.info("Updating role for user %s in project %s", user_id, project_id)
        
        try:
            # Project object is provided by the decorator
            project = project_obj
            
            # Get request data
            data = request.get_json()
            if not data:
                abort(400, message="No data provided")
            
            new_role = data.get('role')
            if not new_role:
                abort(400, message="'role' field is required")
            
            # Validate role value
            valid_roles = ['owner', 'admin', 'designer', 'member']
            if new_role not in valid_roles:
                abort(400, message="Invalid role. Must be one of: {}".format(', '.join(valid_roles)))
            
            # Find the member
            member = ProjectMember.query.filter_by(
                project_id=project_id,
                user_id=user_id
            ).first()
            
            if not member:
                abort(404, message="User is not a member of this project")
            
            # Store old role for audit logging
            old_role = member.role
            
            # Permission validation based on current user's role
            current_user_member = ProjectMember.query.filter_by(
                project_id=project_id,
                user_id=self.current_user.id
            ).first()
            
            current_user_role = current_user_member.role if current_user_member else None
            
            # Check if user is organization admin or super admin
            is_org_admin = PermissionService.has_organization_admin_role(self.current_user)
            is_super_admin = PermissionService.has_super_admin_role(self.current_user)
            
            # Only Project Owners can assign the 'owner' role
            if new_role == 'owner':
                if current_user_role != 'owner' and not is_org_admin and not is_super_admin:
                    abort(403, message="Only project owners can assign the owner role")
            
            # Project Admins cannot assign the 'owner' role
            if current_user_role == 'admin' and new_role == 'owner':
                abort(403, message="Project admins cannot assign the owner role")
            
            # Prevent removing the last owner
            if old_role == 'owner' and new_role != 'owner':
                owner_count = ProjectMember.query.filter_by(
                    project_id=project_id,
                    role='owner'
                ).count()
                
                if owner_count <= 1:
                    abort(400, message="Cannot change role - project must have at least one owner")
            
            # Update the role
            member.role = new_role
            db.session.add(member)
            db.session.commit()
            
            # Log the role change to audit log
            # TODO: Implement audit_project_role_change function
            # target_user = User.query.get(user_id)
            # if target_user:
            #     audit_project_role_change(
            #         self.current_user,
            #         target_user,
            #         project,
            #         old_role,
            #         new_role
            #     )
            
            # Invalidate permission cache for the user whose role was changed
            PermissionService.invalidate_permission_cache(user_id=user_id)
            
            logger.info(
                "Role updated for user %s in project %s: %s -> %s by user %s",
                user_id, project_id, old_role, new_role, self.current_user.id
            )
            
            # Return updated member data
            member_dict = {
                'user_id': member.user_id,
                'user': member.user.to_dict() if member.user else None,
                'role': member.role,
                'added_at': member.added_at.isoformat() if member.added_at else None,
                'added_by_id': member.added_by_id,
                'added_by': member.added_by.to_dict() if member.added_by else None,
                'updated_at': datetime.utcnow().isoformat()
            }
            
            return jsonify(member_dict)
            
        except Exception as e:
            db.session.rollback()
            logger.error("Error updating project member role: %s", str(e), exc_info=True)
            return {"error": "Failed to update member role: {}".format(str(e))}, 500


class ProjectDataSourcesResource(BaseResource):
    def post(self, project_id):
        """Add data source(s) to a project with RBAC permission checks."""
        from redash.services.permission_service import PermissionService
        
        logger.info("Received request to add data source(s) to project %s", project_id)
        
        try:
            org = get_current_organization()
            project = Project.query.filter(
                Project.org_id == org.id,
                Project.id == project_id
            ).first_or_404()
            
            # Check if user has view access to the project (must be a member)
            if not PermissionService.is_project_member(self.current_user, project):
                # Check if user is organization admin or super admin
                if not PermissionService.has_permission(self.current_user, 'view_all_projects'):
                    abort(403, message="Access denied. You must be a project member to assign datasources.")
            
            data = request.get_json()
            if not data:
                logger.error("Invalid JSON payload")
                return {"error": "Invalid JSON payload"}, 400

            # Support both single data_source_id and bulk data_source_ids
            data_source_ids = data.get("data_source_ids")
            if data_source_ids is not None:
                # Bulk operation
                return self._handle_bulk_data_sources(project_id, data_source_ids)
            
            # Single operation (legacy support)
            data_source_id = data.get("data_source_id")
            if not data_source_id:
                logger.error("Data source ID is required")
                return {"error": "Data source ID or data_source_ids is required"}, 400

            current_user_id = self.current_user.id
            logger.debug("Current user ID: %s", current_user_id)

            data_source = DataSource.query.filter_by(
                id=data_source_id,
                org_id=org.id
            ).first()
            if not data_source:
                logger.error("Data source not found with ID: %s", data_source_id)
                return {"error": "Data source not found"}, 404
            logger.debug("Data source found: %s", data_source.to_dict())

            requester = User.query.get(current_user_id)
            if not requester:
                logger.error("Requester (current user) not found")
                return {"error": "Requester not found"}, 404

            # Check if datasource is already in the project
            existing_mapping = ProjectDataSource.query.filter_by(
                project_id=project_id, data_source_id=data_source_id
            ).first()

            if existing_mapping:
                logger.info("Data source already exists in the project")
                return {
                    "action": "already_exists",
                    "message": "Data source is already added to the project.",
                    "data_source": data_source.to_dict(),
                }, 200

            # Check permissions based on RBAC rules:
            # 1. Project members can assign their own datasources
            # 2. Project owners/admins can assign any datasource
            
            can_assign_any = PermissionService.can_manage_project(self.current_user, project)
            is_owner = data_source.owner == current_user_id
            
            if is_owner or can_assign_any:
                # User can directly add the datasource
                logger.info("User has permission to add datasource directly")
                project_data_source = ProjectDataSource(
                    project_id=project_id,
                    data_source_id=data_source_id,
                    owner=current_user_id,
                )
                db.session.add(project_data_source)
                
                # If project is shared, mark datasource as shared and migrate to shared VDB
                if project.is_shared:
                    logger.info("Project {} is shared, marking datasource {} as shared".format(project_id, data_source_id))
                    data_source.is_shared = True
                    
                    # Set shared file path if not already set
                    file_path = data_source.options.get('file_path', '') if data_source.options else ''
                    if file_path and not data_source.shared_file_path:
                        # Convert user path to shared path
                        import re
                        shared_file_path = re.sub(r'/\d+/uploads/', '/shared/uploads/', file_path)
                        data_source.shared_file_path = shared_file_path
                        logger.info("Set shared_file_path: {}".format(shared_file_path))
                    
                    db.session.add(data_source)
                    
                    # Trigger VDB migration to add foreign table and view to shared VDB
                    try:
                        from redash.services.vdb_migration import VDBMigrationService
                        migration_service = VDBMigrationService()
                        
                        # Get file path from datasource options
                        if file_path:
                            # Extract table name from datasource name (remove _XLSX suffix)
                            table_name = data_source.name.replace('_XLSX', '') if data_source.name.endswith('_XLSX') else data_source.name
                            
                            # Determine file type
                            file_type = 'excel' if file_path.endswith('.xlsx') or file_path.endswith('.xls') else 'csv'
                            
                            # Create migration request
                            datasources_to_migrate = [{
                                'private_file_path': file_path,
                                'file_type': file_type,
                                'foreign_table_name': table_name,
                                'shared_file_path': data_source.shared_file_path or file_path.replace('/{}/'.format(current_user_id), '/shared/')
                            }]
                            
                            logger.info("Triggering VDB migration for datasource {} in shared project {}".format(data_source_id, project_id))
                            migration_service.migrate_datasources_to_shared(
                                org_id=org.id,
                                user_id=current_user_id,
                                datasources=datasources_to_migrate
                            )
                            
                            logger.info("VDB migration completed for datasource {}".format(data_source_id))
                        else:
                            logger.warning("No file_path found in datasource options, skipping VDB migration")
                            
                    except Exception as e:
                        logger.error("Failed to migrate datasource to shared VDB: {}".format(str(e)))
                        # Don't fail the datasource assignment, just log the error
                
                db.session.commit()

                self.record_event({
                    "action": "add_data_source",
                    "object_id": project_id,
                    "object_type": "project",
                    "member_id": data_source.id,
                })

                return {
                    "action": "add",
                    "message": "Data source successfully added to the project.",
                    "data_source": data_source.to_dict(),
                }, 201
            else:
                # User doesn't own the datasource and isn't a project owner/admin
                logger.error("User lacks permission to add this datasource")
                return {
                    "error": "You can only assign datasources you own, or you must be a project owner/admin to assign any datasource."
                }, 403

        except IntegrityError as e:
            logger.error("IntegrityError: %s", str(e), exc_info=True)
            db.session.rollback()
            return {
                "error": "This data source is already associated with the project. Duplicate entries are not allowed."
            }, 400
        except SQLAlchemyError as e:
            logger.error("SQLAlchemyError: %s", str(e), exc_info=True)
            db.session.rollback()
            return {
                "error": "An unexpected database error occurred: {}".format(str(e))
            }, 500
        except Exception as e:
            logger.error("Unexpected error: %s", str(e), exc_info=True)
            db.session.rollback()
            return {
                "error": "An unexpected error occurred: {}".format(str(e))
            }, 500

    def _handle_bulk_data_sources(self, project_id, data_source_ids):
        """Handle bulk assignment of data sources to a project with RBAC checks."""
        from redash.services.permission_service import PermissionService
        
        logger.info("Handling bulk data source assignment for project %s", project_id)
        
        if not isinstance(data_source_ids, list):
            return {"error": "data_source_ids must be a list"}, 400
        
        try:
            org = get_current_organization()
            project = Project.query.filter(
                Project.org_id == org.id,
                Project.id == project_id
            ).first_or_404()
            
            current_user_id = self.current_user.id
            
            # Check if user can manage datasources for this project
            can_assign_any = PermissionService.can_manage_project(self.current_user, project)
            
            # Get current data sources
            current_ds_ids = {ds.data_source_id for ds in project.data_sources}
            new_ds_ids = set(data_source_ids)
            
            # Determine which to add and which to remove
            to_add = new_ds_ids - current_ds_ids
            to_remove = current_ds_ids - new_ds_ids
            
            # Validate permissions for datasources to add
            if to_add and not can_assign_any:
                # If user is not project owner/admin, they can only add their own datasources
                for ds_id in to_add:
                    data_source = DataSource.query.filter_by(
                        id=ds_id,
                        org_id=org.id
                    ).first()
                    if data_source and data_source.owner != current_user_id:
                        return {
                            "error": "You can only assign datasources you own. Project owners/admins can assign any datasource."
                        }, 403
            
            # Remove data sources (only if user can manage project)
            if to_remove:
                if not can_assign_any:
                    return {
                        "error": "Only project owners/admins can remove datasources from the project."
                    }, 403
                
                for ds_id in to_remove:
                    ProjectDataSource.query.filter_by(
                        project_id=project_id,
                        data_source_id=ds_id
                    ).delete()
            
            # Add new data sources
            for ds_id in to_add:
                data_source = DataSource.query.filter_by(
                    id=ds_id,
                    org_id=org.id
                ).first()
                if not data_source:
                    logger.warning("Data source %s not found, skipping", ds_id)
                    continue
                
                # Check if already exists
                existing = ProjectDataSource.query.filter_by(
                    project_id=project_id,
                    data_source_id=ds_id
                ).first()
                
                if not existing:
                    project_data_source = ProjectDataSource(
                        project_id=project_id,
                        data_source_id=ds_id,
                        owner=current_user_id,
                    )
                    db.session.add(project_data_source)
                    
                    # If project is shared, mark datasource as shared and migrate to shared VDB
                    if project.is_shared:
                        logger.info("Project {} is shared, marking datasource {} as shared".format(project_id, ds_id))
                        data_source.is_shared = True
                        
                        # Set shared file path if not already set
                        file_path = data_source.options.get('file_path', '') if data_source.options else ''
                        if file_path and not data_source.shared_file_path:
                            # Convert user path to shared path
                            import re
                            shared_file_path = re.sub(r'/\d+/uploads/', '/shared/uploads/', file_path)
                            data_source.shared_file_path = shared_file_path
                            logger.info("Set shared_file_path: {}".format(shared_file_path))
                        
                        db.session.add(data_source)
                        
                        # Trigger VDB migration to add foreign table and view to shared VDB
                        try:
                            from redash.services.vdb_migration import VDBMigrationService
                            migration_service = VDBMigrationService()
                            
                            # Get file path from datasource options
                            if file_path:
                                # Extract table name from datasource name (remove _XLSX suffix)
                                table_name = data_source.name.replace('_XLSX', '') if data_source.name.endswith('_XLSX') else data_source.name
                                
                                # Determine file type
                                file_type = 'excel' if file_path.endswith('.xlsx') or file_path.endswith('.xls') else 'csv'
                                
                                # Create migration request
                                datasources_to_migrate = [{
                                    'private_file_path': file_path,
                                    'file_type': file_type,
                                    'foreign_table_name': table_name,
                                    'shared_file_path': data_source.shared_file_path or file_path.replace('/{}/'.format(current_user_id), '/shared/')
                                }]
                                
                                logger.info("Triggering VDB migration for datasource {} in shared project {}".format(ds_id, project_id))
                                migration_service.migrate_datasources_to_shared(
                                    org_id=org.id,
                                    user_id=current_user_id,
                                    datasources=datasources_to_migrate
                                )
                                
                                logger.info("VDB migration completed for datasource {}".format(ds_id))
                            else:
                                logger.warning("No file_path found in datasource options, skipping VDB migration")
                                
                        except Exception as e:
                            logger.error("Failed to migrate datasource to shared VDB: {}".format(str(e)))
                            # Don't fail the datasource assignment, just log the error
            
            db.session.commit()
            
            self.record_event({
                "action": "bulk_update_data_sources",
                "object_id": project_id,
                "object_type": "project",
                "added": list(to_add),
                "removed": list(to_remove),
            })
            
            return {
                "message": "Data sources updated successfully.",
                "added": list(to_add),
                "removed": list(to_remove),
            }, 200
            
        except Exception as e:
            logger.error("Error in bulk data source update: %s", str(e), exc_info=True)
            db.session.rollback()
            return {"error": "Failed to update data sources: {}".format(str(e))}, 500

    def get(self, project_id):
        """List all data sources in a project."""
        logger.info("Fetching data sources for project %s", project_id)
        try:
            project = Project.query.get_or_404(project_id)
            data_sources = [ds.data_source.to_dict() for ds in project.data_sources]
            logger.debug("Data sources for project %s: %s", project_id, data_sources)
            return jsonify(data_sources), 200
        except Exception as e:
            logger.error("Error fetching data sources for project %s: %s", project_id, str(e), exc_info=True)
            return {"error": "Failed to fetch data sources: {}".format(str(e))}, 500

class ProjectDataSourceResource(BaseResource):
    """Resource to handle DELETE for a single data source in a project."""
    def delete(self, project_id, data_source_id):
            """Remove a specific data source from a project."""
            logger.debug("Removing data source %s from project %s", data_source_id, project_id)
            try:
                project_data_source = ProjectDataSource.query.filter_by(
                    project_id=project_id, data_source_id=data_source_id
                ).first()

                if not project_data_source:
                    logger.error("Data source not found in project %s", project_id)
                    return {"error": "Data source not found in the project"}, 404

                db.session.delete(project_data_source)
                db.session.commit()
                logger.debug("Data source %s successfully removed from project %s", data_source_id, project_id)
                return {"message": "Data source removed successfully"}, 200

            except Exception as e:
                db.session.rollback()
                logger.error("Error removing data source from project %s: %s", project_id, str(e), exc_info=True)
                return {"error": "Failed to remove data source: {}".format(str(e))}, 500

class PrivateProjectListResource(BaseResource):
    def get(self):
        """
        Return projects owned by the current user with no other members.
        This includes projects with zero members, or projects where the only member
        is the current user itself.
        """
        current_user_id = self.current_user.id
        projects = Project.query.filter_by(owner_id=current_user_id).options(joinedload(Project.members)).all()

        private_projects = []
        for project in projects:
            if len(project.members) == 0:
                private_projects.append(project.to_dict())
            elif len(project.members) == 1 and project.members[0].user_id == current_user_id:
                private_projects.append(project.to_dict())

        return jsonify(private_projects)

class PublicProjectListResource(BaseResource):
    def get(self):
        """
        Return projects where the current user is an owner or member, and the project is shared
        (i.e., has more than one unique participant including the owner).
        """
        current_user_id = self.current_user.id
        member_project_ids = db.session.query(ProjectMember.project_id).filter(
            ProjectMember.user_id == current_user_id
        )

        projects = Project.query.filter(
            or_(
                Project.owner_id == current_user_id,
                Project.id.in_(member_project_ids)
            )
        ).options(joinedload(Project.members)).distinct().all()

        public_projects = []
        for project in projects:
            participants = {member.user_id for member in project.members}
            participants.add(project.owner_id)
            if len(participants) > 1:
                public_projects.append(project.to_dict())
        return jsonify(public_projects)

class CombinePublicAndPrivateProjectListResource(BaseResource):
    def get(self):
        """
        Return a JSON object containing both private and public projects for the current user.
        """
        current_user_id = self.current_user.id

        private_projects_q = Project.query.filter_by(owner_id=current_user_id)
        private_projects = [p.to_dict() for p in private_projects_q if len(p.members) <= 1]

        public_projects_q = Project.query.filter(Project.members.any(user_id=current_user_id))
        public_projects = [p.to_dict() for p in public_projects_q if len(p.members) > 1]

        return jsonify({
            "private_projects": private_projects,
            "public_projects": public_projects
        })

    @require_permission('edit_query')
    def post(self):
        """Update assigned projects for queries or dashboards."""
        data = request.get_json(force=True)

        if "query_id" in data:
            return self._handle_query_update(data)
        elif "dashboard_id" in data:
            return self._handle_dashboard_update(data)
        else:
            return jsonify({"error": "Missing query_id or dashboard_id in payload."}), 400

    def _get_allowed_project_ids(self, user_id):
        """Helper to get IDs of projects a user has access to."""
        member_of_projects = [pm.project_id for pm in ProjectMember.query.filter_by(user_id=user_id)]
        owned_projects = [p.id for p in Project.query.filter_by(owner_id=user_id)]
        return set(member_of_projects + owned_projects)

    def _handle_query_update(self, data):
        """Logic to handle updating a query's projects."""
        query_id = data.get("query_id")
        project_ids = data.get("project_ids", [])

        if query_id is None or not isinstance(project_ids, list):
            abort(400, message="Invalid payload. 'query_id' and a list of 'project_ids' are required.")

        query = Query.get_by_id_and_org(query_id, self.current_org)
        if not query:
            abort(404, message="Query not found.")

        require_object_modify_permission(query, self.current_user)

        allowed_ids = self._get_allowed_project_ids(self.current_user.id)
        if not set(project_ids).issubset(allowed_ids):
            abort(403, message="You do not have permission to add one or more of these projects.")

        try:
            query.project_id = project_ids if project_ids else None
            query.last_modified_by = self.current_user
            db.session.add(query)
            db.session.commit()
            return jsonify({
                "message": "Projects assigned successfully",
                "query_id": query.id,
                "projects": query.project_id
            }), 200
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error("DB error assigning projects to query %s: %s", query_id, e)
            abort(500, message="Failed to assign projects due to a database error.")

    def _handle_dashboard_update(self, data):
        """Logic to handle updating a dashboard's project."""
        dashboard_id = data.get("dashboard_id")
        project_ids = data.get("project_ids", [])

        if dashboard_id is None or not isinstance(project_ids, list):
            abort(400, message="Invalid payload. 'dashboard_id' and a list of 'project_ids' are required.")

        dashboard = Dashboard.get_by_id_and_org(dashboard_id, self.current_org)
        if not dashboard:
            abort(404, message="Dashboard not found.")

        require_object_modify_permission(dashboard, self.current_user)

        allowed_ids = self._get_allowed_project_ids(self.current_user.id)
        if project_ids and not set(project_ids).issubset(allowed_ids):
             abort(403, message="You do not have permission to add one or more of these projects.")

        try:
            dashboard.project_id = project_ids[0] if project_ids else None
            dashboard.last_modified_by = self.current_user
            db.session.add(dashboard)
            db.session.commit()
            return jsonify({
                "message": "Project assigned successfully",
                "dashboard_id": dashboard.id,
                "project_id": dashboard.project_id
            }), 200
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error("DB error assigning project to dashboard %s: %s", dashboard_id, e)
            abort(500, message="Failed to assign project due to a database error.")

class DashboardSavedProjectsResource(BaseResource):
    @require_permission('view_dashboard')
    def get(self, dashboard_id):
        """Retrieve a dashboard and its project assignment."""
        dashboard = Dashboard.query.filter_by(id=dashboard_id, org_id=self.current_org.id).first_or_404()
        return jsonify({
            "id": dashboard.id,
            "name": dashboard.name,
            "project_id": dashboard.project_id,
            "user": dashboard.user.to_dict() if dashboard.user else None
        })

class ProjectItemsResource(BaseResource):
    def get(self, project_id):
        # Ensure project_id is an integer for all database lookups
        try:
            pid_int = int(project_id)
        except (ValueError, TypeError):
            abort(404, message="Invalid project ID format.")

        # Validate the project
        project = Project.query.get_or_404(pid_int)

        # For queries with a project_id array:
        queries = Query.query.filter(
            Query.project_id.contains([pid_int])
        ).all()

        # For dashboards with a single integer project_id:
        dashboards = Dashboard.query.filter(
            Dashboard.project_id == pid_int
        ).all()

        # Get data sources for the project
        data_sources = [{
            "id": ds.data_source.id,
            "data_source_id": ds.data_source_id,
            "name": ds.data_source.name,
            "type": ds.data_source.type,
            "created_at": ds.data_source.created_at.isoformat() if ds.data_source.created_at else None,
            "owner": ds.owner,
            "data_source": ds.data_source.to_dict() if ds.data_source else None,
        } for ds in project.data_sources]

        # Use jsonify to return a proper JSON response
        return jsonify({
            "project": project.to_dict(),
            "queries": [{
                "id": q.id,
                "name": q.name,
                "created_at": q.created_at.isoformat() if q.created_at else None,
                "updated_at": q.updated_at.isoformat() if q.updated_at else None,
                "created_by": q.user.name if getattr(q, 'user', None) else None,
                "data_source": q.data_source.name if getattr(q, 'data_source', None) else None,
            } for q in queries],
            "dashboards": [d.to_dict() for d in dashboards],
            "data_sources": data_sources,
        })

class ProjectQueriesWithFieldsResource(BaseResource):
    """
    GET /api/projects/<project_id>/queries_with_fields
    Returns queries in a project along with their result fields.
    
    Permission logic: Project members can view queries in their projects
    """
    def get(self, project_id):
        project = Project.query.get_or_404(project_id)
        
        # Check if user is a member of this project
        from redash.services.access_control import AccessControl
        
        if not AccessControl.check_project_access(self.current_user, project, 'view'):
            logger.warning("User %s does not have permission to view queries in project %s", 
                          self.current_user.id, project_id)
            abort(403, message="You don't have permission to view queries in this project.")
        queries = Query.query.filter(Query.project_id.contains([int(project_id)])).all()
        result = []
        for q in queries:
            try:
                fields = q.latest_query_data.column_names if q.latest_query_data else []
            except Exception:
                fields = []
            q_dict = q.to_dict()
            q_dict.pop("visualizations", None)
            q_dict["fields"] = fields
            
            # Add can_edit flag using RBAC system
            can_edit = AccessControl.check_query_access(self.current_user, q, 'edit')
            q_dict['can_edit'] = can_edit
            
            result.append(q_dict)
        return jsonify(result)

class ProjectRenameResource(BaseResource):
    """Endpoint: /api/projects/<project_id>/rename"""
    def _rename_project(self, project_id):
        from redash.services.permission_service import PermissionService
        
        # Get the project first
        project = Project.query.get(project_id)
        if project is None:
            abort(404, 'Project not found')
        
        # Check if user can manage the project (owner or admin)
        if not PermissionService.can_manage_project(self.current_user, project):
            abort(403, message="You don't have permission to rename this project.")
        
        data = request.get_json(force=True) or {}
        new_name = (data.get('name') or '').strip()
        if not new_name:
            abort(400, 'Name cannot be blank')

        project.name = new_name
        db.session.commit()
        return jsonify({'id': project.id, 'name': project.name})

    def post(self, project_id):
        return self._rename_project(project_id)

    def patch(self, project_id):
        return self._rename_project(project_id)