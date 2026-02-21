"""
Unit tests for OrganizationProvisioningService.

Tests the complete organization provisioning workflow including:
- Slug generation and uniqueness
- Organization creation
- User creation
- Invitation sending
- Error handling for each step
- Retry functionality
- Rollback functionality
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime

from redash.models import db, Organization, User, Group
from redash.services.organization_provisioning import (
    OrganizationProvisioningService,
    OrganizationProvisioningError,
    ProvisioningRollbackHandler
)
from redash.services.vdb_management import VDBProvisioningError


class TestSlugGeneration:
    """Test slug generation and uniqueness."""
    
    @pytest.fixture
    def service(self):
        """Create provisioning service instance."""
        return OrganizationProvisioningService()
    
    def test_generate_slug_basic(self, service):
        """
        Test basic slug generation from organization name.
        
        Requirements: 19.3, 19.4
        """
        with patch.object(Organization, 'get_by_slug', return_value=None):
            slug = service._generate_slug('Test Organization')
            assert slug == 'test-organization'
    
    def test_generate_slug_with_special_characters(self, service):
        """
        Test slug generation with special characters.
        
        Requirements: 19.3, 19.4
        """
        with patch.object(Organization, 'get_by_slug', return_value=None):
            slug = service._generate_slug('Test & Company, Inc.')
            assert slug == 'test-company-inc'
    
    def test_generate_slug_with_spaces(self, service):
        """
        Test slug generation with multiple spaces.
        
        Requirements: 19.3, 19.4
        """
        with patch.object(Organization, 'get_by_slug', return_value=None):
            slug = service._generate_slug('Test   Organization   Name')
            assert slug == 'test-organization-name'
    
    def test_generate_slug_uniqueness(self, service):
        """
        Test slug uniqueness by appending counter.
        
        Requirements: 19.3, 19.4
        """
        # Mock existing slugs
        existing_slugs = ['test-org', 'test-org-1']
        
        def mock_get_by_slug(slug):
            return Mock() if slug in existing_slugs else None
        
        with patch.object(Organization, 'get_by_slug', side_effect=mock_get_by_slug):
            slug = service._generate_slug('Test Org')
            assert slug == 'test-org-2'
    
    def test_generate_slug_empty_name(self, service):
        """
        Test slug generation with empty name.
        
        Requirements: 19.3, 19.4
        """
        with patch.object(Organization, 'get_by_slug', return_value=None):
            slug = service._generate_slug('')
            assert slug == 'organization'


class TestOrganizationCreation:
    """Test organization creation."""
    
    @pytest.fixture
    def service(self):
        """Create provisioning service instance."""
        return OrganizationProvisioningService()
    
    def test_create_organization_success(self, service):
        """
        Test successful organization creation.
        
        Requirements: 19.7, 20.1, 20.2
        """
        with patch.object(db.session, 'add'), \
             patch.object(db.session, 'flush'), \
             patch.object(service, '_create_default_groups'):
            
            org = service._create_organization(
                org_name='Test Org',
                slug='test-org',
                address='123 Test St',
                contact_first_name='John',
                contact_last_name='Doe',
                contact_email='john@example.com'
            )
            
            assert org.name == 'Test Org'
            assert org.slug == 'test-org'
            assert org.address == '123 Test St'
            assert org.primary_contact_first_name == 'John'
            assert org.primary_contact_last_name == 'Doe'
            assert org.primary_contact_email == 'john@example.com'
            assert org.provisioning_status == Organization.PROVISIONING_STATUS_IN_PROGRESS
    
    def test_create_organization_with_invalid_customer_info(self, service):
        """
        Test organization creation with invalid customer info.
        
        Requirements: 19.7, 24.1, 24.6
        """
        with patch.object(db.session, 'add'), \
             patch.object(db.session, 'flush'):
            
            # Mock validation to return errors
            with patch.object(Organization, 'validate_customer_info', return_value=(False, ['Invalid email'])):
                with pytest.raises(OrganizationProvisioningError) as exc_info:
                    service._create_organization(
                        org_name='Test Org',
                        slug='test-org',
                        address='123 Test St',
                        contact_first_name='John',
                        contact_last_name='Doe',
                        contact_email='invalid-email'
                    )
                
                assert 'Invalid customer info' in str(exc_info.value)
    
    def test_create_default_groups(self, service):
        """
        Test creation of default groups for organization.
        
        Requirements: 19.10
        """
        mock_org = Mock(spec=Organization)
        mock_org.id = 1
        
        with patch.object(db.session, 'add') as mock_add, \
             patch.object(db.session, 'flush'):
            
            service._create_default_groups(mock_org)
            
            # Verify admin and default groups were created
            assert mock_add.call_count == 2
            
            # Check admin group
            admin_group_call = mock_add.call_args_list[0][0][0]
            assert admin_group_call.name == 'admin'
            assert 'admin' in admin_group_call.permissions
            
            # Check default group
            default_group_call = mock_add.call_args_list[1][0][0]
            assert default_group_call.name == 'default'
            assert 'create_query' in default_group_call.permissions


class TestUserCreation:
    """Test user creation."""
    
    @pytest.fixture
    def service(self):
        """Create provisioning service instance."""
        return OrganizationProvisioningService()
    
    @pytest.fixture
    def mock_organization(self):
        """Create mock organization."""
        org = Mock(spec=Organization)
        org.id = 1
        org.slug = 'test-org'
        return org
    
    def test_create_user_success(self, service, mock_organization):
        """
        Test successful user creation.
        
        Requirements: 19.9, 23.1
        """
        with patch.object(User.query, 'filter') as mock_filter, \
             patch.object(db.session, 'add'), \
             patch.object(db.session, 'flush'):
            
            # Mock no existing user
            mock_filter.return_value.first.return_value = None
            
            user = service._create_user(
                mock_organization,
                'john@example.com',
                'John',
                'Doe'
            )
            
            assert user.email == 'john@example.com'
            assert user.name == 'John Doe'
            assert user.org == mock_organization
            assert user.is_invitation_pending == True
            assert user.is_email_verified == False
    
    def test_create_user_already_exists(self, service, mock_organization):
        """
        Test user creation when user already exists.
        
        Requirements: 19.9
        """
        existing_user = Mock(spec=User)
        existing_user.email = 'john@example.com'
        
        with patch.object(User.query, 'filter') as mock_filter:
            mock_filter.return_value.first.return_value = existing_user
            
            user = service._create_user(
                mock_organization,
                'john@example.com',
                'John',
                'Doe'
            )
            
            # Should return existing user
            assert user == existing_user
    
    def test_assign_user_to_org(self, service, mock_organization):
        """
        Test assigning user to organization admin group.
        
        Requirements: 19.10
        """
        mock_user = Mock(spec=User)
        mock_user.email = 'john@example.com'
        mock_user.group_ids = []
        
        mock_admin_group = Mock(spec=Group)
        mock_admin_group.id = 5
        mock_organization.admin_group = mock_admin_group
        
        with patch.object(db.session, 'flush'):
            service._assign_user_to_org(mock_user, mock_organization)
            
            assert 5 in mock_user.group_ids
    
    def test_assign_user_to_org_no_admin_group(self, service, mock_organization):
        """
        Test error when admin group doesn't exist.
        
        Requirements: 19.10, 25.3
        """
        mock_user = Mock(spec=User)
        mock_organization.admin_group = None
        
        with pytest.raises(OrganizationProvisioningError) as exc_info:
            service._assign_user_to_org(mock_user, mock_organization)
        
        assert 'Admin group not found' in str(exc_info.value)


class TestInvitationSending:
    """Test invitation email sending."""
    
    @pytest.fixture
    def service(self):
        """Create provisioning service instance."""
        return OrganizationProvisioningService()
    
    @pytest.fixture
    def mock_user(self):
        """Create mock user."""
        user = Mock(spec=User)
        user.email = 'john@example.com'
        user.name = 'John Doe'
        user.details = {}
        return user
    
    @pytest.fixture
    def mock_organization(self):
        """Create mock organization."""
        org = Mock(spec=Organization)
        org.name = 'Test Organization'
        return org
    
    def test_send_invitation_success(self, service, mock_user, mock_organization):
        """
        Test successful invitation sending.
        
        Requirements: 19.11, 23.2, 23.3
        """
        with patch('redash.services.organization_provisioning.generate_token') as mock_token, \
             patch.object(service, '_render_invitation_email', return_value=True), \
             patch.object(db.session, 'flush'):
            
            mock_token.return_value = 'test-token-123'
            
            result = service._send_invitation(mock_user, mock_organization)
            
            assert result == True
            assert mock_user.details['invitation_token'] == 'test-token-123'
            assert 'invitation_sent_at' in mock_user.details
            assert mock_user.is_invitation_pending == True
    
    def test_send_invitation_email_failure(self, service, mock_user, mock_organization):
        """
        Test invitation sending when email fails.
        
        Requirements: 23.2, 25.4
        """
        with patch('redash.services.organization_provisioning.generate_token') as mock_token, \
             patch.object(service, '_render_invitation_email', return_value=False), \
             patch.object(db.session, 'flush'):
            
            mock_token.return_value = 'test-token-123'
            
            result = service._send_invitation(mock_user, mock_organization)
            
            assert result == False
    
    def test_render_invitation_email(self, service, mock_user, mock_organization):
        """
        Test invitation email rendering and sending.
        
        Requirements: 23.2, 23.3
        """
        with patch('redash.services.organization_provisioning.mail') as mock_mail, \
             patch('redash.services.organization_provisioning.Message') as mock_message, \
             patch('redash.services.organization_provisioning.settings') as mock_settings:
            
            mock_settings.HOST_URL = 'https://example.com'
            
            result = service._render_invitation_email(
                mock_user,
                mock_organization,
                'test-token-123'
            )
            
            assert result == True
            mock_mail.send.assert_called_once()


class TestErrorHandling:
    """Test error handling for each provisioning step."""
    
    @pytest.fixture
    def service(self):
        """Create provisioning service instance."""
        return OrganizationProvisioningService()
    
    def test_vdb_provisioning_failure(self, service):
        """
        Test handling of VDB provisioning failure.
        
        Requirements: 21.3, 25.2
        """
        with patch.object(service, '_generate_slug', return_value='test-org'), \
             patch.object(service, '_create_organization') as mock_create_org, \
             patch.object(service.folder_service, 'create_customer_folders'), \
             patch.object(service.vdb_service, 'provision_vdb_for_organization') as mock_vdb, \
             patch.object(db.session, 'commit'), \
             patch.object(db.session, 'rollback'):
            
            mock_org = Mock(spec=Organization)
            mock_org.id = 1
            mock_org.slug = 'test-org'
            mock_create_org.return_value = mock_org
            
            # Simulate VDB provisioning failure
            mock_vdb.side_effect = VDBProvisioningError('VDB creation failed')
            
            with pytest.raises(OrganizationProvisioningError) as exc_info:
                service.provision_organization(
                    'Test Org',
                    '123 Test St',
                    'John',
                    'Doe',
                    'john@example.com'
                )
            
            assert 'VDB provisioning failed' in str(exc_info.value)
            mock_org.mark_provisioning_failed.assert_called_once()
    
    def test_user_creation_failure(self, service):
        """
        Test handling of user creation failure.
        
        Requirements: 21.4, 25.3
        """
        with patch.object(service, '_generate_slug', return_value='test-org'), \
             patch.object(service, '_create_organization') as mock_create_org, \
             patch.object(service.folder_service, 'create_customer_folders'), \
             patch.object(service.vdb_service, 'provision_vdb_for_organization'), \
             patch.object(service, '_create_user') as mock_create_user, \
             patch.object(db.session, 'commit'), \
             patch.object(db.session, 'rollback'):
            
            mock_org = Mock(spec=Organization)
            mock_org.id = 1
            mock_org.slug = 'test-org'
            mock_create_org.return_value = mock_org
            
            # Simulate user creation failure
            mock_create_user.side_effect = OrganizationProvisioningError('User creation failed')
            
            with pytest.raises(OrganizationProvisioningError) as exc_info:
                service.provision_organization(
                    'Test Org',
                    '123 Test St',
                    'John',
                    'Doe',
                    'john@example.com'
                )
            
            assert 'User creation failed' in str(exc_info.value)


class TestRetryFunctionality:
    """Test retry functionality for failed steps."""
    
    @pytest.fixture
    def service(self):
        """Create provisioning service instance."""
        return OrganizationProvisioningService()
    
    @pytest.fixture
    def mock_organization(self):
        """Create mock organization."""
        org = Mock(spec=Organization)
        org.id = 1
        org.slug = 'test-org'
        org.primary_contact_email = 'john@example.com'
        org.primary_contact_first_name = 'John'
        org.primary_contact_last_name = 'Doe'
        org.primary_contact_user_id = None
        return org
    
    def test_retry_vdb_provisioning(self, service, mock_organization):
        """
        Test retrying VDB provisioning.
        
        Requirements: 21.3, 25.10
        """
        with patch.object(Organization.query, 'get', return_value=mock_organization), \
             patch.object(service.vdb_service, 'provision_vdb_for_organization') as mock_vdb, \
             patch.object(db.session, 'commit'):
            
            mock_vdb_config = Mock()
            mock_vdb_config.vdb_id = '1234567'
            mock_vdb.return_value = mock_vdb_config
            
            result = service.retry_provisioning_step(1, 'vdb')
            
            assert result['success'] == True
            assert result['vdb_id'] == '1234567'
            mock_vdb.assert_called_once_with(mock_organization)
    
    def test_retry_user_creation(self, service, mock_organization):
        """
        Test retrying user creation.
        
        Requirements: 21.4, 25.10
        """
        with patch.object(Organization.query, 'get', return_value=mock_organization), \
             patch.object(service, '_create_user') as mock_create_user, \
             patch.object(service, '_assign_user_to_org'), \
             patch.object(db.session, 'commit'):
            
            mock_user = Mock(spec=User)
            mock_user.id = 5
            mock_user.email = 'john@example.com'
            mock_create_user.return_value = mock_user
            
            result = service.retry_provisioning_step(1, 'user')
            
            assert result['success'] == True
            assert result['user_id'] == 5
            assert mock_organization.primary_contact_user_id == 5
    
    def test_retry_invitation_sending(self, service, mock_organization):
        """
        Test retrying invitation sending.
        
        Requirements: 21.5, 23.5, 25.10
        """
        mock_organization.primary_contact_user_id = 5
        mock_user = Mock(spec=User)
        mock_user.id = 5
        mock_user.email = 'john@example.com'
        
        with patch.object(Organization.query, 'get', return_value=mock_organization), \
             patch.object(User.query, 'get', return_value=mock_user), \
             patch.object(service, '_send_invitation', return_value=True), \
             patch.object(db.session, 'commit'):
            
            result = service.retry_provisioning_step(1, 'invitation')
            
            assert result['success'] == True


class TestRollbackFunctionality:
    """Test rollback functionality."""
    
    @pytest.fixture
    def rollback_handler(self):
        """Create rollback handler instance."""
        return ProvisioningRollbackHandler()
    
    @pytest.fixture
    def mock_organization(self):
        """Create mock organization."""
        org = Mock(spec=Organization)
        org.id = 1
        org.slug = 'test-org'
        org.primary_contact_user_id = 5
        return org
    
    def test_rollback_all_steps(self, rollback_handler, mock_organization):
        """
        Test rolling back all provisioning steps.
        
        Requirements: 25.5, 25.6, 25.7
        """
        mock_user = Mock(spec=User)
        mock_user.id = 5
        mock_user.email = 'john@example.com'
        
        mock_vdb_config = Mock()
        mock_vdb_config.vdb_id = '1234567'
        
        steps_completed = [
            'organization_created',
            'folders_created',
            'vdb_provisioned',
            'user_created',
            'user_assigned',
            'invitation_sent'
        ]
        
        with patch.object(Organization.query, 'get', return_value=mock_organization), \
             patch.object(User.query, 'get', return_value=mock_user), \
             patch('redash.services.organization_provisioning.OrganizationVDB') as mock_vdb_class, \
             patch.object(rollback_handler.vdb_service, 'delete_vdb'), \
             patch.object(rollback_handler.folder_service, 'archive_customer_folders'), \
             patch.object(db.session, 'delete'), \
             patch.object(db.session, 'commit'):
            
            mock_vdb_class.get_by_organization.return_value = mock_vdb_config
            
            result = rollback_handler.rollback_provisioning(1, steps_completed)
            
            assert result['success'] == True
            assert 'user_deleted' in result['steps_rolled_back']
            assert 'vdb_deleted' in result['steps_rolled_back']
            assert 'folders_archived' in result['steps_rolled_back']
            assert 'organization_deleted' in result['steps_rolled_back']
    
    def test_rollback_partial_steps(self, rollback_handler, mock_organization):
        """
        Test rolling back only completed steps.
        
        Requirements: 25.5, 25.10
        """
        steps_completed = ['organization_created', 'folders_created']
        
        with patch.object(Organization.query, 'get', return_value=mock_organization), \
             patch.object(rollback_handler.folder_service, 'archive_customer_folders'), \
             patch.object(db.session, 'delete'), \
             patch.object(db.session, 'commit'):
            
            result = rollback_handler.rollback_provisioning(1, steps_completed)
            
            assert result['success'] == True
            assert 'folders_archived' in result['steps_rolled_back']
            assert 'organization_deleted' in result['steps_rolled_back']
            assert 'vdb_deleted' not in result['steps_rolled_back']
    
    def test_rollback_with_errors(self, rollback_handler, mock_organization):
        """
        Test rollback handling when errors occur.
        
        Requirements: 25.7
        """
        steps_completed = ['vdb_provisioned']
        
        mock_vdb_config = Mock()
        mock_vdb_config.vdb_id = '1234567'
        
        with patch.object(Organization.query, 'get', return_value=mock_organization), \
             patch('redash.services.organization_provisioning.OrganizationVDB') as mock_vdb_class, \
             patch.object(rollback_handler.vdb_service, 'delete_vdb') as mock_delete, \
             patch.object(db.session, 'delete'), \
             patch.object(db.session, 'commit'):
            
            mock_vdb_class.get_by_organization.return_value = mock_vdb_config
            mock_delete.side_effect = Exception('VDB deletion failed')
            
            result = rollback_handler.rollback_provisioning(1, steps_completed)
            
            # Should continue despite error
            assert len(result['errors']) > 0
            assert 'VDB deletion failed' in result['errors'][0]
