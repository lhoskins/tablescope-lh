"""
User VDB Resource Handler

API endpoints for managing user-level VDBs (Virtual Databases).
Provides endpoints for provisioning, retrieving, and deleting user VDBs.

Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6
"""

import logging
from flask import request
from flask_restful import abort

from redash.handlers.base import BaseResource
from redash.permissions import require_permission, is_admin_or_owner
from redash.models import db
from redash.models.user_vdb import UserVDB
from redash.services.vdb_management import VDBManagementService, VDBProvisioningError

logger = logging.getLogger(__name__)


class UserVDBResource(BaseResource):
    """
    Resource for managing user VDB configuration.
    
    Endpoints:
    - GET: Retrieve user VDB configuration
    - POST: Provision a new user VDB
    - DELETE: Delete user VDB
    """
    
    def get(self, user_id):
        """
        Retrieve user VDB configuration.
        
        Permission: User can view their own VDB, or admin can view any user's VDB
        
        Args:
            user_id: User ID
            
        Returns:
            JSON with VDB configuration
            
        Requirements: 16.1, 16.4
        """
        # Check permission: user can view their own VDB or admin can view any
        if not is_admin_or_owner(user_id):
            abort(403, message="You don't have permission to view this user's VDB configuration.")
        
        # Get user VDB from database
        user_vdb = UserVDB.get_by_user(user_id)
        
        if not user_vdb:
            return {
                'exists': False,
                'user_id': user_id,
                'message': 'No VDB configured for this user'
            }, 404
        
        # Return VDB configuration (without password)
        result = {
            'exists': True,
            'id': user_vdb.id,
            'user_id': user_vdb.user_id,
            'organization_id': user_vdb.organization_id,
            'vdb_id': user_vdb.vdb_id,
            'vdb_username': user_vdb.vdb_username,
            'vdb_host': user_vdb.vdb_host,
            'vdb_port': user_vdb.vdb_port,
            'is_active': user_vdb.is_active,
            'health_status': user_vdb.health_status,
            'last_health_check': user_vdb.last_health_check.isoformat() if user_vdb.last_health_check else None,
            'created_at': user_vdb.created_at.isoformat() if user_vdb.created_at else None,
            'updated_at': user_vdb.updated_at.isoformat() if user_vdb.updated_at else None
        }
        
        self.record_event({
            'action': 'view',
            'object_id': user_vdb.id,
            'object_type': 'user_vdb',
            'user_id': user_id
        })
        
        logger.info('Retrieved user VDB config for user_id: {}, vdb_id: {}'.format(
            user_id, user_vdb.vdb_id
        ))
        
        return result
    
    def post(self, user_id):
        """
        Provision a new user VDB.
        
        Permission: User can provision their own VDB, or admin can provision for any user
        
        Args:
            user_id: User ID
            
        Returns:
            JSON with provisioned VDB configuration
            
        Requirements: 16.1, 16.2, 16.5, 16.6
        """
        # Check permission: user can provision their own VDB or admin can provision for any
        if not is_admin_or_owner(user_id):
            abort(403, message="You don't have permission to provision a VDB for this user.")
        
        # Check if user VDB already exists
        existing_vdb = UserVDB.get_by_user(user_id)
        if existing_vdb:
            abort(400, message="User VDB already exists for user {}. Use redeploy endpoint to update.".format(user_id))
        
        # Get user to verify existence and get org_id
        from redash.models import User
        user = User.query.get(user_id)
        if not user:
            abort(404, message="User {} not found".format(user_id))
        
        org_id = user.org_id
        
        # Validate request body (optional parameters)
        req = request.get_json(silent=True) or {}
        
        try:
            # Provision user VDB
            logger.info('Provisioning user VDB for user_id: {}, org_id: {}'.format(user_id, org_id))
            
            vdb_service = VDBManagementService()
            user_vdb = vdb_service.provision_user_vdb(user_id, org_id)
            
            # Commit to database
            db.session.commit()
            
            # Return VDB configuration
            result = {
                'success': True,
                'id': user_vdb.id,
                'user_id': user_vdb.user_id,
                'organization_id': user_vdb.organization_id,
                'vdb_id': user_vdb.vdb_id,
                'vdb_username': user_vdb.vdb_username,
                'vdb_host': user_vdb.vdb_host,
                'vdb_port': user_vdb.vdb_port,
                'is_active': user_vdb.is_active,
                'health_status': user_vdb.health_status,
                'created_at': user_vdb.created_at.isoformat() if user_vdb.created_at else None,
                'message': 'User VDB provisioned successfully'
            }
            
            self.record_event({
                'action': 'provision',
                'object_id': user_vdb.id,
                'object_type': 'user_vdb',
                'user_id': user_id
            })
            
            logger.info('User VDB provisioned successfully for user_id: {}, vdb_id: {}'.format(
                user_id, user_vdb.vdb_id
            ))
            
            return result, 201
            
        except VDBProvisioningError as e:
            db.session.rollback()
            error_msg = 'Failed to provision user VDB: {}'.format(str(e))
            logger.error(error_msg)
            abort(500, message=error_msg)
            
        except Exception as e:
            db.session.rollback()
            error_msg = 'Unexpected error provisioning user VDB: {}'.format(str(e))
            logger.error(error_msg, exc_info=True)
            abort(500, message=error_msg)
    
    def delete(self, user_id):
        """
        Delete user VDB.
        
        Permission: User can delete their own VDB, or admin can delete any user's VDB
        
        Args:
            user_id: User ID
            
        Returns:
            JSON with deletion status
            
        Requirements: 16.3, 16.5, 16.6
        """
        # Check permission: user can delete their own VDB or admin can delete any
        if not is_admin_or_owner(user_id):
            abort(403, message="You don't have permission to delete this user's VDB.")
        
        # Get user VDB from database
        user_vdb = UserVDB.get_by_user(user_id)
        
        if not user_vdb:
            abort(404, message="No VDB found for user {}".format(user_id))
        
        vdb_id = user_vdb.vdb_id
        
        try:
            # Delete VDB via servlet
            logger.info('Deleting user VDB for user_id: {}, vdb_id: {}'.format(user_id, vdb_id))
            
            vdb_service = VDBManagementService()
            delete_result = vdb_service.delete_vdb(vdb_id)
            
            if not delete_result.get('success'):
                logger.warning('Servlet deletion failed for VDB {}: {}'.format(
                    vdb_id, delete_result.get('error')
                ))
            
            # Delete from database
            db.session.delete(user_vdb)
            db.session.commit()
            
            result = {
                'success': True,
                'user_id': user_id,
                'vdb_id': vdb_id,
                'message': 'User VDB deleted successfully'
            }
            
            self.record_event({
                'action': 'delete',
                'object_id': user_vdb.id,
                'object_type': 'user_vdb',
                'user_id': user_id
            })
            
            logger.info('User VDB deleted successfully for user_id: {}, vdb_id: {}'.format(
                user_id, vdb_id
            ))
            
            return result
            
        except Exception as e:
            db.session.rollback()
            error_msg = 'Failed to delete user VDB: {}'.format(str(e))
            logger.error(error_msg, exc_info=True)
            abort(500, message=error_msg)


