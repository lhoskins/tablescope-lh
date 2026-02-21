"""
VDB Health Check Resource Handler

API endpoints for checking VDB health and connectivity.
Provides endpoints for monitoring user and shared VDB status.

Requirements: 17.1, 17.2, 17.3, 17.4, 17.5
"""

import logging
from flask import request
from flask_restful import abort

from redash.handlers.base import BaseResource
from redash.permissions import require_admin, is_admin_or_owner
from redash.models import db
from redash.models.user_vdb import UserVDB
from redash.models.shared_vdb import SharedVDB
from redash.services.vdb_management import VDBManagementService

logger = logging.getLogger(__name__)


class UserVDBHealthResource(BaseResource):
    """
    Resource for checking user VDB health.
    
    Endpoint:
    - GET: Check user VDB health and connectivity
    """
    
    def get(self, user_id):
        """
        Check user VDB health and connectivity.
        
        Executes a test query to verify VDB is accessible and returns
        health status and response time.
        
        Permission: User can check their own VDB, or admin can check any user's VDB
        
        Args:
            user_id: User ID
            
        Returns:
            JSON with health status and response time
            
        Requirements: 17.1, 17.3, 17.4, 17.5
        """
        # Check permission
        if not is_admin_or_owner(user_id):
            abort(403, message="You don't have permission to check this user's VDB health.")
        
        # Get user VDB from database
        user_vdb = UserVDB.get_by_user(user_id)
        
        if not user_vdb:
            return {
                'exists': False,
                'user_id': user_id,
                'is_healthy': False,
                'status': 'NOT_CONFIGURED',
                'message': 'No VDB configured for this user'
            }, 404
        
        try:
            # Perform health check
            logger.info('Checking health for user VDB: user_id={}, vdb_id={}'.format(
                user_id, user_vdb.vdb_id
            ))
            
            vdb_service = VDBManagementService()
            health_result = vdb_service.check_vdb_health(user_vdb)
            
            # Update health status in database
            health_status = 'healthy' if health_result.get('is_healthy') else 'down'
            user_vdb.update_health_status(health_status)
            db.session.commit()
            
            # Build response
            result = {
                'exists': True,
                'user_id': user_id,
                'vdb_id': user_vdb.vdb_id,
                'is_healthy': health_result.get('is_healthy', False),
                'status': health_result.get('status', 'UNKNOWN'),
                'response_time': health_result.get('response_time', 0),
                'last_health_check': user_vdb.last_health_check.isoformat() if user_vdb.last_health_check else None,
                'details': health_result.get('details', {})
            }
            
            if not health_result.get('is_healthy'):
                result['error'] = health_result.get('error', 'VDB is not healthy')
            
            self.record_event({
                'action': 'health_check',
                'object_id': user_vdb.id,
                'object_type': 'user_vdb',
                'user_id': user_id,
                'is_healthy': health_result.get('is_healthy')
            })
            
            logger.info('User VDB health check completed: user_id={}, vdb_id={}, healthy={}'.format(
                user_id, user_vdb.vdb_id, health_result.get('is_healthy')
            ))
            
            return result
            
        except Exception as e:
            error_msg = 'Failed to check user VDB health: {}'.format(str(e))
            logger.error(error_msg, exc_info=True)
            
            return {
                'exists': True,
                'user_id': user_id,
                'vdb_id': user_vdb.vdb_id,
                'is_healthy': False,
                'status': 'ERROR',
                'response_time': 0,
                'error': error_msg
            }, 500


class SharedVDBHealthResource(BaseResource):
    """
    Resource for checking shared VDB health.
    
    Endpoint:
    - GET: Check shared VDB health and connectivity
    """
    
    @require_admin
    def get(self, org_id=None):
        """
        Check shared VDB health and connectivity.
        
        Executes a test query to verify VDB is accessible and returns
        health status and response time.
        
        Permission: Admin only
        
        Args:
            org_id: Organization ID (optional, defaults to current org)
            
        Returns:
            JSON with health status and response time
            
        Requirements: 17.2, 17.3, 17.4, 17.5
        """
        # Use current org if not specified
        if org_id is None:
            org_id = self.current_org.id
        
        # Verify user has access to this organization
        if org_id != self.current_org.id and not self.current_user.has_permission('super_admin'):
            abort(403, message="You don't have permission to check this organization's shared VDB health.")
        
        # Get shared VDB from database
        shared_vdb = SharedVDB.get_by_organization(org_id)
        
        if not shared_vdb:
            return {
                'exists': False,
                'organization_id': org_id,
                'is_healthy': False,
                'status': 'NOT_CONFIGURED',
                'message': 'No shared VDB configured for this organization'
            }, 404
        
        try:
            # Perform health check
            logger.info('Checking health for shared VDB: org_id={}, vdb_id={}'.format(
                org_id, shared_vdb.vdb_id
            ))
            
            vdb_service = VDBManagementService()
            health_result = vdb_service.check_vdb_health(shared_vdb)
            
            # Update health status in database
            health_status = 'healthy' if health_result.get('is_healthy') else 'down'
            shared_vdb.update_health_status(health_status)
            db.session.commit()
            
            # Build response
            result = {
                'exists': True,
                'organization_id': org_id,
                'vdb_id': shared_vdb.vdb_id,
                'is_healthy': health_result.get('is_healthy', False),
                'status': health_result.get('status', 'UNKNOWN'),
                'response_time': health_result.get('response_time', 0),
                'last_health_check': shared_vdb.last_health_check.isoformat() if shared_vdb.last_health_check else None,
                'details': health_result.get('details', {})
            }
            
            if not health_result.get('is_healthy'):
                result['error'] = health_result.get('error', 'VDB is not healthy')
            
            self.record_event({
                'action': 'health_check',
                'object_id': shared_vdb.id,
                'object_type': 'shared_vdb',
                'organization_id': org_id,
                'is_healthy': health_result.get('is_healthy')
            })
            
            logger.info('Shared VDB health check completed: org_id={}, vdb_id={}, healthy={}'.format(
                org_id, shared_vdb.vdb_id, health_result.get('is_healthy')
            ))
            
            return result
            
        except Exception as e:
            error_msg = 'Failed to check shared VDB health: {}'.format(str(e))
            logger.error(error_msg, exc_info=True)
            
            return {
                'exists': True,
                'organization_id': org_id,
                'vdb_id': shared_vdb.vdb_id,
                'is_healthy': False,
                'status': 'ERROR',
                'response_time': 0,
                'error': error_msg
            }, 500


