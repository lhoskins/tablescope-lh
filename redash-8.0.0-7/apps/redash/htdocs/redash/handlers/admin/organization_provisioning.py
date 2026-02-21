"""
Organization Provisioning API Endpoints

This module provides admin-only API endpoints for provisioning new customer
organizations with complete setup including:
- Organization creation
- VDB provisioning
- User account creation
- User-to-organization assignment
- Invitation email sending
"""

import logging
import re
from flask import request, jsonify
from flask_login import login_required

from redash.handlers.base import BaseResource, json_response, require_fields, record_event
from redash.permissions import require_super_admin
from redash.authentication import current_org
from flask_login import current_user
from redash.models import db, Organization, User
from redash.services.organization_provisioning import (
    OrganizationProvisioningService,
    OrganizationProvisioningError
)

logger = logging.getLogger(__name__)


def validate_email(email):
    """
    Validate email format using RFC 5322 standard.
    
    Args:
        email (str): Email address to validate
        
    Returns:
        tuple: (is_valid, error_message)
    """
    if not email:
        return False, "Email is required"
    
    # Basic RFC 5322 email validation pattern
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(email_pattern, email):
        return False, "Invalid email format"
    
    if len(email) > 255:
        return False, "Email must be less than 255 characters"
    
    return True, None


def validate_name(name, field_name):
    """
    Validate name fields (first name, last name).
    
    Args:
        name (str): Name to validate
        field_name (str): Field name for error messages
        
    Returns:
        tuple: (is_valid, error_message)
    """
    if not name or not name.strip():
        return False, "{} is required".format(field_name)
    
    # Allow letters, spaces, hyphens, and apostrophes
    name_pattern = r"^[a-zA-Z\s\-']+$"
    
    if not re.match(name_pattern, name):
        return False, "{} can only contain letters, spaces, hyphens, and apostrophes".format(field_name)
    
    if len(name) > 100:
        return False, "{} must be less than 100 characters".format(field_name)
    
    return True, None


def validate_organization_name(org_name):
    """
    Validate organization name.
    
    Args:
        org_name (str): Organization name to validate
        
    Returns:
        tuple: (is_valid, error_message)
    """
    if not org_name or not org_name.strip():
        return False, "Organization name is required"
    
    if len(org_name) < 3:
        return False, "Organization name must be at least 3 characters"
    
    if len(org_name) > 255:
        return False, "Organization name must be less than 255 characters"
    
    return True, None


