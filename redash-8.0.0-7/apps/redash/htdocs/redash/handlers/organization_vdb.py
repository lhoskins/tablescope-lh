"""
Organization VDB API Handlers

API endpoints for managing VDB (Virtual Database) configurations for organizations.
"""

import logging
from flask import request, jsonify
from flask_restful import abort

from redash import models
from redash.handlers.base import BaseResource, get_object_or_404, require_fields
from redash.permissions import require_admin
from redash.services import VDBManagementService, VDBProvisioningError
from redash.services.vdb_context import VDBContextService, VDBNotConfiguredError

logger = logging.getLogger(__name__)


class OrganizationVDBResource(BaseResource):
    """
    API for managing organization VDB configurations.
    
    Endpoints:
    - GET /api/organizations/<org_id>/vdb - Get VDB config
    - POST /api/organizations/<org_id>/vdb - Provision VDB
    - DELETE /api/organizations/<org_id>/vdb - Delete VDB
    """
    
    @require_admin
    def get(self, org_id):
        """
        GET /api/organizations/<org_id>/vdb
        
        Retrieve VDB configuration for an organization.
        
        Returns:
            VDB configuration dict or 404 if not found
        """
        logger.info('=' * 80)
        logger.info('VDB GET HANDLER - START')
        logger.info('GET method called for org_id: {}'.format(org_id))
        logger.info('org_id type: {}'.format(type(org_id)))
        
        # Verify organization exists
        logger.info('Step 1: Verifying organization exists...')
        organization = get_object_or_404(
            models.Organization.get_by_id,
            org_id
        )
        logger.info('Organization found: id={}, name={}'.format(organization.id, organization.name))
        
        # Get VDB config
        logger.info('Step 2: Getting VDB config from VDBContextService...')
        vdb_config = VDBContextService.get_vdb_for_organization(org_id)
        logger.info('VDB config result: {}'.format(vdb_config))
        
        if not vdb_config:
            logger.error('VDB config is None! Returning 404')
            logger.info('=' * 80)
            abort(404, message='No VDB configured for organization {}'.format(org_id))
        
        self.record_event({
            'action': 'view',
            'object_id': vdb_config.id,
            'object_type': 'organization_vdb',
            'org_id': org_id
        })
        
        return vdb_config.to_dict(include_credentials=True)
    
    @require_admin
    def post(self, org_id):
        """
        POST /api/organizations/<org_id>/vdb
        
        Provision a new VDB for an organization.
        
        Request Body (optional):
            {
                "force": true  // Force re-provisioning if VDB already exists
            }
        
        Returns:
            VDB configuration dict
        """
        logger.info('POST method called for org_id: {}'.format(org_id))
        
        # Verify organization exists
        organization = get_object_or_404(
            models.Organization.get_by_id,
            org_id
        )
        
        req = request.get_json(silent=True) or {}
        force = req.get('force', False)
        
        # Check if VDB already exists
        existing_vdb = VDBContextService.get_vdb_for_organization(org_id)
        
        if existing_vdb and not force:
            abort(400, message='VDB already exists for organization {}. Use force=true to re-provision.'.format(org_id))
        
        try:
            # Delete existing VDB if force=true
            if existing_vdb and force:
                logger.info('Force re-provisioning VDB for org {}'.format(org_id))
                vdb_service = VDBManagementService()
                vdb_service.delete_vdb(existing_vdb.vdb_id)
                models.db.session.delete(existing_vdb)
                models.db.session.commit()
            
            # Provision new VDB
            vdb_service = VDBManagementService()
            vdb_config = vdb_service.provision_vdb_for_organization(organization)
            
            models.db.session.commit()
            
            self.record_event({
                'action': 'create',
                'object_id': vdb_config.id,
                'object_type': 'organization_vdb',
                'org_id': org_id,
                'vdb_id': vdb_config.vdb_id
            })
            
            logger.info('VDB provisioned successfully for org {}: {}'.format(
                org_id, vdb_config.vdb_id
            ))
            
            return vdb_config.to_dict(include_credentials=True)
            
        except VDBProvisioningError as e:
            logger.error('VDB provisioning failed for org {}: {}'.format(org_id, str(e)))
            abort(500, message='VDB provisioning failed: {}'.format(str(e)))
            
        except Exception as e:
            logger.error('Unexpected error provisioning VDB for org {}: {}'.format(org_id, str(e)))
            models.db.session.rollback()
            abort(500, message='Failed to provision VDB: {}'.format(str(e)))
    
    @require_admin
    def delete(self, org_id):
        """
        DELETE /api/organizations/<org_id>/vdb
        
        Delete VDB for an organization.
        
        Returns:
            204 No Content on success
        """
        logger.info('DELETE method called for org_id: {}'.format(org_id))
        
        # Verify organization exists
        organization = get_object_or_404(
            models.Organization.get_by_id,
            org_id
        )
        
        # Get VDB config
        vdb_config = VDBContextService.get_vdb_for_organization(org_id)
        
        if not vdb_config:
            abort(404, message='No VDB configured for organization {}'.format(org_id))
        
        try:
            # Delete VDB from Teiid
            vdb_service = VDBManagementService()
            result = vdb_service.delete_vdb(vdb_config.vdb_id)
            
            if not result.get('success'):
                logger.warning('Failed to delete VDB from Teiid: {}'.format(result.get('error')))
            
            # Delete VDB config from database
            models.db.session.delete(vdb_config)
            models.db.session.commit()
            
            self.record_event({
                'action': 'delete',
                'object_id': vdb_config.id,
                'object_type': 'organization_vdb',
                'org_id': org_id,
                'vdb_id': vdb_config.vdb_id
            })
            
            logger.info('VDB deleted successfully for org {}: {}'.format(
                org_id, vdb_config.vdb_id
            ))
            
            return '', 204
            
        except Exception as e:
            logger.error('Failed to delete VDB for org {}: {}'.format(org_id, str(e)))
            models.db.session.rollback()
            abort(500, message='Failed to delete VDB: {}'.format(str(e)))