class UserVDBRedeployResource(BaseResource):
    """
    Resource for redeploying user VDB with updated data sources/queries.
    """
    
    def post(self, user_id):
        """
        Redeploy user VDB with updated data sources/queries.
        
        Permission: User can redeploy their own VDB, or admin can redeploy any user's VDB
        
        Args:
            user_id: User ID
            
        Returns:
            JSON with redeployment status
            
        Requirements: 16.2, 16.5, 16.6
        """
        # Check permission
        if not is_admin_or_owner(user_id):
            abort(403, message="You don't have permission to redeploy this user's VDB.")
        
        # Check if user VDB exists
        user_vdb = UserVDB.get_by_user(user_id)
        if not user_vdb:
            abort(404, message="No VDB found for user {}. Please provision a VDB first.".format(user_id))
        
        try:
            # Redeploy user VDB
            logger.info('Redeploying user VDB for user_id: {}, vdb_id: {}'.format(
                user_id, user_vdb.vdb_id
            ))
            
            vdb_service = VDBManagementService()
            redeploy_result = vdb_service.redeploy_user_vdb(user_id)
            
            if not redeploy_result.get('success'):
                error_msg = 'VDB redeployment failed: {}'.format(redeploy_result.get('error'))
                logger.error(error_msg)
                abort(500, message=error_msg)
            
            result = {
                'success': True,
                'user_id': user_id,
                'vdb_id': user_vdb.vdb_id,
                'message': 'User VDB redeployed successfully'
            }
            
            self.record_event({
                'action': 'redeploy',
                'object_id': user_vdb.id,
                'object_type': 'user_vdb',
                'user_id': user_id
            })
            
            logger.info('User VDB redeployed successfully for user_id: {}, vdb_id: {}'.format(
                user_id, user_vdb.vdb_id
            ))
            
            return result
            
        except VDBProvisioningError as e:
            error_msg = 'Failed to redeploy user VDB: {}'.format(str(e))
            logger.error(error_msg)
            abort(500, message=error_msg)
            
        except Exception as e:
            error_msg = 'Unexpected error redeploying user VDB: {}'.format(str(e))
            logger.error(error_msg, exc_info=True)
            abort(500, message=error_msg)