class OrganizationProvisioningResource(BaseResource):
    """
    API endpoint for provisioning new customer organizations.
    
    POST /api/admin/organizations/provision
    - Creates organization with auto-generated slug
    - Provisions VDB
    - Creates user account
    - Assigns user to organization
    - Sends invitation email
    """
    
    def post(self):
        """
        Provision a new customer organization with complete setup.
        
        Request Body:
        {
            "organization_name": "Acme Corporation",
            "address": "123 Main St, City, State 12345",
            "contact_first_name": "John",
            "contact_last_name": "Doe",
            "contact_email": "john.doe@acme.com"
        }
        
        Response (Success):
        {
            "success": true,
            "organization": {
                "id": 1,
                "name": "Acme Corporation",
                "slug": "acme-corporation",
                "address": "123 Main St, City, State 12345",
                "primary_contact_first_name": "John",
                "primary_contact_last_name": "Doe",
                "primary_contact_email": "john.doe@acme.com",
                "created_at": "2025-11-22T10:00:00Z"
            },
            "vdb": {
                "vdb_id": "1234567",
                "status": "active",
                "provisioned": true
            },
            "user": {
                "id": 1,
                "email": "john.doe@acme.com",
                "name": "John Doe",
                "is_invitation_pending": true
            },
            "invitation_sent": true,
            "steps_completed": [
                "slug_generated",
                "organization_created",
                "folders_created",
                "vdb_provisioned",
                "user_created",
                "user_assigned",
                "invitation_sent"
            ]
        }
        
        Response (Error):
        {
            "success": false,
            "error": "Error message",
            "steps_completed": ["slug_generated", "organization_created"],
            "organization_id": 1
        }
        """
        req = request.get_json(force=True)
        
        # Validate required fields
        require_fields(req, [
            'organization_name',
            'address',
            'contact_first_name',
            'contact_last_name',
            'contact_email'
        ])
        
        # Extract and validate required fields
        org_name = req['organization_name'].strip()
        address = req['address'].strip()
        contact_first_name = req['contact_first_name'].strip()
        contact_last_name = req['contact_last_name'].strip()
        contact_email = req['contact_email'].strip().lower()
        
        # Extract optional fields
        company_name = req.get('company_name', '').strip() if req.get('company_name') else None
        address_line1 = req.get('address_line1', '').strip() if req.get('address_line1') else None
        address_line2 = req.get('address_line2', '').strip() if req.get('address_line2') else None
        city = req.get('city', '').strip() if req.get('city') else None
        state_province = req.get('state_province', '').strip() if req.get('state_province') else None
        postal_code = req.get('postal_code', '').strip() if req.get('postal_code') else None
        country = req.get('country', '').strip() if req.get('country') else None
        contact_phone = req.get('contact_phone', '').strip() if req.get('contact_phone') else None
        organization_email = req.get('organization_email', '').strip().lower() if req.get('organization_email') else None
        
        # Validate organization name
        is_valid, error_msg = validate_organization_name(org_name)
        if not is_valid:
            return jsonify({'error': error_msg}), 400
        
        # Validate first name
        is_valid, error_msg = validate_name(contact_first_name, 'First name')
        if not is_valid:
            return jsonify({'error': error_msg}), 400
        
        # Validate last name
        is_valid, error_msg = validate_name(contact_last_name, 'Last name')
        if not is_valid:
            return jsonify({'error': error_msg}), 400
        
        # Validate email
        is_valid, error_msg = validate_email(contact_email)
        if not is_valid:
            return jsonify({'error': error_msg}), 400
        
        # Validate optional organization email if provided
        if organization_email:
            is_valid, error_msg = validate_email(organization_email)
            if not is_valid:
                return jsonify({'error': 'Organization email: ' + error_msg}), 400
        
        # Note: Email uniqueness is checked at organization level, not tenant level
        # Since we're creating a NEW organization, the email can exist in other orgs
        # The email will be unique within this new organization by definition
        
        # Provision organization
        try:
            provisioning_service = OrganizationProvisioningService()
            result = provisioning_service.provision_organization(
                org_name=org_name,
                address=address,
                contact_first_name=contact_first_name,
                contact_last_name=contact_last_name,
                contact_email=contact_email,
                company_name=company_name,
                address_line1=address_line1,
                address_line2=address_line2,
                city=city,
                state_province=state_province,
                postal_code=postal_code,
                country=country,
                contact_phone=contact_phone,
                organization_email=organization_email
            )
            
            # Record event (use the newly created organization as context)
            if result['organization']:
                record_event(
                    result['organization'],
                    current_user._get_current_object(),
                    {
                        'action': 'provision',
                        'object_type': 'organization',
                        'object_id': result['organization'].id,
                        'additional_properties': {
                            'organization_name': org_name,
                            'contact_email': contact_email
                        }
                    }
                )
            
            # Build response
            response = {
                'success': True,
                'organization': {
                    'id': result['organization'].id,
                    'name': result['organization'].name,
                    'slug': result['organization'].slug,
                    'address': result['organization'].address,
                    'primary_contact_first_name': result['organization'].primary_contact_first_name,
                    'primary_contact_last_name': result['organization'].primary_contact_last_name,
                    'primary_contact_email': result['organization'].primary_contact_email,
                    'created_at': result['organization'].created_at.isoformat() if result['organization'].created_at else None
                },
                'vdb': None,
                'user': None,
                'invitation_sent': result['invitation_sent'],
                'steps_completed': result['steps_completed']
            }
            
            if result['vdb']:
                response['vdb'] = {
                    'vdb_id': result['vdb'].vdb_id,
                    'status': 'active' if result['vdb'].is_active else 'inactive',
                    'provisioned': True
                }
            
            if result['user']:
                response['user'] = {
                    'id': result['user'].id,
                    'email': result['user'].email,
                    'name': result['user'].name,
                    'is_invitation_pending': result['user'].is_invitation_pending
                }
            
            logger.info('Organization provisioning completed successfully: {}'.format(org_name))
            
            return jsonify(response), 201
            
        except OrganizationProvisioningError as e:
            logger.error('Organization provisioning failed: {}'.format(str(e)))
            
            # Return error with partial results
            response = {
                'success': False,
                'error': str(e),
                'steps_completed': [],
                'organization_id': None
            }
            
            return jsonify(response), 500
            
        except Exception as e:
            logger.error('Unexpected error during organization provisioning: {}'.format(str(e)), exc_info=True)
            
            return jsonify({
                'success': False,
                'error': 'An unexpected error occurred: {}'.format(str(e))
            }), 500


