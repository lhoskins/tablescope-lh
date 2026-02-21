"""
Admin API for Organization Management with VDB Provisioning

This module provides admin-only endpoints for creating and managing organizations
with automatic VDB provisioning and customer folder creation.
"""

import re
from flask import request
from flask_login import login_required

from redash import models
from redash.handlers import routes
from redash.handlers.base import BaseResource, json_response, require_fields, record_event
from redash.permissions import require_super_admin
from redash.authentication import current_org
from flask_login import current_user
from redash.models import db
from redash.services.vdb_management import VDBManagementService
from redash.services.customer_folders import CustomerFolderService

import logging

logger = logging.getLogger(__name__)


def validate_slug(slug):
    """
    Validate organization slug format.
    
    Rules:
    - Lowercase alphanumeric with hyphens
    - Must start with a letter
    - 3-50 characters
    - No consecutive hyphens
    """
    if not slug:
        return False, "Slug is required"
    
    if len(slug) < 3 or len(slug) > 50:
        return False, "Slug must be between 3 and 50 characters"
    
    if not re.match(r'^[a-z][a-z0-9-]*$', slug):
        return False, "Slug must start with a letter and contain only lowercase letters, numbers, and hyphens"
    
    if '--' in slug:
        return False, "Slug cannot contain consecutive hyphens"
    
    if slug.endswith('-'):
        return False, "Slug cannot end with a hyphen"
    
    return True, None


class AdminOrganizationListResource(BaseResource):
    """
    Admin endpoint for managing organizations.
    
    GET /api/admin/organizations
    - Lists all organizations
    
    POST /api/admin/organizations
    - Creates new organization
    - Validates slug format and uniqueness
    - Creates customer folder structure
    - Provisions VDB automatically
    - Returns detailed response with VDB status
    """
    
    decorators = [require_super_admin, login_required]
    
    def get(self):
        """
        List all organizations.
        
        Response:
        [
            {
                "id": 1,
                "name": "Organization Name",
                "slug": "organization-slug",
                "created_at": "2025-11-14T10:00:00Z",
                "settings": {...}
            },
            ...
        ]
        """
        try:
            organizations = models.Organization.query.all()
            return json_response({
                'results': [org.to_dict() for org in organizations]
            })
        except Exception as e:
            logger.error("Failed to list organizations: {}".format(str(e)))
            return json_response({
                'error': 'Failed to list organizations: {}'.format(str(e))
            }, status=500)
    
    def post(self):
        """
        Create a new organization with automatic VDB provisioning.
        
        Request Body:
        {
            "name": "Organization Name",
            "slug": "organization-slug",
            "provision_vdb": true  # Optional, defaults to true
        }
        
        Response:
        {
            "organization": {
                "id": 1,
                "name": "Organization Name",
                "slug": "organization-slug",
                "created_at": "2025-11-14T10:00:00Z"
            },
            "vdb_status": {
                "provisioned": true,
                "vdb_id": "vdb_organization_slug",
                "status": "active",
                "error": null
            },
            "folders_status": {
                "created": true,
                "vdb_folder": "/opt/wildfly/teiidfiles/customers/1/vdb",
                "uploads_folder": "/opt/wildfly/teiidfiles/customers/1/uploads",
                "error": null
            }
        }
        """
        req = request.get_json(force=True)
        
        # Validate required fields
        require_fields(req, ['name', 'slug'])
        
        name = req['name'].strip()
        slug = req['slug'].strip().lower()
        provision_vdb = req.get('provision_vdb', True)
        
        # Validate slug format
        is_valid, error_message = validate_slug(slug)
        if not is_valid:
            return json_response({
                'error': error_message
            }, status=400)
        
        # Check slug uniqueness
        existing_org = models.Organization.query.filter(
            models.Organization.slug == slug
        ).first()
        
        if existing_org:
            return json_response({
                'error': 'Organization with slug "{}" already exists'.format(slug)
            }, status=400)
        
        # Create organization
        try:
            organization = models.Organization(name=name, slug=slug)
            db.session.add(organization)
            db.session.flush()  # Get organization ID without committing
            
            logger.info("Created organization: {} (slug: {}, id: {})".format(name, slug, organization.id))
            
            # Record event
            record_event(
                current_org._get_current_object(),
                current_user._get_current_object(),
                {
                    'action': 'create',
                    'object_type': 'organization',
                    'object_id': organization.id,
                    'additional_properties': {
                        'name': name,
                        'slug': slug
                    }
                }
            )
            
            # Initialize response
            response = {
                'organization': {
                    'id': organization.id,
                    'name': organization.name,
                    'slug': organization.slug,
                    'created_at': organization.created_at.isoformat() if organization.created_at else None
                },
                'vdb_status': {
                    'provisioned': False,
                    'vdb_id': None,
                    'status': 'not_provisioned',
                    'error': None
                },
                'folders_status': {
                    'created': False,
                    'vdb_folder': None,
                    'uploads_folder': None,
                    'error': None
                }
            }
            
            # Create customer folders if VDB provisioning is enabled
            if provision_vdb:
                try:
                    folder_service = CustomerFolderService()
                    folders = folder_service.create_customer_folders(organization.id)
                    
                    response['folders_status'] = {
                        'created': True,
                        'vdb_folder': folders['vdb_folder'],
                        'uploads_folder': folders['uploads_folder'],
                        'error': None
                    }
                    
                    logger.info("Created customer folders for organization {}".format(organization.id))
                    
                except Exception as e:
                    logger.error("Failed to create customer folders for organization {}: {}".format(organization.id, str(e)))
                    response['folders_status']['error'] = str(e)
                    # Continue with VDB provisioning even if folder creation fails
                
                # Provision VDB
                try:
                    vdb_service = VDBManagementService()
                    vdb_config = vdb_service.provision_vdb_for_organization(organization)
                    
                    response['vdb_status'] = {
                        'provisioned': True,
                        'vdb_id': vdb_config.vdb_id,
                        'status': 'active' if vdb_config.is_active else 'inactive',
                        'health_status': vdb_config.health_status,
                        'error': None
                    }
                    
                    logger.info("Provisioned VDB for organization {}: {}".format(organization.id, vdb_config.vdb_id))
                    
                except Exception as e:
                    logger.error("Failed to provision VDB for organization {}: {}".format(organization.id, str(e)))
                    response['vdb_status']['error'] = str(e)
                    response['vdb_status']['status'] = 'failed'
                    # Don't rollback organization creation if VDB provisioning fails
            
            # Commit the transaction
            db.session.commit()
            
            return json_response(response, status=201)
            
        except Exception as e:
            db.session.rollback()
            logger.error("Failed to create organization: {}".format(str(e)))
            return json_response({
                'error': 'Failed to create organization: {}'.format(str(e))
            }, status=500)


