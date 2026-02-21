from collections import defaultdict

from redash.handlers.base import BaseResource, get_object_or_404
from redash.models import AccessPermission, Query, Dashboard, User, db
from redash.permissions import require_admin_or_owner, ACCESS_TYPES
from flask import request
from flask_restful import abort
from sqlalchemy.orm.exc import NoResultFound


model_to_types = {
    'queries': Query,
    'dashboards': Dashboard
}


def get_model_from_type(type):
    model = model_to_types.get(type)
    if model is None:
        abort(404)
    return model


class ObjectPermissionsListResource(BaseResource):
    def get(self, object_type, object_id):
        model = get_model_from_type(object_type)
        obj = get_object_or_404(model.get_by_id_and_org, object_id, self.current_org)

        # TODO: include grantees in search to avoid N+1 queries
        permissions = AccessPermission.find(obj)

        result = defaultdict(list)

        for perm in permissions:
            result[perm.access_type].append(perm.grantee.to_dict())

        return result

    def post(self, object_type, object_id):
        model = get_model_from_type(object_type)
        obj = get_object_or_404(model.get_by_id_and_org, object_id, self.current_org)

        require_admin_or_owner(obj.user_id)

        req = request.get_json(True)

        access_type = req['access_type']

        if access_type not in ACCESS_TYPES:
            abort(400, message='Unknown access type.')

        try:
            grantee = User.get_by_id_and_org(req['user_id'], self.current_org)
        except NoResultFound:
            abort(400, message='User not found.')

        permission = AccessPermission.grant(obj, access_type, grantee, self.current_user)
        db.session.commit()

        self.record_event({
            'action': 'grant_permission',
            'object_id': object_id,
            'object_type': object_type,
            'grantee': grantee.id,
            'access_type': access_type,
        })

        return permission.to_dict()

    def delete(self, object_type, object_id):
        model = get_model_from_type(object_type)
        obj = get_object_or_404(model.get_by_id_and_org, object_id,
                                self.current_org)

        require_admin_or_owner(obj.user_id)

        req = request.get_json(True)
        grantee_id = req['user_id']
        access_type = req['access_type']

        grantee = User.query.get(req['user_id'])
        if grantee is None:
            abort(400, message='User not found.')

        AccessPermission.revoke(obj, grantee, access_type)
        db.session.commit()

        self.record_event({
            'action': 'revoke_permission',
            'object_id': object_id,
            'object_type': object_type,
            'access_type': access_type,
            'grantee_id': grantee_id
        })


class CheckPermissionResource(BaseResource):
    def get(self, object_type, object_id, access_type):
        model = get_model_from_type(object_type)
        obj = get_object_or_404(model.get_by_id_and_org, object_id,
                                self.current_org)

        has_access = AccessPermission.exists(obj, access_type,
                                             self.current_user)

        return {'response': has_access}


