"""
Organization Provisioning Service

Service for provisioning new customer organizations with complete setup including:
- Organization creation
- VDB provisioning
- User account creation
- User-to-organization assignment
- Invitation email sending
"""

import logging
import re
from datetime import datetime

from redash import settings
from redash.models import db
from redash.models.users import User, Group
from redash.models.organizations import Organization
from redash.services.vdb_management import VDBManagementService, VDBProvisioningError
from redash.services.customer_folders import CustomerFolderService
from redash.services.provisioning_notifications import ProvisioningNotificationService
from redash.utils import generate_token

logger = logging.getLogger(__name__)


class OrganizationProvisioningError(Exception):
    """Exception raised when organization provisioning fails."""
    pass


class ProvisioningRollbackHandler:
    """
    Handler for rolling back failed provisioning operations.
    
    This class manages the cleanup of resources created during
    a failed provisioning attempt. It provides both full rollback
    and partial rollback capabilities.
    """
    
    def __init__(self):
        """Initialize Rollback Handler."""
        self.vdb_service = VDBManagementService()
        self.folder_service = CustomerFolderService()
    
    def rollback_all(self, organization_id, steps_completed):
        """
        Rollback all provisioning steps in reverse order.
        
        This is the main rollback method that orchestrates the complete
        cleanup of all resources created during provisioning.
        
        Args:
            organization_id (int): Organization ID
            steps_completed (list): List of completed steps
            
        Returns:
            dict: Rollback result with success status and details
        """
        logger.info('Starting full rollback for organization: {}'.format(organization_id))
        
        result = {
            'success': True,
            'steps_rolled_back': [],
            'errors': []
        }
        
        try:
            organization = Organization.query.get(organization_id)
            if not organization:
                logger.error('Organization not found: {}'.format(organization_id))
                result['success'] = False
                result['errors'].append('Organization not found')
                return result
            
            # Rollback in reverse order of creation
            # Step 7: Archive invitation (cannot unsend email)
            if 'invitation_sent' in steps_completed:
                try:
                    self._archive_invitation(organization)
                    result['steps_rolled_back'].append('invitation_archived')
                    logger.info('Invitation archived for organization: {}'.format(organization_id))
                except Exception as e:
                    logger.error('Failed to archive invitation: {}'.format(str(e)))
                    result['errors'].append('Invitation archival failed: {}'.format(str(e)))
            
            # Step 6 & 5: Delete user account
            if 'user_assigned' in steps_completed or 'user_created' in steps_completed:
                try:
                    self._delete_user(organization)
                    result['steps_rolled_back'].append('user_deleted')
                    logger.info('User deleted for organization: {}'.format(organization_id))
                except Exception as e:
                    logger.error('Failed to delete user: {}'.format(str(e)))
                    result['errors'].append('User deletion failed: {}'.format(str(e)))
            
            # Step 4: Delete VDB
            if 'vdb_provisioned' in steps_completed:
                try:
                    self._delete_vdb(organization_id)
                    result['steps_rolled_back'].append('vdb_deleted')
                    logger.info('VDB deleted for organization: {}'.format(organization_id))
                except Exception as e:
                    logger.error('Failed to delete VDB: {}'.format(str(e)))
                    result['errors'].append('VDB deletion failed: {}'.format(str(e)))
            
            # Step 4.5: Delete Shared VDB
            if 'shared_vdb_provisioned' in steps_completed:
                try:
                    self._delete_shared_vdb(organization_id)
                    result['steps_rolled_back'].append('shared_vdb_deleted')
                    logger.info('Shared VDB deleted for organization: {}'.format(organization_id))
                except Exception as e:
                    logger.error('Failed to delete shared VDB: {}'.format(str(e)))
                    result['errors'].append('Shared VDB deletion failed: {}'.format(str(e)))
            
            # Step 3: Archive customer folders
            if 'folders_created' in steps_completed:
                try:
                    self._archive_customer_folders(organization_id)
                    result['steps_rolled_back'].append('folders_archived')
                    logger.info('Customer folders archived for organization: {}'.format(organization_id))
                except Exception as e:
                    logger.error('Failed to archive folders: {}'.format(str(e)))
                    result['errors'].append('Folder archival failed: {}'.format(str(e)))
            
            # Step 2: Delete organization
            if 'organization_created' in steps_completed:
                try:
                    self._delete_organization(organization)
                    result['steps_rolled_back'].append('organization_deleted')
                    logger.info('Organization deleted: {}'.format(organization.slug))
                except Exception as e:
                    logger.error('Failed to delete organization: {}'.format(str(e)))
                    result['errors'].append('Organization deletion failed: {}'.format(str(e)))
            
            # Commit all rollback changes
            db.session.commit()
            
            logger.info('Full rollback completed for organization: {}'.format(organization_id))
            return result
            
        except Exception as e:
            logger.error('Rollback failed: {}'.format(str(e)), exc_info=True)
            db.session.rollback()
            result['success'] = False
            result['errors'].append('Rollback failed: {}'.format(str(e)))
            return result
    
    def rollback_step(self, organization_id, step):
        """
        Rollback a specific provisioning step.
        
        This method allows for partial rollback of individual steps
        without affecting other completed steps.
        
        Args:
            organization_id (int): Organization ID
            step (str): Step to rollback ('invitation', 'user', 'vdb', 'folders', 'organization')
            
        Returns:
            dict: Rollback result with success status and details
        """
        logger.info('Starting partial rollback of step "{}" for organization: {}'.format(
            step, organization_id
        ))
        
        result = {
            'success': True,
            'step': step,
            'errors': []
        }
        
        try:
            organization = Organization.query.get(organization_id)
            if not organization:
                logger.error('Organization not found: {}'.format(organization_id))
                result['success'] = False
                result['errors'].append('Organization not found')
                return result
            
            if step == 'invitation':
                self._archive_invitation(organization)
                logger.info('Invitation archived for organization: {}'.format(organization_id))
                
            elif step == 'user':
                self._delete_user(organization)
                logger.info('User deleted for organization: {}'.format(organization_id))
                
            elif step == 'vdb':
                self._delete_vdb(organization_id)
                logger.info('VDB deleted for organization: {}'.format(organization_id))
                
            elif step == 'shared_vdb':
                self._delete_shared_vdb(organization_id)
                logger.info('Shared VDB deleted for organization: {}'.format(organization_id))
                
            elif step == 'folders':
                self._archive_customer_folders(organization_id)
                logger.info('Folders archived for organization: {}'.format(organization_id))
                
            elif step == 'organization':
                self._delete_organization(organization)
                logger.info('Organization deleted: {}'.format(organization.slug))
                
            else:
                raise ValueError('Unknown rollback step: {}'.format(step))
            
            # Update provisioning status after partial rollback
            if step in ['vdb', 'user', 'invitation']:
                self._mark_provisioning_failed(
                    organization,
                    'Partial rollback: {} step removed'.format(step)
                )
            
            db.session.commit()
            
            logger.info('Partial rollback of step "{}" completed for organization: {}'.format(
                step, organization_id
            ))
            return result
            
        except Exception as e:
            logger.error('Partial rollback failed: {}'.format(str(e)), exc_info=True)
            db.session.rollback()
            result['success'] = False
            result['errors'].append('Partial rollback failed: {}'.format(str(e)))
            return result
    
    def _archive_invitation(self, organization):
        """
        Archive invitation for the organization's primary contact.
        
        Note: Cannot unsend email, but we can mark the invitation as cancelled
        and remove the invitation token.
        
        Args:
            organization: Organization instance
        """
        if organization.primary_contact_user_id:
            user = User.query.get(organization.primary_contact_user_id)
            if user:
                logger.info('Archiving invitation for user: {}'.format(user.email))
                
                # Mark invitation as not pending
                user.is_invitation_pending = False
                
                # Archive invitation details
                if user.details:
                    if 'invitation_token' in user.details:
                        # Move to archived section
                        if 'archived_invitations' not in user.details:
                            user.details['archived_invitations'] = []
                        
                        user.details['archived_invitations'].append({
                            'token': user.details.pop('invitation_token'),
                            'sent_at': user.details.pop('invitation_sent_at', None),
                            'archived_at': datetime.utcnow().isoformat(),
                            'reason': 'provisioning_rollback'
                        })
                
                db.session.flush()
                logger.info('Invitation archived successfully for user: {}'.format(user.email))
    
    def _delete_user(self, organization):
        """
        Delete the user account for the organization's primary contact.
        
        Args:
            organization: Organization instance
        """
        if organization.primary_contact_user_id:
            user = User.query.get(organization.primary_contact_user_id)
            if user:
                logger.info('Deleting user: {} (id={})'.format(user.email, user.id))
                
                # Archive user information before deletion
                logger.info('User archived: email={}, name={}, org_id={}'.format(
                    user.email, user.name, user.org_id
                ))
                
                # Delete user
                db.session.delete(user)
                db.session.flush()
                
                # Clear primary contact reference
                organization.primary_contact_user_id = None
                db.session.flush()
                
                logger.info('User deleted successfully: {}'.format(user.email))
    
    def _delete_vdb(self, organization_id):
        """
        Delete the VDB for the organization.
        
        Args:
            organization_id (int): Organization ID
        """
        from redash.models.organization_vdb import OrganizationVDB
        
        vdb_config = OrganizationVDB.get_by_organization(organization_id)
        if vdb_config:
            logger.info('Deleting VDB: {} (id={})'.format(vdb_config.vdb_id, vdb_config.id))
            
            # Archive VDB information before deletion
            logger.info('VDB archived: vdb_id={}, org_id={}, host={}, port={}'.format(
                vdb_config.vdb_id, organization_id, vdb_config.vdb_host, vdb_config.vdb_port
            ))
            
            try:
                # Call servlet to delete VDB from Teiid
                self.vdb_service.delete_vdb(vdb_config.vdb_id, organization_id)
                logger.info('VDB undeployed from Teiid: {}'.format(vdb_config.vdb_id))
            except Exception as e:
                logger.error('Failed to undeploy VDB from Teiid: {}'.format(str(e)))
                # Continue with database deletion even if Teiid deletion fails
            
            # Delete VDB record from database
            db.session.delete(vdb_config)
            db.session.flush()
            
            logger.info('VDB deleted successfully: {}'.format(vdb_config.vdb_id))
        else:
            logger.warning('No VDB found for organization: {}'.format(organization_id))
    
    def _delete_shared_vdb(self, organization_id):
        """
        Delete the shared VDB for the organization.
        
        Args:
            organization_id (int): Organization ID
        """
        from redash.models.shared_vdb import SharedVDB
        
        shared_vdb_config = SharedVDB.get_by_organization(organization_id)
        if shared_vdb_config:
            logger.info('Deleting Shared VDB: {} (id={})'.format(
                shared_vdb_config.vdb_id, shared_vdb_config.id
            ))
            
            # Archive shared VDB information before deletion
            logger.info('Shared VDB archived: vdb_id={}, org_id={}, host={}, port={}'.format(
                shared_vdb_config.vdb_id, organization_id, 
                shared_vdb_config.vdb_host, shared_vdb_config.vdb_port
            ))
            
            try:
                # Call servlet to delete shared VDB from Teiid
                self.vdb_service.delete_vdb(shared_vdb_config.vdb_id, organization_id)
                logger.info('Shared VDB undeployed from Teiid: {}'.format(shared_vdb_config.vdb_id))
            except Exception as e:
                logger.error('Failed to undeploy shared VDB from Teiid: {}'.format(str(e)))
                # Continue with database deletion even if Teiid deletion fails
            
            # Delete shared VDB record from database
            db.session.delete(shared_vdb_config)
            db.session.flush()
            
            logger.info('Shared VDB deleted successfully: {}'.format(shared_vdb_config.vdb_id))
        else:
            logger.warning('No shared VDB found for organization: {}'.format(organization_id))
    
    def _archive_customer_folders(self, organization_id):
        """
        Archive customer folders for the organization.
        
        Args:
            organization_id (int): Organization ID
        """
        logger.info('Archiving customer folders for organization: {}'.format(organization_id))
        
        try:
            self.folder_service.archive_customer_folders(organization_id)
            logger.info('Customer folders archived successfully for organization: {}'.format(
                organization_id
            ))
        except Exception as e:
            logger.error('Failed to archive customer folders: {}'.format(str(e)))
            raise
    
    def _delete_organization(self, organization):
        """
        Delete the organization record.
        
        Args:
            organization: Organization instance
        """
        logger.info('Deleting organization: {} (id={})'.format(organization.slug, organization.id))
        
        # Archive organization information before deletion
        logger.info('Organization archived: slug={}, name={}, address={}, contact={} {}'.format(
            organization.slug,
            organization.name,
            organization.address,
            organization.primary_contact_first_name,
            organization.primary_contact_last_name
        ))
        
        # Delete organization
        db.session.delete(organization)
        db.session.flush()
        
        logger.info('Organization deleted successfully: {}'.format(organization.slug))
    
    # Maintain backward compatibility with old method name
    def rollback_provisioning(self, organization_id, steps_completed):
        """
        Backward compatibility wrapper for rollback_all.
        
        Args:
            organization_id (int): Organization ID
            steps_completed (list): List of completed steps
            
        Returns:
            dict: Rollback result with success status and details
        """
        return self.rollback_all(organization_id, steps_completed)


