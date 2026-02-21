# redash/services/access_control.py

"""
Access control service for managing resource access logic.

This service provides methods to check user access to specific resources
(datasources, queries, projects) based on ownership, project membership,
and role-based permissions.
"""

import logging
from redash.models.project import ProjectMember, ProjectDataSource
from redash.services.permission_service import PermissionService

logger = logging.getLogger(__name__)


class AccessControl:
    """
    Manages resource access control logic.
    
    This service implements the access rules for datasources, queries, and projects
    based on ownership, project membership, and role-based permissions.
    """
    
    @staticmethod
    def check_datasource_access(user, datasource, access_type='view'):
        """
        Check if user has specific access to datasource.
        
        Access rules:
        - Owner has full access (view, edit, delete, execute)
        - Project members have view and execute access if datasource is assigned to project
        - Organization admin has view access to all datasources in organization
        - Super admin has full access to all datasources
        
        Args:
            user: User object
            datasource: DataSource object
            access_type (str): 'view', 'edit', 'delete', or 'execute'
            
        Returns:
            bool: True if access granted
        """
        if not user or not datasource:
            logger.debug("Access denied: user or datasource is None")
            return False
        
        # Multi-tenant isolation check
        if datasource.org_id != user.org_id:
            logger.debug(
                "Access denied: datasource org {} != user org {}".format(
                    datasource.org_id, user.org_id
                )
            )
            return False
        
        # Check ownership - owner has full access
        if hasattr(datasource, 'owner') and datasource.owner == user.id:
            logger.debug("Access granted: user {} is owner of datasource {}".format(
                user.id, datasource.id
            ))
            return True
        
        # Check project membership for view and execute access
        if access_type in ['view', 'execute']:
            user_projects = PermissionService.get_user_project_ids(user)
            datasource_projects = AccessControl._get_datasource_project_ids(datasource)
            
            if set(user_projects) & set(datasource_projects):
                logger.debug(
                    "Access granted: user {} has project membership for datasource {}".format(
                        user.id, datasource.id
                    )
                )
                return True
        
        # Check organization admin role
        if PermissionService.has_organization_admin_role(user):
            # Organization admin can view all datasources in their org
            if access_type == 'view':
                logger.debug(
                    "Access granted: user {} is organization admin (view access)".format(user.id)
                )
                return True
            # For edit/delete, org admin needs explicit permission or ownership
            if user.has_permission('edit_any_datasource') or user.has_permission('delete_any_datasource'):
                logger.debug(
                    "Access granted: user {} is organization admin with edit/delete permission".format(
                        user.id
                    )
                )
                return True
        
        # Check super admin role - super admin has full access
        if PermissionService.has_super_admin_role(user):
            logger.debug("Access granted: user {} is super admin".format(user.id))
            return True
        
        logger.debug(
            "Access denied: user {} does not have {} access to datasource {}".format(
                user.id, access_type, datasource.id
            )
        )
        return False
    
    @staticmethod
    def check_query_access(user, query, access_type='view'):
        """
        Check if user has specific access to query.
        
        Access rules:
        - Owner has full access (view, edit, delete, execute)
        - Project members have view and execute access if query is assigned to project
        - Designers can edit queries in projects where they are members
        - Organization admin has full access to all queries in organization
        - Super admin has full access to all queries
        
        Args:
            user: User object
            query: Query object
            access_type (str): 'view', 'edit', 'delete', or 'execute'
            
        Returns:
            bool: True if access granted
        """
        if not user or not query:
            logger.debug("Access denied: user or query is None")
            return False
        
        # Multi-tenant isolation check
        if query.org_id != user.org_id:
            logger.debug(
                "Access denied: query org {} != user org {}".format(
                    query.org_id, user.org_id
                )
            )
            return False
        
        # Check ownership - owner has full access
        # This is the primary check - users can always edit their own queries
        # Check both user_id (creator) and owner field
        is_creator = hasattr(query, 'user_id') and query.user_id == user.id
        is_owner = hasattr(query, 'owner') and query.owner == user.id
        
        logger.info("RBAC: Checking ownership - query.user_id={}, query.owner={}, user.id={}, is_creator={}, is_owner={}".format(
            getattr(query, 'user_id', None), getattr(query, 'owner', None), user.id, is_creator, is_owner
        ))
        
        if is_creator or is_owner:
            logger.info("RBAC: Access granted - user {} is owner of query {} (creator={}, owner={})".format(
                user.id, query.id, is_creator, is_owner
            ))
            return True
        
        # Check if query is assigned to a project the user is a member of
        if hasattr(query, 'project_id') and query.project_id:
            # Handle project_id as either a single value or a list
            query_project_ids = query.project_id if isinstance(query.project_id, list) else [query.project_id]
            
            # Check if user is a member of any of the query's projects
            for project_id in query_project_ids:
                member = ProjectMember.query.filter(
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == user.id
                ).first()
                
                if member:
                    # All project members can view and execute
                    if access_type in ['view', 'execute']:
                        logger.debug(
                            "Access granted: user {} is project member (view/execute access) for project {}".format(
                                user.id, project_id
                            )
                        )
                        return True
                    
                    # For edit access, check role:
                    # - 'member' role: can only edit their own queries (handled by ownership check above)
                    # - 'designer' role: can edit any query in the project
                    # - 'admin' role: can edit any query in the project
                    # - 'owner' role: can edit any query in the project
                    if access_type == 'edit':
                        if member.role in ['designer', 'admin', 'owner']:
                            logger.info(
                                "RBAC: Access granted - user {} is project {} with edit access for project {} (role: {})".format(
                                    user.id, member.role, project_id, member.role
                                )
                            )
                            return True
                        else:
                            logger.info(
                                "RBAC: Access denied - user {} is project member but role '{}' cannot edit other users' queries in project {}".format(
                                    user.id, member.role, project_id
                                )
                            )
                            # Member role can only edit their own queries (already checked above)
                            # Continue to check other permissions
        
        # Check organization admin role - org admin has full access to all queries
        if PermissionService.has_organization_admin_role(user):
            logger.debug("Access granted: user {} is organization admin".format(user.id))
            return True
        
        # Check super admin role - super admin has full access
        if PermissionService.has_super_admin_role(user):
            logger.debug("Access granted: user {} is super admin".format(user.id))
            return True
        
        logger.info(
            "RBAC: Access DENIED - user {} does not have {} access to query {} (final check)".format(
                user.id, access_type, query.id
            )
        )
        return False
    
    @staticmethod
    def check_project_access(user, project, access_type='view'):
        """
        Check if user has specific access to project.
        
        Access rules:
        - Project owner has full access (view, edit, delete, manage members)
        - Project admin has management access (view, edit, manage members) but cannot delete
        - Project members have view access
        - Organization admin has full access to all projects in organization
        - Super admin has full access to all projects
        
        Args:
            user: User object
            project: Project object
            access_type (str): 'view', 'edit', 'delete', or 'manage'
            
        Returns:
            bool: True if access granted
        """
        if not user or not project:
            logger.debug("Access denied: user or project is None")
            return False
        
        # Multi-tenant isolation check
        if project.org_id != user.org_id:
            logger.debug(
                "Access denied: project org {} != user org {}".format(
                    project.org_id, user.org_id
                )
            )
            return False
        
        # Check if user is project owner
        if PermissionService.is_project_owner(user, project):
            logger.debug("Access granted: user {} is owner of project {}".format(
                user.id, project.id
            ))
            return True
        
        # Check if user is project admin
        if PermissionService.is_project_admin(user, project):
            # Project admins can do everything except delete
            if access_type != 'delete':
                logger.debug(
                    "Access granted: user {} is admin of project {}".format(
                        user.id, project.id
                    )
                )
                return True
            else:
                logger.debug("Access denied: project admins cannot delete projects")
                return False
        
        # Check if user is a project member (for view access)
        if access_type == 'view':
            if PermissionService.is_project_member(user, project):
                logger.debug(
                    "Access granted: user {} is member of project {}".format(
                        user.id, project.id
                    )
                )
                return True
        
        # Check organization admin role - org admin has full access
        if PermissionService.has_organization_admin_role(user):
            logger.debug("Access granted: user {} is organization admin".format(user.id))
            return True
        
        # Check super admin role - super admin has full access
        if PermissionService.has_super_admin_role(user):
            logger.debug("Access granted: user {} is super admin".format(user.id))
            return True
        
        logger.debug(
            "Access denied: user {} does not have {} access to project {}".format(
                user.id, access_type, project.id
            )
        )
        return False
    
    @staticmethod
    def _get_datasource_project_ids(datasource):
        """
        Get all project IDs that a datasource is assigned to.
        
        Args:
            datasource: DataSource object
            
        Returns:
            list: List of project IDs
        """
        project_datasources = ProjectDataSource.query.filter(
            ProjectDataSource.data_source_id == datasource.id
        ).all()
        
        return [pds.project_id for pds in project_datasources]

    @staticmethod
    def get_accessible_datasources(user, org=None):
        """
        Get all datasources accessible to user with optimized query.
        
        Returns datasources that the user can access based on:
        - Ownership
        - Project membership
        - Organization admin role
        - Super admin role
        
        Args:
            user: User object
            org: Optional organization (defaults to user's org)
            
        Returns:
            Query: SQLAlchemy query object for accessible datasources
        """
        from redash.models import DataSource
        from sqlalchemy import or_, and_
        
        if not user:
            return DataSource.query.filter(False)  # Return empty query
        
        if org is None:
            org = user.org
        
        # Start with organization filter
        query = DataSource.query.filter(DataSource.org_id == org.id)
        
        # Super admin can access all datasources
        if PermissionService.has_super_admin_role(user):
            logger.debug("User {} is super admin - returning all datasources".format(user.id))
            return query
        
        # Organization admin can view all datasources in their org
        if PermissionService.has_organization_admin_role(user):
            logger.debug("User {} is org admin - returning all datasources in org".format(user.id))
            return query
        
        # Build filter for accessible datasources
        user_project_ids = PermissionService.get_user_project_ids(user, org)
        
        # Datasources accessible through:
        # 1. User is the owner
        # 2. Datasource is assigned to a project the user is a member of
        filters = [DataSource.owner == user.id]
        
        if user_project_ids:
            # Add filter for datasources in user's projects
            from sqlalchemy import select
            filters.append(
                DataSource.id.in_(
                    select([ProjectDataSource.data_source_id]).where(
                        ProjectDataSource.project_id.in_(user_project_ids)
                    )
                )
            )
        
        query = query.filter(or_(*filters))
        
        logger.debug(
            "Returning accessible datasources for user {} (owner or in {} projects)".format(
                user.id, len(user_project_ids)
            )
        )
        return query
    
    @staticmethod
    def get_accessible_queries(user, org=None):
        """
        Get all queries accessible to user with optimized query.
        
        Returns queries that the user can access based on:
        - Ownership
        - Project membership
        - Organization admin role
        - Super admin role
        
        Args:
            user: User object
            org: Optional organization (defaults to user's org)
            
        Returns:
            Query: SQLAlchemy query object for accessible queries
        """
        from redash.models import Query
        from sqlalchemy import or_
        
        if not user:
            return Query.query.filter(False)  # Return empty query
        
        if org is None:
            org = user.org
        
        # Start with organization filter
        query = Query.query.filter(Query.org_id == org.id)
        
        # Super admin can access all queries
        if PermissionService.has_super_admin_role(user):
            logger.debug("User {} is super admin - returning all queries".format(user.id))
            return query
        
        # Organization admin can access all queries in their org
        if PermissionService.has_organization_admin_role(user):
            logger.debug("User {} is org admin - returning all queries in org".format(user.id))
            return query
        
        # Build filter for accessible queries
        user_project_ids = PermissionService.get_user_project_ids(user, org)
        
        # Queries accessible through:
        # 1. User is the owner
        # 2. Query is assigned to a project the user is a member of
        filters = [Query.user_id == user.id]
        
        if user_project_ids:
            # Add filter for queries in user's projects OR queries with no project assigned
            filters.append(
                or_(
                    Query.project_id.overlap(user_project_ids),  # Queries in user's projects
                    Query.project_id == None,  # Queries with NULL project_id
                    Query.project_id == []  # Queries with empty array project_id
                )
            )
        
        query = query.filter(or_(*filters))
        
        logger.debug(
            "Returning accessible queries for user {} (owner or in {} projects)".format(
                user.id, len(user_project_ids)
            )
        )
        return query
    
    @staticmethod
    def get_accessible_projects(user, org=None):
        """
        Get all projects accessible to user with optimized query.
        
        Returns projects that the user can access based on:
        - Project membership (owner, admin, or member)
        - Organization admin role
        - Super admin role
        
        Args:
            user: User object
            org: Optional organization (defaults to user's org)
            
        Returns:
            Query: SQLAlchemy query object for accessible projects
        """
        from redash.models.project import Project
        from sqlalchemy import or_
        
        if not user:
            return Project.query.filter(False)  # Return empty query
        
        if org is None:
            org = user.org
        
        # Start with organization filter
        query = Project.query.filter(Project.org_id == org.id)
        
        # Super admin can access all projects
        if PermissionService.has_super_admin_role(user):
            logger.debug("User {} is super admin - returning all projects".format(user.id))
            return query
        
        # Organization admin can access all projects in their org
        if PermissionService.has_organization_admin_role(user):
            logger.debug("User {} is org admin - returning all projects in org".format(user.id))
            return query
        
        # Get projects where user is a member
        user_project_ids = PermissionService.get_user_project_ids(user, org)
        
        if user_project_ids:
            query = query.filter(Project.id.in_(user_project_ids))
            logger.debug(
                "Returning {} accessible projects for user {}".format(
                    len(user_project_ids), user.id
                )
            )
        else:
            # User is not a member of any projects
            query = query.filter(False)
            logger.debug("User {} has no accessible projects".format(user.id))
        
        return query
    
    @staticmethod
    def filter_accessible_resources(user, resources, resource_type='datasource'):
        """
        Filter resources to only those accessible by user (batch checking).
        
        This method performs batch permission checks for efficiency when
        filtering a list of resources.
        
        Args:
            user: User object
            resources: List of resource objects (DataSource, Query, or Project)
            resource_type (str): Type of resource ('datasource', 'query', or 'project')
            
        Returns:
            list: Filtered list of accessible resources
        """
        if not user or not resources:
            return []
        
        # Super admin can access all resources
        if PermissionService.has_super_admin_role(user):
            logger.debug("User {} is super admin - returning all {} resources".format(
                user.id, len(resources)
            ))
            return resources
        
        # Organization admin can access all resources in their org
        if PermissionService.has_organization_admin_role(user):
            # Filter by organization
            accessible = [r for r in resources if r.org_id == user.org_id]
            logger.debug(
                "User {} is org admin - returning {} resources in org".format(
                    user.id, len(accessible)
                )
            )
            return accessible
        
        # Get user's project IDs once for efficiency
        user_project_ids = set(PermissionService.get_user_project_ids(user))
        
        accessible = []
        
        for resource in resources:
            # Multi-tenant isolation
            if resource.org_id != user.org_id:
                continue
            
            # Check ownership
            if hasattr(resource, 'user_id') and resource.user_id == user.id:
                accessible.append(resource)
                continue
            
            # Check project membership
            if resource_type == 'datasource':
                datasource_projects = set(AccessControl._get_datasource_project_ids(resource))
                if user_project_ids & datasource_projects:
                    accessible.append(resource)
            elif resource_type == 'query':
                if hasattr(resource, 'project_id') and resource.project_id in user_project_ids:
                    accessible.append(resource)
            elif resource_type == 'project':
                if resource.id in user_project_ids:
                    accessible.append(resource)
        
        logger.debug(
            "Filtered {} {}s to {} accessible for user {}".format(
                len(resources), resource_type, len(accessible), user.id
            )
        )
        return accessible