class VDBCredentialRotationResource(BaseResource):
    """
    API for rotating VDB credentials.
    
    Endpoint:
    - POST /api/organizations/<org_id>/vdb/rotate-credentials
    """
    
    @require_admin
    def post(self, org_id):
        """
        POST /api/organizations/<org_id>/vdb/rotate-credentials
        
        Rotate VDB credentials for an organization.
        
        Returns:
            Updated VDB configuration dict
        """
        # Verify organization exists
        organization = get_object_or_404(
            models.Organization.get_by_id,
            org_id
        )
        
        # Get VDB config
        vdb_config = VDBContextService.get_vdb_for_organization(org_id)
        
        if not vdb_config:
            abort(404, message='No VDB configured for organization {}'.format(org_id))
        
        try:
            # Generate new credentials
            from redash.utils.vdb_utils import generate_vdb_credentials
            new_username, new_password = generate_vdb_credentials()
            
            logger.info('Rotating credentials for VDB: {}'.format(vdb_config.vdb_id))
            
            # Update credentials via servlet
            vdb_service = VDBManagementService()
            result = vdb_service.update_vdb_credentials(
                vdb_config.vdb_id,
                new_username,
                new_password
            )
            
            if not result.get('success'):
                raise Exception('Servlet returned error: {}'.format(result.get('error')))
            
            # Update credentials in database
            vdb_config.vdb_username = new_username
            vdb_config.set_encrypted_password(new_password)
            
            models.db.session.commit()
            
            self.record_event({
                'action': 'rotate_credentials',
                'object_id': vdb_config.id,
                'object_type': 'organization_vdb',
                'org_id': org_id,
                'vdb_id': vdb_config.vdb_id
            })
            
            logger.info('Credentials rotated successfully for VDB: {}'.format(vdb_config.vdb_id))
            
            return vdb_config.to_dict(include_credentials=True)
            
        except Exception as e:
            logger.error('Failed to rotate credentials for VDB {}: {}'.format(
                vdb_config.vdb_id, str(e)
            ))
            models.db.session.rollback()
            abort(500, message='Failed to rotate credentials: {}'.format(str(e)))


class VDBHealthCheckResource(BaseResource):
    """
    API for checking VDB health.
    
    Endpoints:
    - GET /api/organizations/<org_id>/vdb/health - Check single VDB
    - GET /api/vdbs/health - Check all VDBs (bulk)
    """
    
    @require_admin
    def get(self, org_id=None):
        """
        GET /api/organizations/<org_id>/vdb/health
        
        Check VDB connectivity and health for a specific organization.
        
        Returns:
            Health status dict
        """
        if org_id:
            return self._check_single_vdb(org_id)
        else:
            return self._check_all_vdbs()
    
    def _check_single_vdb(self, org_id):
        """Check health of a single VDB."""
        # Verify organization exists
        organization = get_object_or_404(
            models.Organization.get_by_id,
            org_id
        )
        
        # Get VDB config
        vdb_config = VDBContextService.get_vdb_for_organization(org_id)
        
        if not vdb_config:
            abort(404, message='No VDB configured for organization {}'.format(org_id))
        
        # Check health
        vdb_service = VDBManagementService()
        health_result = vdb_service.check_vdb_health(vdb_config)
        
        is_healthy = health_result['is_healthy']
        response_time = health_result['response_time']
        
        # Update health status
        status = 'healthy' if is_healthy else 'down'
        vdb_config.update_health_status(status)
        models.db.session.commit()
        
        self.record_event({
            'action': 'health_check',
            'object_id': vdb_config.id,
            'object_type': 'organization_vdb',
            'org_id': org_id,
            'health_status': status
        })
        
        return {
            'vdb_id': vdb_config.vdb_id,
            'org_id': org_id,
            'is_healthy': is_healthy,
            'status': status,  # Frontend expects 'status' not 'health_status'
            'health_status': status,  # Keep for backward compatibility
            'response_time': response_time,
            'last_health_check': vdb_config.last_health_check.isoformat() if vdb_config.last_health_check else None
        }
    
    def _check_all_vdbs(self):
        """Check health of all VDBs (bulk operation)."""
        from redash.models.organization_vdb import OrganizationVDB
        
        all_vdbs = OrganizationVDB.query.filter(OrganizationVDB.is_active == True).all()
        
        results = []
        vdb_service = VDBManagementService()
        
        for vdb_config in all_vdbs:
            health_result = vdb_service.check_vdb_health(vdb_config)
            is_healthy = health_result['is_healthy']
            response_time = health_result['response_time']
            
            status = 'healthy' if is_healthy else 'down'
            vdb_config.update_health_status(status)
            
            results.append({
                'vdb_id': vdb_config.vdb_id,
                'org_id': vdb_config.organization_id,
                'is_healthy': is_healthy,
                'status': status,
                'health_status': status,
                'response_time': response_time,
                'last_health_check': vdb_config.last_health_check.isoformat() if vdb_config.last_health_check else None
            })
        
        models.db.session.commit()
        
        self.record_event({
            'action': 'bulk_health_check',
            'object_type': 'organization_vdb',
            'vdb_count': len(all_vdbs)
        })
        
        return {
            'total': len(results),
            'healthy': sum(1 for r in results if r['is_healthy']),
            'unhealthy': sum(1 for r in results if not r['is_healthy']),
            'vdbs': results
        }