class AdminOrganizationResource(BaseResource):
    """
    Admin endpoint for managing individual organizations.
    
    GET /api/admin/organizations/<org_id>
    - Get organization details with VDB status
    
    DELETE /api/admin/organizations/<org_id>
    - Delete organization with VDB cleanup
    """
    
    decorators = [require_super_admin, login_required]
    
    def get(self, org_id):
        """
        Get organization details with VDB status.
        """
        organization = models.Organization.query.get_or_404(org_id)
        
        # Get VDB configuration if exists
        vdb_config = models.OrganizationVDB.get_by_organization(org_id)
        
        response = {
            'organization': {
                'id': organization.id,
                'name': organization.name,
                'slug': organization.slug,
                'created_at': organization.created_at.isoformat() if organization.created_at else None
            },
            'vdb': None
        }
        
        if vdb_config:
            response['vdb'] = vdb_config.to_dict(include_credentials=False)
        
        return json_response(response)
    
    def delete(self, org_id):
        """
        Delete organization with VDB cleanup.
        
        This will:
        1. Delete VDB from Teiid server
        2. Archive customer folders
        3. Delete organization record
        """
        organization = models.Organization.query.get_or_404(org_id)
        
        try:
            # Get VDB configuration
            vdb_config = models.OrganizationVDB.get_by_organization(org_id)
            
            cleanup_status = {
                'vdb_deleted': False,
                'folders_archived': False,
                'organization_deleted': False,
                'errors': []
            }
            
            # Delete VDB if exists
            if vdb_config:
                try:
                    vdb_service = VDBManagementService()
                    vdb_service.delete_vdb(vdb_config.vdb_id)
                    
                    # Delete VDB record from database
                    db.session.delete(vdb_config)
                    
                    cleanup_status['vdb_deleted'] = True
                    logger.info("Deleted VDB for organization {}: {}".format(org_id, vdb_config.vdb_id))
                    
                except Exception as e:
                    logger.error("Failed to delete VDB for organization {}: {}".format(org_id, str(e)))
                    cleanup_status['errors'].append("VDB deletion failed: {}".format(str(e)))
            
            # Archive customer folders
            try:
                folder_service = CustomerFolderService()
                folder_service.delete_customer_folders(org_id)
                
                cleanup_status['folders_archived'] = True
                logger.info("Archived customer folders for organization {}".format(org_id))
                
            except Exception as e:
                logger.error("Failed to archive folders for organization {}: {}".format(org_id, str(e)))
                cleanup_status['errors'].append("Folder archiving failed: {}".format(str(e)))
            
            # Delete organization
            db.session.delete(organization)
            db.session.commit()
            
            cleanup_status['organization_deleted'] = True
            logger.info("Deleted organization {}: {}".format(org_id, organization.name))
            
            # Record event
            record_event(
                current_org._get_current_object(),
                current_user._get_current_object(),
                {
                    'action': 'delete',
                    'object_type': 'organization',
                    'object_id': org_id,
                    'additional_properties': {
                        'name': organization.name,
                        'slug': organization.slug
                    }
                }
            )
            
            return json_response({
                'message': 'Organization deleted successfully',
                'cleanup_status': cleanup_status
            })
            
        except Exception as e:
            db.session.rollback()
            logger.error("Failed to delete organization {}: {}".format(org_id, str(e)))
            return json_response({
                'error': 'Failed to delete organization: {}'.format(str(e))
            }, status=500)