class PermissionCheckResource(BaseResource):
    """
    Resource for checking if the current user has a specific permission.
    
    POST /api/permissions/check
    Checks if the current user has the specified permission for a resource.
    """
    
    def post(self):
        """
        Check if current user has a specific permission.
        
        This endpoint allows checking permissions for the authenticated user
        against specific resources or general permissions.
        
        Request body:
            {
                "permission": "edit_query",  # Required
                "resource_type": "query",    # Optional
                "resource_id": 123           # Optional
            }
            
        Returns:
            JSON object with:
            - has_permission: boolean indicating if user has the permission
            - user_id: ID of the checked user
            - permission: The permission that was checked
            
        Requirements: 11.1-11.5
        """
        from flask_login import current_user
        from redash.services.permission_service import PermissionService
        from redash.authentication import current_org
        import logging
        
        logger = logging.getLogger(__name__)
        
        logger.info("=== PERMISSION CHECK API CALLED ===")
        
        try:
            # Check authentication
            user = current_user._get_current_object()
            if not user or not user.is_authenticated:
                abort(401, message="Authentication required")
            
            org = current_org._get_current_object()
            
            # Get request data
            data = request.get_json()
            if not data:
                abort(400, message="No data provided")
            
            permission = data.get('permission')
            if not permission:
                abort(400, message="permission is required")
            
            resource_type = data.get('resource_type')
            resource_id = data.get('resource_id')
            
            # If resource is specified, look it up
            resource = None
            if resource_type and resource_id:
                resource = _get_resource(resource_type, resource_id, org)
                if not resource:
                    # Resource not found or doesn't belong to organization
                    # Return false instead of 404 for permission checks
                    logger.info(
                        "Permission check: resource not found - user=%s, permission=%s, resource_type=%s, resource_id=%s",
                        user.id, permission, resource_type, resource_id
                    )
                    return {
                        'has_permission': False,
                        'user_id': user.id,
                        'permission': permission,
                        'resource_type': resource_type,
                        'resource_id': resource_id,
                        'reason': 'Resource not found'
                    }
            
            # Check permission using appropriate method based on resource type
            has_permission = False
            
            if resource and resource_type:
                # Use AccessControl for resource-specific checks
                from redash.services.access_control import AccessControl
                
                # Map permission names to access types
                access_type_map = {
                    'edit_query': 'edit',
                    'delete_query': 'delete',
                    'view_query': 'view',
                    'execute_query': 'execute',
                    'edit_datasource': 'edit',
                    'delete_datasource': 'delete',
                    'view_datasource': 'view',
                    'edit_project': 'edit',
                    'delete_project': 'delete',
                    'view_project': 'view',
                    'manage_project': 'manage',
                }
                
                access_type = access_type_map.get(permission, 'view')
                
                if resource_type == 'query':
                    has_permission = AccessControl.check_query_access(user, resource, access_type)
                elif resource_type == 'datasource':
                    has_permission = AccessControl.check_datasource_access(user, resource, access_type)
                elif resource_type == 'project':
                    has_permission = AccessControl.check_project_access(user, resource, access_type)
                else:
                    # Fallback to general permission check
                    has_permission = PermissionService.has_permission(
                        user=user,
                        permission=permission,
                        resource=resource,
                        org=org
                    )
            else:
                # No resource specified, use general permission check
                has_permission = PermissionService.has_permission(
                    user=user,
                    permission=permission,
                    resource=resource,
                    org=org
                )
            
            logger.info(
                "Permission check: user=%s, permission=%s, resource_type=%s, resource_id=%s, result=%s",
                user.id, permission, resource_type, resource_id, has_permission
            )
            
            # Build response
            response = {
                'has_permission': has_permission,
                'user_id': user.id,
                'permission': permission
            }
            
            if resource_type:
                response['resource_type'] = resource_type
            if resource_id:
                response['resource_id'] = resource_id
            
            return response
            
        except Exception as e:
            logger.error("Error checking permission: %s", str(e), exc_info=True)
            return {"error": "Failed to check permission: {}".format(str(e))}, 500


# RBAC Decorators for API Endpoint Protection

from functools import wraps
from flask import g
from flask_login import current_user
from redash.services.permission_service import PermissionService
from redash.services.access_control import AccessControl
from redash.models.project import Project
from redash.authentication import current_org