class OrganizationProvisioningStatusResource(BaseResource):
    """
    API endpoint for checking organization provisioning status.
    
    GET /api/admin/organizations/<org_id>/provisioning/status
    - Returns current provisioning status
    - Shows completed steps and any errors
    """
    
    def get(self, org_id):
        """
        Get provisioning status for an organization.
        
        Response:
        {
            "organization_id": 1,
            "provisioning_status": "complete",  # or "in_progress", "failed", "not_started"
            "provisioning_started_at": "2025-11-22T10:00:00Z",
            "provisioning_completed_at": "2025-11-22T10:05:00Z",
            "provisioning_error": null,
            "vdb_provisioned": true,
            "user_created": true,
            "invitation_sent": true
        }
        """
        organization = Organization.query.get_or_404(org_id)
        
        # Check VDB status
        from redash.models.organization_vdb import OrganizationVDB
        vdb_config = OrganizationVDB.get_by_organization(org_id)
        
        # Check user status
        user_created = organization.primary_contact_user_id is not None
        
        # Determine overall status
        provisioning_status = getattr(organization, 'provisioning_status', 'not_started')
        
        response = {
            'organization_id': org_id,
            'provisioning_status': provisioning_status,
            'provisioning_started_at': getattr(organization, 'provisioning_started_at', None),
            'provisioning_completed_at': getattr(organization, 'provisioning_completed_at', None),
            'provisioning_error': getattr(organization, 'provisioning_error', None),
            'vdb_provisioned': vdb_config is not None and vdb_config.is_active,
            'user_created': user_created,
            'invitation_sent': user_created  # If user exists, invitation was sent
        }
        
        # Convert datetime objects to ISO format
        if response['provisioning_started_at']:
            response['provisioning_started_at'] = response['provisioning_started_at'].isoformat()
        if response['provisioning_completed_at']:
            response['provisioning_completed_at'] = response['provisioning_completed_at'].isoformat()
        
        return response


class OrganizationProvisioningRetryResource(BaseResource):
    """
    API endpoint for retrying failed provisioning steps.
    
    POST /api/admin/organizations/<org_id>/provisioning/retry
    - Retries specific provisioning step
    - Supports: vdb, user, invitation
    """
    
    def post(self, org_id):
        """
        Retry a specific provisioning step.
        
        Request Body:
        {
            "step": "vdb"  # or "user", "invitation"
        }
        
        Response:
        {
            "success": true,
            "step": "vdb",
            "message": "VDB provisioning retry successful"
        }
        """
        organization = Organization.query.get_or_404(org_id)
        
        req = request.get_json(force=True)
        require_fields(req, ['step'])
        
        step = req['step'].strip().lower()
        
        if step not in ['vdb', 'user', 'invitation']:
            return {
                'error': 'Invalid step. Must be one of: vdb, user, invitation'
            }, 400
        
        try:
            provisioning_service = OrganizationProvisioningService()
            result = provisioning_service.retry_provisioning_step(org_id, step)
            
            if result['success']:
                # Record event (use the organization being provisioned as context)
                organization = Organization.query.get(org_id)
                record_event(
                    organization,
                    current_user._get_current_object(),
                    {
                        'action': 'retry_provisioning',
                        'object_type': 'organization',
                        'object_id': org_id,
                        'additional_properties': {
                            'step': step
                        }
                    }
                )
                
                return {
                    'success': True,
                    'step': step,
                    'message': '{} retry successful'.format(step.upper())
                }
            else:
                return {
                    'success': False,
                    'step': step,
                    'error': result.get('error', 'Retry failed')
                }, 500
                
        except OrganizationProvisioningError as e:
            logger.error('Provisioning retry failed: {}'.format(str(e)))
            return {
                'success': False,
                'step': step,
                'error': str(e)
            }, 500
        except Exception as e:
            logger.error('Unexpected error during retry: {}'.format(str(e)), exc_info=True)
            return {
                'success': False,
                'step': step,
                'error': 'An unexpected error occurred: {}'.format(str(e))
            }, 500


