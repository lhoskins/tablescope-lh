"""
Project Sharing Resource Handler

API endpoint for sharing projects and moving data to shared VDB.
When a project is shared, data sources are physically copied from user's
private folder to the organization's shared folder.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8
"""

import logging
from flask import request
from flask_restful import abort

from redash.handlers.base import BaseResource
from redash.models import db
from redash.services.project_sharing import ProjectSharingService, ProjectSharingError

logger = logging.getLogger(__name__)


class ProjectSharingResource(BaseResource):
    """
    Resource for sharing projects.
    
    Endpoint:
    - POST: Share a project and move data to shared folder
    """
    
    def post(self, project_id):
        """
        Share a project and move data to shared folder.
        
        This endpoint:
        1. Validates user has permission to share the project
        2. Marks project as shared
        3. Ensures shared VDB exists (provisions if needed)
        4. Copies data sources from user folder to shared folder
        5. Updates data source references
        6. Triggers shared VDB redeployment
        
        Permission: User must have edit permission on the project
        
        Args:
            project_id: Project ID to share
            
        Returns:
            JSON with sharing status
            
        Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8
        """
        # Get project to verify existence and ownership
        from redash.models.project import Project
        
        project = Project.query.get(project_id)
        if not project:
            abort(404, message="Project {} not found".format(project_id))
        
        # Verify project belongs to current organization
        if project.org_id != self.current_org.id:
            abort(403, message="Project does not belong to your organization")
        
        # Check if user has permission to share this project
        # Permission is based on project_members table roles:
        # - "Project Owner" can share
        # - "Project Admin" can share
        can_share = False
        
        # Check if user is the project owner (by owner_id field on project)
        if project.owner_id == self.current_user.id:
            can_share = True
        
        # Check if user has Project Owner or Project Admin role in project_members table
        if not can_share:
            from redash.models.project import ProjectMember
            project_member = ProjectMember.query.filter_by(
                project_id=project_id,
                user_id=self.current_user.id
            ).first()
            
            if project_member and project_member.role:
                # Normalize role for comparison (handle variations like "Project Owner", "owner", "Owner")
                role_normalized = project_member.role.lower().replace(' ', '').replace('_', '')
                allowed_roles = ['projectowner', 'owner', 'projectadmin', 'admin']
                
                if role_normalized in allowed_roles:
                    can_share = True
        
        if not can_share:
            abort(403, message="You don't have permission to share this project. "
                              "Only Project Owners and Project Admins can share projects.")
        
        # Validate request body (optional parameters)
        req = request.get_json(silent=True) or {}
        
        try:
            # Share project
            logger.info('Sharing project: project_id={}, user_id={}, org_id={}'.format(
                project_id, self.current_user.id, self.current_org.id
            ))
            
            sharing_service = ProjectSharingService()
            result = sharing_service.share_project(project_id, self.current_user.id)
            
            if not result.get('success'):
                error_msg = 'Failed to share project: {}'.format(result.get('error'))
                logger.error(error_msg)
                abort(500, message=error_msg)
            
            # Build response
            response = {
                'success': True,
                'project_id': project_id,
                'shared_vdb_id': result.get('shared_vdb_id'),
                'data_sources_copied': result.get('data_sources_copied', 0),
                'message': 'Project shared successfully'
            }
            
            self.record_event({
                'action': 'share',
                'object_id': project_id,
                'object_type': 'project',
                'shared_vdb_id': result.get('shared_vdb_id'),
                'data_sources_copied': result.get('data_sources_copied', 0)
            })
            
            logger.info('Project shared successfully: project_id={}, shared_vdb_id={}, data_sources_copied={}'.format(
                project_id, result.get('shared_vdb_id'), result.get('data_sources_copied', 0)
            ))
            
            return response
            
        except ProjectSharingError as e:
            error_msg = 'Failed to share project: {}'.format(str(e))
            logger.error(error_msg)
            abort(500, message=error_msg)
            
        except Exception as e:
            error_msg = 'Unexpected error sharing project: {}'.format(str(e))
            logger.error(error_msg, exc_info=True)
            abort(500, message=error_msg)