def require_permission(permission):
    """
    Decorator to require a specific permission for an endpoint.
    
    This decorator checks if the current user has the specified permission
    before allowing access to the endpoint. If the user lacks the permission,
    a 403 Forbidden response is returned.
    
    Usage:
        @require_permission('create_query')
        def post(self):
            # Create query logic
            ...
    
    Args:
        permission (str): The permission string to check (e.g., 'create_query', 'edit_datasource')
    
    Returns:
        function: Decorated function that checks permission before execution
    
    Raises:
        403: If user lacks the required permission
    
    Requirements: 11.1-11.5
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from redash.services.audit_service import audit_permission_check
            
            # Get current user from Flask-Login
            user = current_user._get_current_object()
            
            if not user or not user.is_authenticated:
                abort(401, message="Authentication required")
            
            # Check if user has the required permission
            has_permission = PermissionService.has_permission(user, permission)
            
            if not has_permission:
                # Log permission denial
                audit_permission_check(user, permission, resource=None, granted=False)
                abort(403, message="Insufficient permissions to perform this action")
            
            # Log successful permission check (optional - can be disabled for performance)
            # audit_permission_check(user, permission, resource=None, granted=True)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_resource_access(resource_type, access_type='view', resource_param='id'):
    """
    Decorator to require access to a specific resource.
    
    This decorator checks if the current user has the specified access type
    to a resource (datasource, query, or project). It looks up the resource
    by ID from the request parameters and validates access using AccessControl.
    
    Usage:
        @require_resource_access('query', 'edit', 'query_id')
        def post(self, query_id):
            # Edit query logic
            ...
        
        @require_resource_access('datasource', 'delete')
        def delete(self, id):
            # Delete datasource logic
            ...
    
    Args:
        resource_type (str): Type of resource ('datasource', 'query', 'project')
        access_type (str): Type of access required ('view', 'edit', 'delete', 'execute')
        resource_param (str): Name of the parameter containing the resource ID (default: 'id')
    
    Returns:
        function: Decorated function that checks resource access before execution
    
    Raises:
        404: If resource not found or belongs to different organization
        403: If user lacks required access to the resource
    
    Requirements: 8.3, 8.4, 11.1-11.5
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from redash.services.audit_service import audit_permission_check
            
            # Get current user and organization
            user = current_user._get_current_object()
            org = current_org._get_current_object()
            
            if not user or not user.is_authenticated:
                abort(401, message="Authentication required")
            
            # Get resource ID from kwargs
            resource_id = kwargs.get(resource_param)
            if not resource_id:
                abort(400, message="Missing required parameter: {}".format(resource_param))
            
            # Look up the resource
            resource = _get_resource(resource_type, resource_id, org)
            
            if not resource:
                abort(404, message="{} not found".format(resource_type.capitalize()))
            
            # Check organization boundary (multi-tenant isolation)
            if hasattr(resource, 'org_id') and resource.org_id != org.id:
                # Return 404 instead of 403 to prevent information leakage
                abort(404, message="{} not found".format(resource_type.capitalize()))
            
            # Check access using AccessControl
            has_access = False
            if resource_type == 'datasource':
                has_access = AccessControl.check_datasource_access(user, resource, access_type)
            elif resource_type == 'query':
                has_access = AccessControl.check_query_access(user, resource, access_type)
            elif resource_type == 'project':
                has_access = AccessControl.check_project_access(user, resource, access_type)
            else:
                abort(400, message="Unknown resource type: {}".format(resource_type))
            
            if not has_access:
                # Log permission denial with resource context
                permission_name = '{}_{}'.format(access_type, resource_type)
                audit_permission_check(user, permission_name, resource=resource, granted=False)
                abort(403, message="Access denied")
            
            # Store resource in kwargs for use in the handler
            kwargs['{}_obj'.format(resource_type)] = resource
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_project_access(access_type='view'):
    """
    Decorator to require access to a project.
    
    This decorator is specifically designed for project-related endpoints.
    It checks if the user has the specified access type to a project,
    validates organization boundaries, and checks project membership.
    
    For 'manage' access, it verifies that the user is either:
    - The project owner
    - A project admin
    - An organization admin
    - A super admin
    
    Usage:
        @require_project_access('manage')
        def post(self, project_id):
            # Add project member logic
            ...
        
        @require_project_access('view')
        def get(self, project_id):
            # View project details logic
            ...
    
    Args:
        access_type (str): Type of access required ('view', 'edit', 'delete', 'manage')
    
    Returns:
        function: Decorated function that checks project access before execution
    
    Raises:
        404: If project not found or belongs to different organization
        403: If user lacks required access to the project
    
    Requirements: 4.2-4.8, 5.2-5.8, 8.1-8.5
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get current user and organization
            user = current_user._get_current_object()
            org = current_org._get_current_object()
            
            if not user or not user.is_authenticated:
                abort(401, message="Authentication required")
            
            # Get project ID from kwargs
            project_id = kwargs.get('project_id')
            if not project_id:
                abort(400, message="Missing required parameter: project_id")
            
            # Look up the project
            project = Project.query.get(project_id)
            
            if not project:
                abort(404, message="Project not found")
            
            # Check organization boundary (multi-tenant isolation)
            if project.org_id != org.id:
                # Return 404 instead of 403 to prevent information leakage
                abort(404, message="Project not found")
            
            # Check access based on access type
            if access_type == 'manage':
                # For management access, check if user can manage the project
                if not PermissionService.can_manage_project(user, project):
                    abort(403, message="Insufficient permissions to manage this project")
            elif access_type == 'delete':
                # For delete access, check if user can delete the project
                if not PermissionService.can_delete_project(user, project):
                    abort(403, message="Insufficient permissions to delete this project")
            elif access_type == 'edit':
                # For edit access, check if user can manage the project
                if not PermissionService.can_manage_project(user, project):
                    abort(403, message="Insufficient permissions to edit this project")
            elif access_type == 'view':
                # For view access, check if user is a project member
                if not PermissionService.is_project_member(user, project):
                    # Also allow org admins and super admins to view
                    if not (PermissionService.has_organization_admin_role(user) or 
                            PermissionService.has_super_admin_role(user)):
                        abort(403, message="Access denied")
            else:
                abort(400, message="Unknown access type: {}".format(access_type))
            
            # Store project in kwargs for use in the handler
            kwargs['project_obj'] = project
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def _get_resource(resource_type, resource_id, org):
    """
    Helper function to look up a resource by type and ID.
    
    Args:
        resource_type (str): Type of resource ('datasource', 'query', 'project')
        resource_id (int): Resource ID
        org: Organization object
    
    Returns:
        Resource object or None if not found
    """
    from redash.models import DataSource, Query
    
    if resource_type == 'datasource':
        return DataSource.get_by_id_and_org(resource_id, org)
    elif resource_type == 'query':
        return Query.get_by_id_and_org(resource_id, org)
    elif resource_type == 'project':
        project = Project.query.get(resource_id)
        if project and project.org_id == org.id:
            return project
        return None
    else:
        return None