class OrganizationProvisioningService:
    """
    Service for provisioning new customer organizations.
    
    This service orchestrates the complete organization provisioning workflow:
    1. Create organization record
    2. Create customer folders
    3. Provision VDB
    4. Create user account
    5. Assign user to organization
    6. Send invitation email
    """
    
    def __init__(self):
        """Initialize Organization Provisioning Service."""
        self.vdb_service = VDBManagementService()
        self.folder_service = CustomerFolderService()
        self.rollback_handler = ProvisioningRollbackHandler()
    
    def _mark_provisioning_failed(self, organization, error_message):
        """Safely mark provisioning as failed (handles missing method)."""
        if hasattr(organization, 'mark_provisioning_failed'):
            organization.mark_provisioning_failed(error_message)
        else:
            # Fallback: set status directly
            organization.provisioning_status = 'failed'
            organization.provisioning_error = error_message
    
    def provision_organization(self, org_name, address, contact_first_name, 
                              contact_last_name, contact_email, company_name=None,
                              address_line1=None, address_line2=None, city=None,
                              state_province=None, postal_code=None, country=None,
                              contact_phone=None, organization_email=None):
        """
        Provision a complete organization with VDB, user, and invitation.
        
        This is the main entry point for organization provisioning. It executes
        the complete workflow and handles errors at each step.
        
        Args:
            org_name (str): Organization name
            address (str): Organization address (legacy field, kept for backward compatibility)
            contact_first_name (str): Primary contact first name
            contact_last_name (str): Primary contact last name
            contact_email (str): Primary contact email address
            company_name (str, optional): Company/business name
            address_line1 (str, optional): Street address, P.O. box, etc.
            address_line2 (str, optional): Apartment, suite, unit, etc.
            city (str, optional): City name
            state_province (str, optional): State, province, or region
            postal_code (str, optional): ZIP or postal code
            country (str, optional): Country name
            contact_phone (str, optional): Primary contact phone number
            organization_email (str, optional): Organization/account email address
            
        Returns:
            dict: Provisioning result with organization, user, and status information
            
        Raises:
            OrganizationProvisioningError: If any step fails
        """
        logger.info('Starting organization provisioning for: {}'.format(org_name))
        
        result = {
            'organization': None,
            'vdb': None,
            'user': None,
            'invitation_sent': False,
            'steps_completed': [],
            'errors': []
        }
        
        try:
            # Step 1: Generate slug
            slug = self._generate_slug(org_name)
            result['steps_completed'].append('slug_generated')
            logger.info('Generated slug: {}'.format(slug))
            
            # Step 2: Create organization
            organization = self._create_organization(
                org_name, slug, address, contact_first_name, 
                contact_last_name, contact_email, company_name,
                address_line1, address_line2, city, state_province,
                postal_code, country, contact_phone, organization_email
            )
            result['organization'] = organization
            result['steps_completed'].append('organization_created')
            logger.info('Organization created: {} (id={})'.format(slug, organization.id))
            
            # Step 3: Create customer folders
            folders_created = self.folder_service.create_customer_folders(organization.id)
            if not folders_created:
                error_msg = 'Customer folder creation failed for organization: {}'.format(organization.id)
                logger.error(error_msg)
                self._mark_provisioning_failed(organization, error_msg)
                db.session.commit()
                result['errors'].append(error_msg)
                raise OrganizationProvisioningError(error_msg)
            result['steps_completed'].append('folders_created')
            logger.info('Customer folders created for org: {}'.format(organization.id))
            
            # Step 4: Provision VDB
            try:
                vdb_config = self.vdb_service.provision_vdb_for_organization(organization)
                result['vdb'] = vdb_config
                result['steps_completed'].append('vdb_provisioned')
                logger.info('VDB provisioned: {}'.format(vdb_config.vdb_id))
            except VDBProvisioningError as e:
                error_msg = 'VDB provisioning failed: {}'.format(str(e))
                logger.error(error_msg)
                self._mark_provisioning_failed(organization, error_msg)
                db.session.commit()
                result['errors'].append(error_msg)
                raise OrganizationProvisioningError(error_msg)
            
            # Step 4.5: Provision Shared VDB (Requirements 26.8, 26.9)
            # CRITICAL: Shared VDB is REQUIRED for project sharing functionality
            # Create both the shared VDB file AND the corresponding database record
            try:
                logger.info('Provisioning shared VDB for organization: {}'.format(organization.id))
                shared_vdb_config = self.vdb_service.provision_shared_vdb(organization.id)
                result['shared_vdb'] = shared_vdb_config
                result['steps_completed'].append('shared_vdb_provisioned')
                logger.info('Shared VDB provisioned successfully: {}'.format(shared_vdb_config.vdb_id))
            except VDBProvisioningError as e:
                # CHANGED: Shared VDB is now CRITICAL - fail provisioning if it fails
                # Without shared VDB, project sharing will not work
                error_msg = 'CRITICAL: Shared VDB provisioning failed: {}'.format(str(e))
                logger.error(error_msg)
                logger.error('Organization provisioning will fail because shared VDB is required for project sharing')
                self._mark_provisioning_failed(organization, error_msg)
                db.session.commit()
                result['errors'].append(error_msg)
                
                # Send alert to administrators
                try:
                    ProvisioningNotificationService.send_critical_failure_notification(
                        organization,
                        'Shared VDB provisioning failed',
                        error_msg
                    )
                except Exception as notif_error:
                    logger.error('Failed to send critical failure notification: {}'.format(str(notif_error)))
                
                raise OrganizationProvisioningError(error_msg)
            
            # Step 5: Create user account
            user = self._create_user(organization, contact_email, contact_first_name, contact_last_name)
            result['user'] = user
            result['steps_completed'].append('user_created')
            logger.info('User created: {} (id={})'.format(contact_email, user.id))
            
            # Step 6: Assign user to organization admin group
            self._assign_user_to_org(user, organization)
            result['steps_completed'].append('user_assigned')
            logger.info('User assigned to organization admin group')
            
            # Step 6.5: Create default tsadmin account
            try:
                tsadmin_user = self._create_default_admin_account(organization)
                result['tsadmin_user'] = tsadmin_user
                result['steps_completed'].append('tsadmin_created')
                logger.info('Default tsadmin account created for organization: {}'.format(organization.slug))
            except Exception as e:
                logger.warning('Failed to create default tsadmin account: {}'.format(str(e)))
                result['errors'].append('Default admin account creation failed: {}'.format(str(e)))
            
            # Step 7: Update organization with primary contact user ID
            organization.primary_contact_user_id = user.id
            db.session.flush()
            
            # Step 8: Send invitation email
            invitation_sent = self._send_invitation(user, organization)
            result['invitation_sent'] = invitation_sent
            if invitation_sent:
                result['steps_completed'].append('invitation_sent')
                logger.info('Invitation email sent to: {}'.format(contact_email))
            else:
                logger.warning('Failed to send invitation email to: {}'.format(contact_email))
                result['errors'].append('Invitation email failed')
            
            # Mark provisioning as complete
            if hasattr(organization, 'mark_provisioning_complete'):
                organization.mark_provisioning_complete()
            else:
                from datetime import datetime
                organization.provisioning_status = 'complete'
                organization.provisioning_error = None
                organization.provisioned_at = datetime.utcnow()
            db.session.commit()
            
            logger.info('Organization provisioning completed successfully for: {}'.format(org_name))
            return result
            
        except OrganizationProvisioningError as e:
            # Already logged and handled
            db.session.rollback()
            
            # Send failure notification to administrators
            try:
                ProvisioningNotificationService.send_provisioning_failure_notification(
                    result.get('organization'),
                    str(e),
                    result.get('steps_completed', [])
                )
            except Exception as notification_error:
                logger.error('Failed to send failure notification: {}'.format(str(notification_error)))
            
            raise
            
        except Exception as e:
            error_msg = 'Unexpected error during organization provisioning: {}'.format(str(e))
            logger.error(error_msg, exc_info=True)
            
            if result['organization']:
                self._mark_provisioning_failed(result['organization'], error_msg)
                try:
                    db.session.commit()
                except:
                    db.session.rollback()
            else:
                db.session.rollback()
            
            result['errors'].append(error_msg)
            
            # Send failure notification to administrators
            try:
                ProvisioningNotificationService.send_provisioning_failure_notification(
                    result.get('organization'),
                    error_msg,
                    result.get('steps_completed', [])
                )
            except Exception as notification_error:
                logger.error('Failed to send failure notification: {}'.format(str(notification_error)))
            
            raise OrganizationProvisioningError(error_msg)
    
    def _generate_slug(self, org_name):
        """
        Generate a unique URL-safe slug from organization name.
        
        Uses existing slug generation logic:
        - Convert to lowercase
        - Replace spaces and special characters with hyphens
        - Remove consecutive hyphens
        - Ensure uniqueness by appending number if needed
        
        Args:
            org_name (str): Organization name
            
        Returns:
            str: Unique slug
        """
        # Convert to lowercase and replace spaces with hyphens
        slug = org_name.lower().strip()
        
        # Replace special characters with hyphens
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        
        # Remove leading/trailing hyphens
        slug = slug.strip('-')
        
        # Remove consecutive hyphens
        slug = re.sub(r'-+', '-', slug)
        
        # Ensure slug is not empty
        if not slug:
            slug = 'organization'
        
        # Ensure uniqueness
        original_slug = slug
        counter = 1
        while Organization.get_by_slug(slug):
            slug = '{}-{}'.format(original_slug, counter)
            counter += 1
        
        return slug
    
    def _create_organization(self, org_name, slug, address, contact_first_name, 
                            contact_last_name, contact_email, company_name=None,
                            address_line1=None, address_line2=None, city=None,
                            state_province=None, postal_code=None, country=None,
                            contact_phone=None, organization_email=None):
        """
        Create organization record in database.
        
        Args:
            org_name (str): Organization name
            slug (str): Organization slug
            address (str): Organization address (legacy field)
            contact_first_name (str): Primary contact first name
            contact_last_name (str): Primary contact last name
            contact_email (str): Primary contact email
            company_name (str, optional): Company/business name
            address_line1 (str, optional): Street address
            address_line2 (str, optional): Apartment, suite, etc.
            city (str, optional): City name
            state_province (str, optional): State/province
            postal_code (str, optional): ZIP/postal code
            country (str, optional): Country name
            contact_phone (str, optional): Contact phone
            organization_email (str, optional): Organization email
            
        Returns:
            Organization: Created organization instance
            
        Raises:
            OrganizationProvisioningError: If creation fails
        """
        try:
            # Create organization with basic fields first
            organization = Organization(
                name=org_name,
                slug=slug,
                settings={}
            )
            
            # Set customer info fields using setattr (workaround for SQLAlchemy issue)
            organization.address = address
            organization.primary_contact_first_name = contact_first_name
            organization.primary_contact_last_name = contact_last_name
            organization.primary_contact_email = contact_email
            
            # Set detailed customer info fields (optional)
            if company_name:
                organization.company_name = company_name
            if address_line1:
                organization.address_line1 = address_line1
            if address_line2:
                organization.address_line2 = address_line2
            if city:
                organization.city = city
            if state_province:
                organization.state_province = state_province
            if postal_code:
                organization.postal_code = postal_code
            if country:
                organization.country = country
            if contact_phone:
                organization.contact_phone = contact_phone
            if organization_email:
                organization.organization_email = organization_email
            
            # Validate customer info (if method exists)
            if hasattr(organization, 'validate_customer_info'):
                is_valid, errors = organization.validate_customer_info()
                if not is_valid:
                    raise OrganizationProvisioningError('Invalid customer info: {}'.format(', '.join(errors)))
            
            # Mark provisioning as started (if method exists)
            if hasattr(organization, 'mark_provisioning_started'):
                organization.mark_provisioning_started()
            else:
                # Fallback: set status directly
                organization.provisioning_status = 'in_progress'
            
            db.session.add(organization)
            db.session.flush()  # Get the ID without committing
            
            # Create default groups for the organization
            self._create_default_groups(organization)
            
            return organization
            
        except Exception as e:
            logger.error('Failed to create organization: {}'.format(str(e)))
            raise OrganizationProvisioningError('Organization creation failed: {}'.format(str(e)))
    
    def _create_default_groups(self, organization):
        """
        Create default builtin groups (admin, default, and SuperUser) for the organization.
        
        Args:
            organization: Organization instance
        """
        # Create admin group with org_admin role_type for MFA
        admin_group = Group(
            name='admin',
            permissions=['admin', 'super_admin'],
            org=organization,
            type=Group.BUILTIN_GROUP,
            role_type='org_admin'  # Set role_type for MFA enforcement
        )
        db.session.add(admin_group)
        
        # Create default group
        default_group = Group(
            name='default',
            permissions=['create_dashboard', 'create_query', 'edit_dashboard', 'edit_query',
                        'view_query', 'view_source', 'execute_query', 'list_users',
                        'schedule_query', 'list_dashboards', 'list_alerts', 'list_data_sources'],
            org=organization,
            type=Group.BUILTIN_GROUP,
            role_type=None  # Default users don't require MFA
        )
        db.session.add(default_group)
        
        # Create SuperUser builtin group with super_admin role_type for MFA
        superuser_group = Group(
            name='SuperUser',
            permissions=['admin', 'create_dashboard', 'create_query', 'edit_dashboard', 'edit_query',
                        'view_query', 'view_source', 'execute_query', 'list_users',
                        'schedule_query', 'list_dashboards', 'list_alerts', 'list_data_sources'],
            org=organization,
            type=Group.BUILTIN_GROUP,
            role_type='super_admin'  # Set role_type for MFA enforcement
        )
        db.session.add(superuser_group)
        
        db.session.flush()
        logger.info('Created builtin groups (admin, default, SuperUser) for organization: {}'.format(organization.slug))
    
    def _create_user(self, organization, email, first_name, last_name):
        """
        Create user account for primary contact.
        
        Args:
            organization: Organization instance
            email (str): User email address
            first_name (str): User first name
            last_name (str): User last name
            
        Returns:
            User: Created user instance
            
        Raises:
            OrganizationProvisioningError: If user creation fails
        """
        try:
            # Check if user already exists
            existing_user = User.query.filter(
                User.email == email.lower(),
                User.org_id == organization.id
            ).first()
            
            if existing_user:
                logger.warning('User already exists: {}'.format(email))
                return existing_user
            
            # Create user with invitation pending
            user = User(
                org=organization,
                email=email.lower(),
                name='{} {}'.format(first_name, last_name).strip(),
                group_ids=[],
                is_invitation_pending=True,
                is_email_verified=False
            )
            
            db.session.add(user)
            db.session.flush()
            
            return user
            
        except Exception as e:
            logger.error('Failed to create user: {}'.format(str(e)))
            raise OrganizationProvisioningError('User creation failed: {}'.format(str(e)))
    
    def _create_default_admin_account(self, organization):
        """
        Create default tsadmin account with password Demo2020 for the organization.
        
        Args:
            organization: Organization instance
            
        Returns:
            User: Created tsadmin user instance
            
        Raises:
            OrganizationProvisioningError: If tsadmin account creation fails
        """
        try:
            # Check if tsadmin already exists for this organization
            existing_tsadmin = User.query.filter(
                User.email == 'tsadmin@{}.local'.format(organization.slug),
                User.org_id == organization.id
            ).first()
            
            if existing_tsadmin:
                logger.warning('tsadmin account already exists for organization: {}'.format(organization.slug))
                return existing_tsadmin
            
            # Create tsadmin user with a known password
            
            tsadmin_user = User(
                org=organization,
                email='tsadmin@{}.local'.format(organization.slug),
                name='TS Admin',
                group_ids=[],
                is_invitation_pending=False,
                is_email_verified=True
            )
            
            # Set the password to Demo2020
            tsadmin_user.hash_password('Demo2020')
            
            db.session.add(tsadmin_user)
            db.session.flush()
            
            # Assign tsadmin to all builtin groups: admin, default, and SuperUser
            if tsadmin_user.group_ids is None:
                tsadmin_user.group_ids = []
            
            # Query all builtin groups for this organization
            from redash.models.users import Group
            builtin_groups = Group.query.filter(
                Group.org_id == organization.id,
                Group.type == Group.BUILTIN_GROUP,
                Group.name.in_(['admin', 'default', 'SuperUser'])
            ).all()
            
            # Add all builtin group IDs to tsadmin
            for group in builtin_groups:
                tsadmin_user.group_ids.append(group.id)
                logger.info('tsadmin assigned to {} group (id: {})'.format(group.name, group.id))
            
            db.session.flush()
            logger.info('tsadmin user assigned to {} builtin groups for organization: {}'.format(
                len(builtin_groups), organization.slug))
            
            logger.info('Default tsadmin account created: tsadmin@{}.local'.format(organization.slug))
            return tsadmin_user
            
        except Exception as e:
            logger.error('Failed to create default tsadmin account: {}'.format(str(e)))
            raise OrganizationProvisioningError('Default admin account creation failed: {}'.format(str(e)))
    
    def _assign_user_to_org(self, user, organization):
        """
        Assign user to organization admin and default groups.
        
        Args:
            user: User instance
            organization: Organization instance
            
        Raises:
            OrganizationProvisioningError: If assignment fails
        """
        try:
            # Get admin group
            admin_group = organization.admin_group
            if not admin_group:
                raise OrganizationProvisioningError('Admin group not found for organization')
            
            # Get default group
            from redash.models.users import Group
            default_group = Group.query.filter(
                Group.org_id == organization.id,
                Group.type == Group.BUILTIN_GROUP,
                Group.name == 'default'
            ).first()
            
            if not default_group:
                raise OrganizationProvisioningError('Default group not found for organization')
            
            # Initialize group_ids if None
            if user.group_ids is None:
                user.group_ids = []
            
            # Add user to admin group
            if admin_group.id not in user.group_ids:
                user.group_ids.append(admin_group.id)
                logger.info('User {} assigned to admin group'.format(user.email))
            
            # Add user to default group
            if default_group.id not in user.group_ids:
                user.group_ids.append(default_group.id)
                logger.info('User {} assigned to default group'.format(user.email))
            
            db.session.flush()
            
        except Exception as e:
            logger.error('Failed to assign user to organization: {}'.format(str(e)))
            raise OrganizationProvisioningError('User assignment failed: {}'.format(str(e)))
    
    def _send_invitation(self, user, organization):
        """
        Send invitation email to user using existing Redash invitation mechanism.
        
        Args:
            user: User instance
            organization: Organization instance
            
        Returns:
            bool: True if invitation sent successfully, False otherwise
        """
        try:
            from redash.authentication.account import invite_link_for_user, send_invite_email
            
            # Mark user as having pending invitation
            if user.details is None:
                user.details = {}
            user.details['is_invitation_pending'] = True
            user.is_invitation_pending = True
            
            db.session.flush()
            
            # Generate invitation link using Redash's built-in system
            invite_url = invite_link_for_user(user)
            
            # Send invitation email using Redash's built-in email template
            # Note: inviter is set to user itself for self-service provisioning
            send_invite_email(user, user, invite_url, organization)
            
            logger.info('Invitation sent to {} for organization {}'.format(user.email, organization.name))
            
            return True
            
        except Exception as e:
            logger.error('Failed to send invitation: {}'.format(str(e)))
            return False
    

    def _update_provisioning_status(self, organization, status, error_message=None):
        """
        Update organization provisioning status.
        
        Args:
            organization: Organization instance
            status (str): Provisioning status
            error_message (str, optional): Error message if failed
        """
        try:
            if status == Organization.PROVISIONING_STATUS_COMPLETE:
                if hasattr(organization, 'mark_provisioning_complete'):
                    organization.mark_provisioning_complete()
                else:
                    organization.provisioning_status = 'complete'
            elif status == Organization.PROVISIONING_STATUS_FAILED:
                if hasattr(organization, 'mark_provisioning_failed'):
                    organization.mark_provisioning_failed(error_message)
                else:
                    organization.provisioning_status = 'failed'
                    organization.provisioning_error = error_message
            elif status == Organization.PROVISIONING_STATUS_IN_PROGRESS:
                organization.mark_provisioning_started()
            
            db.session.commit()
            
        except Exception as e:
            logger.error('Failed to update provisioning status: {}'.format(str(e)))
            db.session.rollback()
    
    def retry_provisioning_step(self, organization_id, step):
        """
        Retry a specific provisioning step that failed.
        
        Args:
            organization_id (int): Organization ID
            step (str): Step to retry ('vdb', 'user', 'invitation')
            
        Returns:
            dict: Retry result with success status and details
            
        Raises:
            OrganizationProvisioningError: If retry fails
        """
        logger.info('Retrying provisioning step "{}" for organization: {}'.format(
            step, organization_id
        ))
        
        result = {
            'success': False,
            'step': step,
            'error': None
        }
        
        try:
            organization = Organization.query.get(organization_id)
            if not organization:
                raise OrganizationProvisioningError('Organization not found')
            
            if step == 'vdb':
                # Retry VDB provisioning
                try:
                    vdb_config = self.vdb_service.provision_vdb_for_organization(organization)
                    result['success'] = True
                    result['vdb_id'] = vdb_config.vdb_id
                    logger.info('VDB provisioning retry successful: {}'.format(vdb_config.vdb_id))
                except VDBProvisioningError as e:
                    error_msg = 'VDB provisioning retry failed: {}'.format(str(e))
                    logger.error(error_msg)
                    result['error'] = error_msg
                    self._mark_provisioning_failed(organization, error_msg)
                    db.session.commit()
                    
                    # Send failure notification
                    try:
                        ProvisioningNotificationService.send_provisioning_failure_notification(
                            organization,
                            error_msg,
                            ['vdb_retry_failed']
                        )
                    except Exception as notification_error:
                        logger.error('Failed to send failure notification: {}'.format(str(notification_error)))
                    
                    raise OrganizationProvisioningError(error_msg)
            
            elif step == 'user':
                # Retry user creation
                if not organization.primary_contact_email:
                    raise OrganizationProvisioningError('Primary contact email not set')
                
                user = self._create_user(
                    organization,
                    organization.primary_contact_email,
                    organization.primary_contact_first_name or 'User',
                    organization.primary_contact_last_name or ''
                )
                
                self._assign_user_to_org(user, organization)
                organization.primary_contact_user_id = user.id
                db.session.commit()
                
                result['success'] = True
                result['user_id'] = user.id
                logger.info('User creation retry successful: {}'.format(user.email))
            
            elif step == 'invitation':
                # Retry invitation sending
                if not organization.primary_contact_user_id:
                    raise OrganizationProvisioningError('Primary contact user not created')
                
                user = User.query.get(organization.primary_contact_user_id)
                if not user:
                    raise OrganizationProvisioningError('Primary contact user not found')
                
                invitation_sent = self._send_invitation(user, organization)
                db.session.commit()
                
                result['success'] = invitation_sent
                if invitation_sent:
                    logger.info('Invitation retry successful: {}'.format(user.email))
                else:
                    result['error'] = 'Failed to send invitation email'
                    logger.error('Invitation retry failed')
            
            else:
                raise OrganizationProvisioningError('Unknown step: {}'.format(step))
            
            return result
            
        except OrganizationProvisioningError:
            raise
        except Exception as e:
            error_msg = 'Unexpected error during retry: {}'.format(str(e))
            logger.error(error_msg, exc_info=True)
            result['error'] = error_msg
            
            # Send failure notification
            try:
                organization = Organization.query.get(organization_id)
                if organization:
                    ProvisioningNotificationService.send_provisioning_failure_notification(
                        organization,
                        error_msg,
                        ['{}_retry_failed'.format(step)]
                    )
            except Exception as notification_error:
                logger.error('Failed to send failure notification: {}'.format(str(notification_error)))
            
            raise OrganizationProvisioningError(error_msg)
    
    def rollback_provisioning(self, organization_id, steps_completed):
        """
        Rollback all provisioning steps for an organization.
        
        This method delegates to the ProvisioningRollbackHandler to perform
        the actual rollback operations.
        
        Args:
            organization_id (int): Organization ID
            steps_completed (list): List of completed steps to rollback
            
        Returns:
            dict: Rollback result with success status and details
        """
        logger.info('Initiating full rollback for organization: {}'.format(organization_id))
        
        try:
            result = self.rollback_handler.rollback_all(
                organization_id,
                steps_completed
            )
            
            if result['success']:
                logger.info('Rollback completed successfully for organization: {}'.format(
                    organization_id
                ))
            else:
                logger.error('Rollback completed with errors for organization: {}'.format(
                    organization_id
                ))
            
            return result
            
        except Exception as e:
            error_msg = 'Rollback failed: {}'.format(str(e))
            logger.error(error_msg, exc_info=True)
            return {
                'success': False,
                'steps_rolled_back': [],
                'errors': [error_msg]
            }
    
    def rollback_step(self, organization_id, step):
        """
        Rollback a specific provisioning step.
        
        This method delegates to the ProvisioningRollbackHandler to perform
        partial rollback of a single step.
        
        Args:
            organization_id (int): Organization ID
            step (str): Step to rollback ('invitation', 'user', 'vdb', 'folders', 'organization')
            
        Returns:
            dict: Rollback result with success status and details
        """
        logger.info('Initiating partial rollback of step "{}" for organization: {}'.format(
            step, organization_id
        ))
        
        try:
            result = self.rollback_handler.rollback_step(organization_id, step)
            
            if result['success']:
                logger.info('Partial rollback completed successfully for organization: {}'.format(
                    organization_id
                ))
            else:
                logger.error('Partial rollback completed with errors for organization: {}'.format(
                    organization_id
                ))
            
            return result
            
        except Exception as e:
            error_msg = 'Partial rollback failed: {}'.format(str(e))
            logger.error(error_msg, exc_info=True)
            return {
                'success': False,
                'step': step,
                'errors': [error_msg]
            }
