"""
Shared VDB Resource Handler

API endpoints for managing organization-level shared VDBs (Virtual Databases).
Provides endpoints for provisioning, retrieving, and deleting shared VDBs.

Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6
"""

import logging
from flask import request
from flask_restful import abort

from redash.handlers.base import BaseResource
from redash.permissions import require_admin
from redash.models import db
from redash.models.shared_vdb import SharedVDB
from redash.services.vdb_management import VDBManagementService, VDBProvisioningError

logger = logging.getLogger(__name__)


class SharedVDBResource(BaseResource):
    """
    Resource for managing shared VDB configuration.
    
    Endpoints:
    - GET: Retrieve shared VDB configuration
    - POST: Provision a new shared VDB
    - DELETE: Delete shared VDB
    
    Note: All operations require admin permission
    """
    
    @require_admin
    def get(self, org_id=None):
        """
        Retrieve shared VDB configuration for an organization.
        
        Permission: Admin only
        
        Args:
            org_id: Organization ID (optional, defaults to current org)
            
        Returns:
            JSON with VDB configuration
            
        Requirements: 16.1, 16.4
        """
        # Use current org if not specified
        if org_id is None:
            org_id = self.current_org.id
        
        # Verify user has access to this organization
        if org_id != self.current_org.id and not self.current_user.has_permission('super_admin'):
            abort(403, message="You don't have permission to view this organization's shared VDB.")
        
        # Get shared VDB from database
        shared_vdb = SharedVDB.get_by_organization(org_id)
        
        if not shared_vdb:
            return {
                'exists': False,
                'organization_id': org_id,
                'message': 'No shared VDB configured for this organization'
            }, 404
        
        # Return VDB configuration (without password)
        result = {
            'exists': True,
            'id': shared_vdb.id,
            'organization_id': shared_vdb.organization_id,
            'vdb_id': shared_vdb.vdb_id,
            'vdb_username': shared_vdb.vdb_username,
            'vdb_host': shared_vdb.vdb_host,
            'vdb_port': shared_vdb.vdb_port,
            'is_active': shared_vdb.is_active,
            'health_status': shared_vdb.health_status,
            'last_health_check': shared_vdb.last_health_check.isoformat() if shared_vdb.last_health_check else None,
            'created_at': shared_vdb.created_at.isoformat() if shared_vdb.created_at else None,
            'updated_at': shared_vdb.updated_at.isoformat() if shared_vdb.updated_at else None
        }
        
        self.record_event({
            'action': 'view',
            'object_id': shared_vdb.id,
            'object_type': 'shared_vdb',
            'organization_id': org_id
        })
        
        logger.info('Retrieved shared VDB config for org_id: {}, vdb_id: {}'.format(
            org_id, shared_vdb.vdb_id
        ))
        
        return result
    
    @require_admin
    def post(self, org_id=None):
        """
        Provision a new shared VDB for an organization.
        
        Permission: Admin only
        
        Args:
            org_id: Organization ID (optional, defaults to current org)
            
        Returns:
            JSON with provisioned VDB configuration
            
        Requirements: 16.1, 16.2, 16.5, 16.6
        """
        # Use current org if not specified
        if org_id is None:
            org_id = self.current_org.id
        
        # Verify user has access to this organization
        if org_id != self.current_org.id and not self.current_user.has_permission('super_admin'):
            abort(403, message="You don't have permission to provision a shared VDB for this organization.")
        
        # Check if shared VDB already exists
        existing_vdb = SharedVDB.get_by_organization(org_id)
        if existing_vdb:
            abort(400, message="Shared VDB already exists for organization {}. Use redeploy endpoint to update.".format(org_id))
        
        # Validate request body (optional parameters)
        req = request.get_json(silent=True) or {}
        
        try:
            # Provision shared VDB
            logger.info('Provisioning shared VDB for org_id: {}'.format(org_id))
            
            vdb_service = VDBManagementService()
            shared_vdb = vdb_service.provision_shared_vdb(org_id)
            
            # Commit to database
            db.session.commit()
            
            # Return VDB configuration
            result = {
                'success': True,
                'id': shared_vdb.id,
                'organization_id': shared_vdb.organization_id,
                'vdb_id': shared_vdb.vdb_id,
                'vdb_username': shared_vdb.vdb_username,
                'vdb_host': shared_vdb.vdb_host,
                'vdb_port': shared_vdb.vdb_port,
                'is_active': shared_vdb.is_active,
                'health_status': shared_vdb.health_status,
                'created_at': shared_vdb.created_at.isoformat() if shared_vdb.created_at else None,
                'message': 'Shared VDB provisioned successfully'
            }
            
            self.record_event({
                'action': 'provision',
                'object_id': shared_vdb.id,
                'object_type': 'shared_vdb',
                'organization_id': org_id
            })
            
            logger.info('Shared VDB provisioned successfully for org_id: {}, vdb_id: {}'.format(
                org_id, shared_vdb.vdb_id
            ))
            
            return result, 201
            
        except VDBProvisioningError as e:
            db.session.rollback()
            error_msg = 'Failed to provision shared VDB: {}'.format(str(e))
            logger.error(error_msg)
            abort(500, message=error_msg)
            
        except Exception as e:
            db.session.rollback()
            error_msg = 'Unexpected error provisioning shared VDB: {}'.format(str(e))
            logger.error(error_msg, exc_info=True)
            abort(500, message=error_msg)
    
    @require_admin
    def delete(self, org_id=None):
        """
        Delete shared VDB for an organization.
        
        Permission: Admin only
        
        Args:
            org_id: Organization ID (optional, defaults to current org)
            
        Returns:
            JSON with deletion status
            
        Requirements: 16.3, 16.5, 16.6
        """
        # Use current org if not specified
        if org_id is None:
            org_id = self.current_org.id
        
        # Verify user has access to this organization
        if org_id != self.current_org.id and not self.current_user.has_permission('super_admin'):
            abort(403, message="You don't have permission to delete this organization's shared VDB.")
        
        # Get shared VDB from database
        shared_vdb = SharedVDB.get_by_organization(org_id)
        
        if not shared_vdb:
            abort(404, message="No shared VDB found for organization {}".format(org_id))
        
        vdb_id = shared_vdb.vdb_id
        
        try:
            # Delete VDB via servlet
            logger.info('Deleting shared VDB for org_id: {}, vdb_id: {}'.format(org_id, vdb_id))
            
            vdb_service = VDBManagementService()
            delete_result = vdb_service.delete_vdb(vdb_id)
            
            if not delete_result.get('success'):
                logger.warning('Servlet deletion failed for VDB {}: {}'.format(
                    vdb_id, delete_result.get('error')
                ))
            
            # Delete from database
            db.session.delete(shared_vdb)
            db.session.commit()
            
            result = {
                'success': True,
                'organization_id': org_id,
                'vdb_id': vdb_id,
                'message': 'Shared VDB deleted successfully'
            }
            
            self.record_event({
                'action': 'delete',
                'object_id': shared_vdb.id,
                'object_type': 'shared_vdb',
                'organization_id': org_id
            })
            
            logger.info('Shared VDB deleted successfully for org_id: {}, vdb_id: {}'.format(
                org_id, vdb_id
            ))
            
            return result
            
        except Exception as e:
            db.session.rollback()
            error_msg = 'Failed to delete shared VDB: {}'.format(str(e))
            logger.error(error_msg, exc_info=True)
            abort(500, message=error_msg)