class OrganizationVDBsHealthResource(BaseResource):
    """
    Resource for checking health of all user VDBs in an organization.
    
    Endpoint:
    - GET: Check health of all user VDBs in organization
    """
    
    @require_admin
    def get(self, org_id=None):
        """
        Check health of all user VDBs in an organization.
        
        Returns health status for all user VDBs and the shared VDB
        in the organization.
        
        Permission: Admin only
        
        Args:
            org_id: Organization ID (optional, defaults to current org)
            
        Returns:
            JSON with health status for all VDBs
            
        Requirements: 17.3, 17.4, 17.5
        """
        # Use current org if not specified
        if org_id is None:
            org_id = self.current_org.id
        
        # Verify user has access to this organization
        if org_id != self.current_org.id and not self.current_user.has_permission('super_admin'):
            abort(403, message="You don't have permission to check VDB health for this organization.")
        
        try:
            logger.info('Checking health for all VDBs in org_id: {}'.format(org_id))
            
            vdb_service = VDBManagementService()
            
            # Get all user VDBs for organization
            user_vdbs = UserVDB.query.filter_by(organization_id=org_id).all()
            
            # Get shared VDB for organization
            shared_vdb = SharedVDB.get_by_organization(org_id)
            
            # Check health for each user VDB
            user_vdb_health = []
            for user_vdb in user_vdbs:
                try:
                    health_result = vdb_service.check_vdb_health(user_vdb)
                    
                    # Update health status in database
                    health_status = 'healthy' if health_result.get('is_healthy') else 'down'
                    user_vdb.update_health_status(health_status)
                    
                    user_vdb_health.append({
                        'user_id': user_vdb.user_id,
                        'vdb_id': user_vdb.vdb_id,
                        'is_healthy': health_result.get('is_healthy', False),
                        'status': health_result.get('status', 'UNKNOWN'),
                        'response_time': health_result.get('response_time', 0),
                        'last_health_check': user_vdb.last_health_check.isoformat() if user_vdb.last_health_check else None
                    })
                    
                except Exception as e:
                    logger.error('Failed to check health for user VDB {}: {}'.format(
                        user_vdb.vdb_id, str(e)
                    ))
                    user_vdb_health.append({
                        'user_id': user_vdb.user_id,
                        'vdb_id': user_vdb.vdb_id,
                        'is_healthy': False,
                        'status': 'ERROR',
                        'response_time': 0,
                        'error': str(e)
                    })
            
            # Check health for shared VDB
            shared_vdb_health = None
            if shared_vdb:
                try:
                    health_result = vdb_service.check_vdb_health(shared_vdb)
                    
                    # Update health status in database
                    health_status = 'healthy' if health_result.get('is_healthy') else 'down'
                    shared_vdb.update_health_status(health_status)
                    
                    shared_vdb_health = {
                        'vdb_id': shared_vdb.vdb_id,
                        'is_healthy': health_result.get('is_healthy', False),
                        'status': health_result.get('status', 'UNKNOWN'),
                        'response_time': health_result.get('response_time', 0),
                        'last_health_check': shared_vdb.last_health_check.isoformat() if shared_vdb.last_health_check else None
                    }
                    
                except Exception as e:
                    logger.error('Failed to check health for shared VDB {}: {}'.format(
                        shared_vdb.vdb_id, str(e)
                    ))
                    shared_vdb_health = {
                        'vdb_id': shared_vdb.vdb_id,
                        'is_healthy': False,
                        'status': 'ERROR',
                        'response_time': 0,
                        'error': str(e)
                    }
            
            # Commit all health status updates
            db.session.commit()
            
            # Build response
            result = {
                'organization_id': org_id,
                'user_vdbs': user_vdb_health,
                'shared_vdb': shared_vdb_health,
                'total_user_vdbs': len(user_vdbs),
                'healthy_user_vdbs': sum(1 for vdb in user_vdb_health if vdb.get('is_healthy')),
                'shared_vdb_healthy': shared_vdb_health.get('is_healthy') if shared_vdb_health else None
            }
            
            self.record_event({
                'action': 'health_check_all',
                'object_type': 'organization_vdbs',
                'organization_id': org_id,
                'total_vdbs': len(user_vdbs) + (1 if shared_vdb else 0),
                'healthy_vdbs': result['healthy_user_vdbs'] + (1 if result['shared_vdb_healthy'] else 0)
            })
            
            logger.info('Organization VDB health check completed: org_id={}, total={}, healthy={}'.format(
                org_id,
                len(user_vdbs) + (1 if shared_vdb else 0),
                result['healthy_user_vdbs'] + (1 if result['shared_vdb_healthy'] else 0)
            ))
            
            return result
            
        except Exception as e:
            error_msg = 'Failed to check organization VDB health: {}'.format(str(e))
            logger.error(error_msg, exc_info=True)
            abort(500, message=error_msg)