class OrganizationProvisioningRollbackResource(BaseResource):
    """
    API endpoint for rolling back failed provisioning.
    
    POST /api/admin/organizations/<org_id>/provisioning/rollback
    - Rolls back all provisioning steps
    - Deletes organization, VDB, user, and folders
    """
    
    def post(self, org_id):
        """
        Rollback all provisioning steps for an organization.
        
        Request Body:
        {
            "steps_completed": ["organization_created", "vdb_provisioned", "user_created"]
        }
        
        Response:
        {
            "success": true,
            "steps_rolled_back": ["user_deleted", "vdb_deleted", "organization_deleted"],
            "errors": []
        }
        """
        organization = Organization.query.get_or_404(org_id)
        
        req = request.get_json(force=True)
        steps_completed = req.get('steps_completed', [])
        
        try:
            provisioning_service = OrganizationProvisioningService()
            result = provisioning_service.rollback_provisioning(org_id, steps_completed)
            
            # Record event
            record_event(
                current_org._get_current_object(),
                current_user._get_current_object(),
                {
                    'action': 'rollback_provisioning',
                    'object_type': 'organization',
                    'object_id': org_id,
                    'additional_properties': {
                        'steps_rolled_back': result['steps_rolled_back']
                    }
                }
            )
            
            return result
            
        except Exception as e:
            logger.error('Rollback failed: {}'.format(str(e)), exc_info=True)
            return {
                'success': False,
                'steps_rolled_back': [],
                'errors': [str(e)]
            }, 500


class SlugAvailabilityResource(BaseResource):
    """
    API endpoint for checking slug availability.
    
    GET /api/admin/organizations/check-slug?slug=acme-corp
    - Checks if slug is available
    - Returns availability status
    """
    
    def get(self):
        """
        Check if an organization slug is available.
        
        Query Parameters:
        - slug: The slug to check
        
        Response:
        {
            "slug": "acme-corp",
            "available": true
        }
        """
        slug = request.args.get('slug', '').strip().lower()
        
        if not slug:
            return {
                'error': 'Slug parameter is required'
            }, 400
        
        # Check if slug exists
        existing_org = Organization.query.filter(Organization.slug == slug).first()
        
        return jsonify({
            'slug': slug,
            'available': existing_org is None
        })


class EmailAvailabilityResource(BaseResource):
    """
    API endpoint for checking email availability.
    
    GET /api/admin/organizations/check-email?email=john@example.com
    - Checks if email is available
    - Returns availability status
    """
    
    def get(self):
        """
        Check if an email address is available.
        
        Query Parameters:
        - email: The email to check
        
        Response:
        {
            "email": "john@example.com",
            "available": true
        }
        
        Note: For new organization provisioning, emails are unique at the 
        organization level, not tenant level. The same email can exist in 
        multiple organizations. This endpoint always returns available=true 
        for new org provisioning since we're creating a new organization.
        """
        email = request.args.get('email', '').strip().lower()
        
        if not email:
            return {
                'error': 'Email parameter is required'
            }, 400
        
        # Validate email format
        is_valid, error_msg = validate_email(email)
        if not is_valid:
            return jsonify({
                'error': error_msg
            }), 400
        
        # For new organization provisioning, email uniqueness is at org level
        # Since we're creating a NEW organization, the email is always available
        # (it will be unique within the new org by definition)
        return jsonify({
            'email': email,
            'available': True
        })


# Route registration
from redash.handlers.base import routes, org_scoped_rule


@routes.route(org_scoped_rule('/api/admin/organizations/provision'), methods=['POST'])
@login_required
@require_super_admin
def provision_organization(org_slug=None):
    """Route for provisioning new organizations"""
    resource = OrganizationProvisioningResource()
    return resource.post()


@routes.route(org_scoped_rule('/api/admin/organizations/<int:org_id>/provisioning/status'), methods=['GET'])
@login_required
@require_super_admin
def get_provisioning_status(org_id, org_slug=None):
    """Route for getting provisioning status"""
    resource = OrganizationProvisioningStatusResource()
    return resource.get(org_id)


@routes.route(org_scoped_rule('/api/admin/organizations/<int:org_id>/provisioning/retry'), methods=['POST'])
@login_required
@require_super_admin
def retry_provisioning(org_id, org_slug=None):
    """Route for retrying provisioning steps"""
    resource = OrganizationProvisioningRetryResource()
    return resource.post(org_id)


@routes.route(org_scoped_rule('/api/admin/organizations/<int:org_id>/provisioning/rollback'), methods=['POST'])
@login_required
@require_super_admin
def rollback_provisioning(org_id, org_slug=None):
    """Route for rolling back provisioning"""
    resource = OrganizationProvisioningRollbackResource()
    return resource.post(org_id)


@routes.route(org_scoped_rule('/api/admin/organizations/check-slug'), methods=['GET'])
@login_required
@require_super_admin
def check_slug_availability(org_slug=None):
    """Route for checking slug availability"""
    resource = SlugAvailabilityResource()
    return resource.get()


@routes.route(org_scoped_rule('/api/admin/organizations/check-email'), methods=['GET'])
@login_required
@require_super_admin
def check_email_availability(org_slug=None):
    """Route for checking email availability"""
    resource = EmailAvailabilityResource()
    return resource.get()