class ProjectUnsharingResource(BaseResource):
    """
    Resource for unsharing projects.
    
    Endpoint:
    - POST: Unshare a project and revert data to user folder
    """
    
    def post(self, project_id):
        """
        Unshare a project and revert data to user folder.
        
        This endpoint:
        1. Validates user has permission to unshare the project
        2. Removes all members except the project owner
        3. Marks project as private
        4. Migrates data back to user folder
        5. Updates data source references
        6. Triggers user VDB redeployment
        
        Permission: User must have edit permission on the project
        
        Args:
            project_id: Project ID to unshare
            
        Returns:
            JSON with unsharing status
            
        Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 7.4, 7.5, 7.6, 7.7
        """
        # Get project to verify existence
        from redash.models.project import Project, ProjectMember
        from redash.services.permission_service import PermissionService
        
        project = Project.query.get(project_id)
        if not project:
            abort(404, message="Project {} not found".format(project_id))
        
        # Verify project belongs to current organization
        if project.org_id != self.current_org.id:
            abort(403, message="Project does not belong to your organization")
        
        # Check if user has permission to unshare this project
        # Permission is based on project_members table roles:
        # - "Project Owner" can unshare
        # - "Project Admin" can unshare
        can_unshare = False
        
        # Check if user is the project owner (by owner_id field on project)
        if project.owner_id == self.current_user.id:
            can_unshare = True
            logger.info("User {} is project owner (owner_id match) for project {}".format(
                self.current_user.id, project_id))
        
        # Check if user has Project Owner or Project Admin role in project_members table
        if not can_unshare:
            project_member = ProjectMember.query.filter_by(
                project_id=project_id,
                user_id=self.current_user.id
            ).first()
            
            if project_member and project_member.role:
                # Normalize role for comparison (handle variations like "Project Owner", "owner", "Owner")
                role_normalized = project_member.role.lower().replace(' ', '').replace('_', '')
                allowed_roles = ['projectowner', 'owner', 'projectadmin', 'admin']
                
                if role_normalized in allowed_roles:
                    can_unshare = True
                    logger.info("User {} has '{}' role in project_members for project {}".format(
                        self.current_user.id, project_member.role, project_id))
        
        if not can_unshare:
            logger.warning("User {} denied permission to unshare project {}. owner_id={}, user_id={}".format(
                self.current_user.id, project_id, project.owner_id, self.current_user.id))
            abort(403, message="You don't have permission to unshare this project. "
                              "Only Project Owners and Project Admins can unshare projects.")
        
        # Check if project is currently shared
        if not hasattr(project, 'is_shared') or not project.is_shared:
            abort(400, message="Project is not currently shared")
        
        # Verify confirmation in request body
        req = request.get_json(silent=True) or {}
        if not req.get('confirm'):
            abort(400, message="Confirmation required")
        
        try:
            # Begin transaction
            db.session.begin_nested()
            
            # Remove all members except owner
            removed_count = ProjectMember.query.filter(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id != project.owner_id
            ).delete()
            
            logger.info('Removed {} members from project {}'.format(removed_count, project_id))
            
            # Call the full migration orchestrator to properly unshare the project
            logger.info('Unsharing project: project_id={}, user_id={}'.format(
                project_id, self.current_user.id
            ))
            
            # Initialize the migration orchestrator
            from redash.services.data_migration import DataMigrationOrchestrator
            orchestrator = DataMigrationOrchestrator()
            
            # Perform the full migration (files, VDB, queries, etc.)
            # This will:
            # 1. Migrate files back to private directory
            # 2. Update VDB configurations
            # 3. Remove non-owner queries from the project
            # 4. Set is_shared = False
            orchestrator.migrate_project_to_private(project_id, self.current_user.id)
            
            # Commit transaction
            db.session.commit()
            
            # Invalidate permission cache for removed members
            from redash.services.permission_service import PermissionService
            removed_members = ProjectMember.query.filter_by(project_id=project_id).all()
            for member in removed_members:
                PermissionService.invalidate_permission_cache(user_id=member.user_id)
            
            # Build response
            response = {
                'success': True,
                'project_id': project_id,
                'removed_members_count': removed_count,
                'message': 'Project unshared successfully. Data migrated back to private folder.',
                'project': {
                    'id': project.id,
                    'name': project.name,
                    'is_shared': False,
                    'member_count': 1
                }
            }
            
            self.record_event({
                'action': 'unshare',
                'object_id': project_id,
                'object_type': 'project',
                'removed_members_count': removed_count
            })
            
            logger.info('Project unshared successfully: project_id={}, removed_members={}'.format(
                project_id, removed_count
            ))
            
            return response
            
        except Exception as e:
            db.session.rollback()
            error_msg = 'Failed to unshare project: {}'.format(str(e))
            logger.error(error_msg, exc_info=True)
            abort(500, message=error_msg)