class AdminOrganizationRetryProvisionResource(BaseResource):
    """
    Admin endpoint for retrying failed VDB provisioning.
    
    POST /api/admin/organizations/<org_id>/retry-provision
    - Retry VDB provisioning for organizations with failed provisioning
    """
    
    decorators = [require_super_admin, login_required]
    
    def post(self, org_id):
        """
        Retry VDB provisioning for an organization.
        
        This is useful when initial provisioning failed due to temporary issues.
        """
        organization = models.Organization.query.get_or_404(org_id)
        
        # Check if VDB already exists
        existing_vdb = models.OrganizationVDB.get_by_organization(org_id)
        if existing_vdb and existing_vdb.is_active:
            return json_response({
                'error': 'Organization already has an active VDB',
                'vdb_id': existing_vdb.vdb_id
            }, status=400)
        
        try:
            response = {
                'folders_status': {
                    'created': False,
                    'error': None
                },
                'vdb_status': {
                    'provisioned': False,
                    'error': None
                }
            }
            
            # Create customer folders if they don't exist
            try:
                folder_service = CustomerFolderService()
                folders = folder_service.create_customer_folders(org_id)
                
                response['folders_status'] = {
                    'created': True,
                    'vdb_folder': folders['vdb_folder'],
                    'uploads_folder': folders['uploads_folder'],
                    'error': None
                }
                
                logger.info("Created/verified customer folders for organization {}".format(org_id))
                
            except Exception as e:
                logger.error("Failed to create customer folders for organization {}: {}".format(org_id, str(e)))
                response['folders_status']['error'] = str(e)
            
            # Provision VDB
            try:
                vdb_service = VDBManagementService()
                vdb_config = vdb_service.provision_vdb_for_organization(organization)
                
                response['vdb_status'] = {
                    'provisioned': True,
                    'vdb_id': vdb_config.vdb_id,
                    'status': 'active' if vdb_config.is_active else 'inactive',
                    'error': None
                }
                
                logger.info("Provisioned VDB for organization {}: {}".format(org_id, vdb_config.vdb_id))
                
            except Exception as e:
                logger.error("Failed to provision VDB for organization {}: {}".format(org_id, str(e)))
                response['vdb_status']['error'] = str(e)
                return json_response(response, status=500)
            
            db.session.commit()
            
            # Record event
            record_event(
                current_org._get_current_object(),
                current_user._get_current_object(),
                {
                    'action': 'retry_provision',
                    'object_type': 'organization_vdb',
                    'object_id': org_id
                }
            )
            
            return json_response(response)
            
        except Exception as e:
            db.session.rollback()
            logger.error("Failed to retry VDB provisioning for organization {}: {}".format(org_id, str(e)))
            return json_response({
                'error': 'Failed to retry provisioning: {}'.format(str(e))
            }, status=500)


# Register routes
@routes.route('/api/admin/organizations', methods=['GET', 'POST'])
@require_super_admin
@login_required
def manage_organizations():
    """Route wrapper for AdminOrganizationListResource"""
    resource = AdminOrganizationListResource()
    if request.method == 'GET':
        return resource.get()
    elif request.method == 'POST':
        return resource.post()


@routes.route('/api/admin/organizations/<int:org_id>', methods=['GET', 'DELETE'])
@require_super_admin
@login_required
def manage_organization(org_id):
    """Route wrapper for AdminOrganizationResource"""
    resource = AdminOrganizationResource()
    if request.method == 'GET':
        return resource.get(org_id)
    elif request.method == 'DELETE':
        return resource.delete(org_id)


@routes.route('/api/admin/organizations/<int:org_id>/retry-provision', methods=['POST'])
@require_super_admin
@login_required
def retry_provision_organization(org_id):
    """Route wrapper for AdminOrganizationRetryProvisionResource.post()"""
    resource = AdminOrganizationRetryProvisionResource()
    return resource.post(org_id)