class SharedVDBRedeployResource(BaseResource):
    """
    Resource for redeploying shared VDB with updated shared data sources.
    """
    
    @require_admin
    def post(self, org_id=None):
        """
        Redeploy shared VDB with updated shared data sources.
        
        Permission: Admin only
        
        Args:
            org_id: Organization ID (optional, defaults to current org)
            
        Returns:
            JSON with redeployment status
            
        Requirements: 16.2, 16.5, 16.6
        """
        # Use current org if not specified
        if org_id is None:
            org_id = self.current_org.id
        
        # Verify user has access to this organization
        if org_id != self.current_org.id and not self.current_user.has_permission('super_admin'):
            abort(403, message="You don't have permission to redeploy this organization's shared VDB.")
        
        # Check if shared VDB exists
        shared_vdb = SharedVDB.get_by_organization(org_id)
        if not shared_vdb:
            abort(404, message="No shared VDB found for organization {}. Please provision a shared VDB first.".format(org_id))
        
        try:
            # Redeploy shared VDB
            logger.info('Redeploying shared VDB for org_id: {}, vdb_id: {}'.format(
                org_id, shared_vdb.vdb_id
            ))
            
            vdb_service = VDBManagementService()
            redeploy_result = vdb_service.redeploy_shared_vdb(org_id)
            
            if not redeploy_result.get('success'):
                error_msg = 'VDB redeployment failed: {}'.format(redeploy_result.get('error'))
                logger.error(error_msg)
                abort(500, message=error_msg)
            
            result = {
                'success': True,
                'organization_id': org_id,
                'vdb_id': shared_vdb.vdb_id,
                'message': 'Shared VDB redeployed successfully'
            }
            
            self.record_event({
                'action': 'redeploy',
                'object_id': shared_vdb.id,
                'object_type': 'shared_vdb',
                'organization_id': org_id
            })
            
            logger.info('Shared VDB redeployed successfully for org_id: {}, vdb_id: {}'.format(
                org_id, shared_vdb.vdb_id
            ))
            
            return result
            
        except VDBProvisioningError as e:
            error_msg = 'Failed to redeploy shared VDB: {}'.format(str(e))
            logger.error(error_msg)
            abort(500, message=error_msg)
            
        except Exception as e:
            error_msg = 'Unexpected error redeploying shared VDB: {}'.format(str(e))
            logger.error(error_msg, exc_info=True)
            abort(500, message=error_msg)
