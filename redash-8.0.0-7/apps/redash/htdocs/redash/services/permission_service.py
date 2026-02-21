# redash/services/permission_service.py

"""
Centralized service for checking user permissions in the RBAC security model.

This service provides methods to check if users have specific permissions,
taking into account role assignments, project memberships, and resource ownership.
"""

import logging
import os
from redash.models.role_assignment import RoleAssignment
from redash.models.permission_cache import PermissionCache
from redash.models.users import Group
from redash.models.project import ProjectMember

logger = logging.getLogger(__name__)

# Import Redis cache service (optional)
try:
    from redash.services.redis_permission_cache import get_redis_cache
    REDIS_CACHE_AVAILABLE = True
except ImportError:
    REDIS_CACHE_AVAILABLE = False
    logger.warning("Redis permission cache not available")


class PermissionService:
    """
    Centralized service for checking user permissions.
    
    This service handles permission checks for the RBAC security model,
    including role-based permissions, project-specific permissions, and
    resource ownership checks.
    """
    
    # Cache TTL in seconds (5 minutes by default, configurable via env var)
    CACHE_TTL = int(os.environ.get('PERMISSION_CACHE_TTL', '300'))
    
    # Enable/disable permission caching (configurable via env var)
    ENABLE_CACHING = os.environ.get('ENABLE_PERMISSION_CACHING', 'true').lower() == 'true'
    
    @staticmethod
    def has_permission(user, permission, resource=None, org=None):
        """
        Check if user has a specific permission.
        
        This is the main entry point for permission checks. It checks:
        1. Redis cache for quick lookups (if enabled)
        2. Database permission cache (fallback)
        3. Role-based permissions from user's groups
        4. Role assignments (project-specific or global)
        5. Resource ownership
        6. Project membership
        
        Args:
            user: User object
            permission (str): Permission string (e.g., 'edit_query', 'create_datasource')
            resource: Optional resource object (Query, DataSource, Project)
            org: Optional organization for multi-tenant check
            
        Returns:
            bool: True if user has permission
        """
        if not user or not permission:
            return False
        
        # Use user's org if not specified
        if org is None:
            org = user.org
        
        # Determine resource type and ID
        resource_type = None
        resource_id = None
        if resource:
            resource_type = resource.__class__.__name__.lower()
            resource_id = resource.id
        
        # Skip cache if caching is disabled
        if not PermissionService.ENABLE_CACHING:
            return PermissionService._compute_permission(user, permission, resource, org)
        
        # Check Redis cache first (if available)
        cached_result = None
        if REDIS_CACHE_AVAILABLE:
            try:
                redis_cache = get_redis_cache()
                cached_result = redis_cache.get_cached_permission(
                    user.id, permission, resource_type, resource_id
                )
                if cached_result is not None:
                    logger.debug("Redis cache hit for user %s, permission %s", user.id, permission)
                    return cached_result
            except Exception as e:
                logger.warning("Redis cache lookup failed: %s", e)
        
        # Fallback to database cache
        if cached_result is None:
            cached_result = PermissionCache.get_cached_permission(
                user.id, permission, resource_type, resource_id
            )
            if cached_result is not None:
                logger.debug("Database cache hit for user %s, permission %s", user.id, permission)
                return cached_result
        
        # Compute permission
        has_perm = PermissionService._compute_permission(
            user, permission, resource, org
        )
        
        # Cache the result in both Redis and database
        try:
            # Cache in Redis first (if available)
            if REDIS_CACHE_AVAILABLE:
                try:
                    redis_cache = get_redis_cache()
                    redis_cache.set_cached_permission(
                        user.id, permission, org.id, has_perm,
                        resource_type, resource_id,
                        ttl_seconds=PermissionService.CACHE_TTL
                    )
                except Exception as e:
                    logger.warning("Failed to cache permission in Redis: %s", e)
            
            # Also cache in database as fallback
            PermissionCache.cache_permission(
                user.id, permission, org.id, resource_type, resource_id,
                ttl_seconds=PermissionService.CACHE_TTL
            )
        except Exception as e:
            logger.warning("Failed to cache permission: %s", e)
        
        return has_perm
    
    @staticmethod
    def _compute_permission(user, permission, resource, org):
        """
        Compute if user has permission (internal method).
        
        Args:
            user: User object
            permission (str): Permission string
            resource: Optional resource object
            org: Organization object
            
        Returns:
            bool: True if user has permission
        """
        # Check if user has permission through their groups
        if permission in user.permissions:
            return True
        
        # Check role assignments for additional permissions
        role_assignments = RoleAssignment.get_user_roles(user.id, org.id)
        
        for assignment in role_assignments:
            role_permissions = Group.ROLE_PERMISSIONS.get(assignment.role_type, [])
            
            # For project-specific roles, check if the resource belongs to that project
            if assignment.resource_type == 'project' and assignment.resource_id:
                if resource and hasattr(resource, 'project_id'):
                    # Resource is directly in a project
                    if resource.project_id == assignment.resource_id and permission in role_permissions:
                        return True
                elif resource and hasattr(resource, 'id'):
                    # Check if resource is associated with the project through membership
                    resource_type = resource.__class__.__name__.lower()
                    if resource_type == 'project' and resource.id == assignment.resource_id:
                        if permission in role_permissions:
                            return True
            else:
                # Global role assignment
                if permission in role_permissions:
                    return True
        
        return False
    
    @staticmethod
    def get_user_permissions(user, org=None):
        """
        Get all permissions for a user with caching.
        
        This method returns the complete set of permissions a user has,
        combining permissions from groups and role assignments.
        
        Args:
            user: User object
            org: Optional organization (defaults to user's org)
            
        Returns:
            set: Set of permission strings
        """
        if not user:
            return set()
        
        if org is None:
            org = user.org
        
        # Skip cache if caching is disabled
        if not PermissionService.ENABLE_CACHING:
            permissions = set(user.permissions)
            role_assignments = RoleAssignment.get_user_roles(user.id, org.id)
            for assignment in role_assignments:
                role_permissions = Group.ROLE_PERMISSIONS.get(assignment.role_type, [])
                permissions.update(role_permissions)
            return permissions
        
        # Check Redis cache first (if available)
        cached_permissions = None
        if REDIS_CACHE_AVAILABLE:
            try:
                redis_cache = get_redis_cache()
                cached_permissions = redis_cache.get_cached_permissions(user.id, org.id)
                if cached_permissions:
                    logger.debug("Redis cache hit for user %s permissions", user.id)
                    return cached_permissions
            except Exception as e:
                logger.warning("Redis cache lookup failed: %s", e)
        
        # Fallback to database cache
        if cached_permissions is None:
            cached_permissions = PermissionCache.get_user_cached_permissions(user.id, org.id)
            if cached_permissions:
                logger.debug("Database cache hit for user %s permissions", user.id)
                return set(cached_permissions)
        
        # Compute permissions
        permissions = set(user.permissions)
        
        # Add permissions from role assignments
        role_assignments = RoleAssignment.get_user_roles(user.id, org.id)
        for assignment in role_assignments:
            role_permissions = Group.ROLE_PERMISSIONS.get(assignment.role_type, [])
            permissions.update(role_permissions)
        
        # Cache the complete permission set in Redis (if available)
        if REDIS_CACHE_AVAILABLE:
            try:
                redis_cache = get_redis_cache()
                redis_cache.set_cached_permissions(
                    user.id, org.id, permissions,
                    ttl_seconds=PermissionService.CACHE_TTL
                )
            except Exception as e:
                logger.warning("Failed to cache permissions in Redis: %s", e)
        
        # Cache individual permissions in database as fallback
        for perm in permissions:
            try:
                PermissionCache.cache_permission(
                    user.id, perm, org.id,
                    ttl_seconds=PermissionService.CACHE_TTL
                )
            except Exception as e:
                logger.warning("Failed to cache permission %s: %s", perm, e)
        
        return permissions
    
    @staticmethod
    def invalidate_permission_cache(user_id=None, resource_type=None, resource_id=None, org_id=None):
        """
        Invalidate permission cache in both Redis and database.
        
        This should be called when:
        - User's roles change
        - User is added/removed from a project
        - Resource ownership changes
        - Project membership changes
        
        Args:
            user_id (int, optional): User ID to invalidate cache for
            resource_type (str, optional): Resource type to invalidate
            resource_id (int, optional): Resource ID to invalidate
            org_id (int, optional): Organization ID to invalidate
            
        Returns:
            int: Number of cache entries invalidated
        """
        count = 0
        
        # Invalidate Redis cache first (if available)
        if REDIS_CACHE_AVAILABLE:
            try:
                redis_cache = get_redis_cache()
                redis_count = 0
                
                if user_id:
                    redis_count = redis_cache.invalidate_user_cache(user_id)
                elif resource_type and resource_id:
                    redis_count = redis_cache.invalidate_resource_cache(resource_type, resource_id)
                elif org_id:
                    redis_count = redis_cache.invalidate_org_cache(org_id)
                
                if redis_count > 0:
                    logger.info("Invalidated %s Redis cache entries", redis_count)
                    count += redis_count
            except Exception as e:
                logger.warning("Failed to invalidate Redis cache: %s", e)
        
        # Also invalidate database cache
        try:
            db_count = 0
            if user_id:
                db_count = PermissionCache.invalidate_user_cache(user_id)
                logger.info("Invalidated %s database cache entries for user %s", db_count, user_id)
            elif resource_type and resource_id:
                db_count = PermissionCache.invalidate_resource_cache(resource_type, resource_id)
                logger.info("Invalidated %s database cache entries for %s:%s", db_count, resource_type, resource_id)
            elif org_id:
                db_count = PermissionCache.invalidate_org_cache(org_id)
                logger.info("Invalidated %s database cache entries for org %s", db_count, org_id)
            
            count += db_count
        except Exception as e:
            logger.error("Failed to invalidate database permission cache: %s", e)
        
        return count
    
    # Role-based permission checking methods
    
    @staticmethod
    def has_default_role(user):
        """
        Check if user has default role permissions.
        
        All users should have default role permissions as it's the base role.
        
        Args:
            user: User object
            
        Returns:
            bool: True if user has default role
        """
        if not user:
            return False
        
        # Check if user is in default group
        if user.org and user.org.default_group:
            if user.org.default_group.id in (user.group_ids or []):
                return True
        
        # Check role assignments
        return RoleAssignment.has_role(user.id, Group.ROLE_DEFAULT)
    
    @staticmethod
    def has_designer_role(user, org=None):
        """
        Check if user has designer role.
        
        Args:
            user: User object
            org: Optional organization
            
        Returns:
            bool: True if user has designer role
        """
        if not user:
            return False
        
        if org is None:
            org = user.org
        
        # Check role assignments
        role_assignments = RoleAssignment.get_user_roles(user.id, org.id)
        for assignment in role_assignments:
            if assignment.role_type == Group.ROLE_DESIGNER:
                return True
        
        return False
    
    @staticmethod
    def is_project_owner(user, project):
        """
        Check if user is the owner of a project.
        
        Args:
            user: User object
            project: Project object
            
        Returns:
            bool: True if user is project owner
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not user or not project:
            return False
        
        # Check if user created the project
        if project.owner_id == user.id:
            logger.debug("[is_project_owner] User %s is project owner (owner_id match)", user.id)
            return True
        
        # Check project membership with owner role
        member = ProjectMember.query.filter(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
            ProjectMember.role == 'owner'
        ).first()
        
        if member:
            logger.debug("[is_project_owner] User %s has owner role in project_members", user.id)
            return True
        
        # Check role assignments
        has_role = RoleAssignment.has_role(
            user.id, Group.ROLE_PROJECT_OWNER,
            resource_type='project', resource_id=project.id
        )
        if has_role:
            logger.debug("[is_project_owner] User %s has owner role via RoleAssignment", user.id)
        return has_role
    
    @staticmethod
    def is_project_admin(user, project):
        """
        Check if user is a project admin for a specific project.
        
        Args:
            user: User object
            project: Project object
            
        Returns:
            bool: True if user is project admin
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not user or not project:
            return False
        
        # Check project membership with admin role
        member = ProjectMember.query.filter(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
            ProjectMember.role == 'admin'
        ).first()
        
        if member:
            logger.debug("[is_project_admin] User %s has admin role in project_members", user.id)
            return True
        
        # Check role assignments
        has_role = RoleAssignment.has_role(
            user.id, Group.ROLE_PROJECT_ADMIN,
            resource_type='project', resource_id=project.id
        )
        if has_role:
            logger.debug("[is_project_admin] User %s has admin role via RoleAssignment", user.id)
        return has_role
    
    @staticmethod
    def has_organization_admin_role(user, org=None):
        """
        Check if user has organization admin role.
        
        Args:
            user: User object
            org: Optional organization
            
        Returns:
            bool: True if user has organization admin role
        """
        if not user:
            return False
        
        if org is None:
            org = user.org
        
        # Check role assignments
        role_assignments = RoleAssignment.get_user_roles(user.id, org.id)
        for assignment in role_assignments:
            if assignment.role_type == Group.ROLE_ORG_ADMIN:
                return True
        
        return False
    
    @staticmethod
    def has_super_admin_role(user):
        """
        Check if user has super admin role.
        
        Args:
            user: User object
            
        Returns:
            bool: True if user has super admin role
        """
        if not user:
            return False
        
        # Check role assignments (super admin can be across orgs)
        role_assignments = RoleAssignment.query.filter(
            RoleAssignment.user_id == user.id,
            RoleAssignment.role_type == Group.ROLE_SUPER_ADMIN
        ).first()
        
        return role_assignments is not None
    
    @staticmethod
    def can_manage_project(user, project):
        """
        Check if user can manage a project (owner or admin).
        
        Args:
            user: User object
            project: Project object
            
        Returns:
            bool: True if user can manage the project
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not user or not project:
            logger.debug("[can_manage_project] User or project is None: user=%s, project=%s", user, project)
            return False
        
        logger.debug("[can_manage_project] Checking permissions for user %s on project %s", user.id, project.id)
        
        # Check if user is project owner
        if PermissionService.is_project_owner(user, project):
            logger.debug("[can_manage_project] User %s is project owner", user.id)
            return True
        
        # Check if user is project admin
        if PermissionService.is_project_admin(user, project):
            logger.debug("[can_manage_project] User %s is project admin", user.id)
            return True
        
        # Check if user is organization admin
        if PermissionService.has_organization_admin_role(user, project.organization):
            logger.debug("[can_manage_project] User %s is organization admin", user.id)
            return True
        
        # Check if user is super admin
        if PermissionService.has_super_admin_role(user):
            logger.debug("[can_manage_project] User %s is super admin", user.id)
            return True
        
        logger.debug("[can_manage_project] User %s does not have manage permission on project %s", user.id, project.id)
        return False

    # Resource-specific permission checking methods
    
    @staticmethod
    def can_access_datasource(user, datasource, access_type='view'):
        """
        Check if user can access a datasource.
        
        Access rules:
        - Owner has full access (view, edit, delete, execute)
        - Project members have view and execute access if datasource is assigned to project
        - Organization admin has view access to all datasources in organization
        - Super admin has full access to all datasources
        
        Args:
            user: User object
            datasource: DataSource object
            access_type (str): Type of access ('view', 'edit', 'delete', 'execute')
            
        Returns:
            bool: True if user can access the datasource
        """
        if not user or not datasource:
            return False
        
        # Multi-tenant isolation check
        if datasource.org_id != user.org_id:
            return False
        
        # Check if user is the owner
        if hasattr(datasource, 'owner') and datasource.owner == user.id:
            return True
        
        # For view and execute access, check project membership
        if access_type in ['view', 'execute']:
            # Get projects the datasource is assigned to
            from redash.models.project import ProjectDataSource
            project_datasources = ProjectDataSource.query.filter(
                ProjectDataSource.data_source_id == datasource.id
            ).all()
            
            # Check if user is a member of any of these projects
            for pds in project_datasources:
                member = ProjectMember.query.filter(
                    ProjectMember.project_id == pds.project_id,
                    ProjectMember.user_id == user.id
                ).first()
                if member:
                    return True
        
        # Check if user has organization-wide permissions
        if PermissionService.has_organization_admin_role(user):
            if access_type == 'view':
                return True
            # Org admin can view but not necessarily edit/delete others' datasources
            # unless they have explicit permission
            if PermissionService.has_permission(user, 'view_all_datasources'):
                return access_type == 'view'
        
        # Check if user is super admin
        if PermissionService.has_super_admin_role(user):
            return True
        
        return False
    
    @staticmethod
    def can_access_query(user, query, access_type='view'):
        """
        Check if user can access a query.
        
        Access rules:
        - Owner has full access (view, edit, delete, execute)
        - Project members have view and execute access if query is assigned to project
        - Designers can edit queries in projects where they are members
        - Organization admin has full access to all queries in organization
        - Super admin has full access to all queries
        
        Args:
            user: User object
            query: Query object
            access_type (str): Type of access ('view', 'edit', 'delete', 'execute')
            
        Returns:
            bool: True if user can access the query
        """
        if not user or not query:
            return False
        
        # Multi-tenant isolation check
        if query.org_id != user.org_id:
            return False
        
        # Check if user is the owner
        if hasattr(query, 'user_id') and query.user_id == user.id:
            return True
        
        # Check if query is assigned to a project the user is a member of
        if hasattr(query, 'project_id') and query.project_id:
            member = ProjectMember.query.filter(
                ProjectMember.project_id == query.project_id,
                ProjectMember.user_id == user.id
            ).first()
            
            if member:
                # Project members can view and execute
                if access_type in ['view', 'execute']:
                    return True
                
                # Designers can edit queries in their projects
                if access_type == 'edit' and PermissionService.has_designer_role(user):
                    return True
                
                # Project owners and admins can edit
                if access_type == 'edit' and member.can_manage_project():
                    return True
        
        # Check if user has organization-wide permissions
        if PermissionService.has_organization_admin_role(user):
            return True
        
        # Check if user is super admin
        if PermissionService.has_super_admin_role(user):
            return True
        
        return False
    
    @staticmethod
    def can_delete_project(user, project):
        """
        Check if user can delete a project.
        
        Only project owners, organization admins, and super admins can delete projects.
        Project admins cannot delete projects.
        
        Args:
            user: User object
            project: Project object
            
        Returns:
            bool: True if user can delete the project
        """
        if not user or not project:
            return False
        
        # Multi-tenant isolation check
        if project.org_id != user.org_id:
            return False
        
        # Check if user is project owner
        if PermissionService.is_project_owner(user, project):
            return True
        
        # Check if user is organization admin
        if PermissionService.has_organization_admin_role(user, project.organization):
            return True
        
        # Check if user is super admin
        if PermissionService.has_super_admin_role(user):
            return True
        
        # Project admins cannot delete projects
        return False
    
    @staticmethod
    def is_project_member(user, project):
        """
        Check if user is a member of a project.
        
        Args:
            user: User object
            project: Project object
            
        Returns:
            bool: True if user is a project member
        """
        if not user or not project:
            return False
        
        # Check project membership
        member = ProjectMember.query.filter(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id
        ).first()
        
        return member is not None
    
    @staticmethod
    def get_user_project_ids(user, org=None):
        """
        Get all project IDs that a user is a member of.
        
        Args:
            user: User object
            org: Optional organization
            
        Returns:
            list: List of project IDs
        """
        if not user:
            return []
        
        if org is None:
            org = user.org
        
        # Get all project memberships
        memberships = ProjectMember.query.filter(
            ProjectMember.user_id == user.id
        ).all()
        
        # Filter by organization if needed
        from redash.models.project import Project
        project_ids = []
        for membership in memberships:
            project = Project.query.get(membership.project_id)
            if project and project.org_id == org.id:
                project_ids.append(project.id)
        
        return project_ids
