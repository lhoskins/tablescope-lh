"""
API tests for Organization Provisioning endpoints.

Tests the API endpoints for provisioning new customer organizations including:
- POST /api/admin/organizations/provision
- GET /api/admin/organizations/<org_id>/provisioning/status
- POST /api/admin/organizations/<org_id>/provisioning/retry
- POST /api/admin/organizations/<org_id>/provisioning/rollback
- GET /api/admin/organizations/check-slug
- GET /api/admin/organizations/check-email
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock

from redash.models import db, Organization, User
from redash.services.organization_provisioning import OrganizationProvisioningError


class TestOrganizationProvisioningAPI:
    """Test organization provisioning API endpoint."""
    
    def test_provision_organization_success(self, app, admin_user):
        """
        Test successful organization provisioning via API.
        
        Requirements: 19.1, 19.2, 22.1, 22.2
        """
        with app.test_client() as client:
            # Login as admin
            with client.session_transaction() as sess:
                sess['user_id'] = admin_user.id
            
            # Mock the provisioning service
            with patch('redash.handlers.admin.organization_provisioning.OrganizationProvisioningService') as mock_service_class:
                mock_service = mock_service_class.return_value
                
                # Create mock organization
                mock_org = Mock(spec=Organization)
                mock_org.id = 1
                mock_org.name = 'Test Organization'
                mock_org.slug = 'test-organization'
                mock_org.address = '123 Test St'
                mock_org.primary_contact_first_name = 'John'
                mock_org.primary_contact_last_name = 'Doe'
                mock_org.primary_contact_email = 'john@example.com'
                mock_org.created_at = None
                
                # Create mock VDB
                mock_vdb = Mock()
                mock_vdb.vdb_id = '1234567'
                mock_vdb.is_active = True
                
                # Create mock user
                mock_user = Mock(spec=User)
                mock_user.id = 5
                mock_user.email = 'john@example.com'
                mock_user.name = 'John Doe'
                mock_user.is_invitation_pending = True
                
                # Mock provisioning result
                mock_service.provision_organization.return_value = {
                    'organization': mock_org,
                    'vdb': mock_vdb,
                    'user': mock_user,
                    'invitation_sent': True,
                    'steps_completed': [
                        'slug_generated',
                        'organization_created',
                        'folders_created',
                        'vdb_provisioned',
                        'user_created',
                        'user_assigned',
                        'invitation_sent'
                    ],
                    'errors': []
                }
                
                # Make request
                response = client.post(
                    '/api/admin/organizations/provision',
                    data=json.dumps({
                        'organization_name': 'Test Organization',
                        'address': '123 Test St',
                        'contact_first_name': 'John',
                        'contact_last_name': 'Doe',
                        'contact_email': 'john@example.com'
                    }),
                    content_type='application/json'
                )
                
                assert response.status_code == 201
                data = json.loads(response.data)
                assert data['success'] == True
                assert data['organization']['name'] == 'Test Organization'
                assert data['vdb']['vdb_id'] == '1234567'
                assert data['user']['email'] == 'john@example.com'
                assert data['invitation_sent'] == True
    
    def test_provision_organization_missing_fields(self, app, admin_user):
        """
        Test provisioning with missing required fields.
        
        Requirements: 19.2, 22.4, 24.1
        """
        with app.test_client() as client:
            # Login as admin
            with client.session_transaction() as sess:
                sess['user_id'] = admin_user.id
            
            # Make request with missing fields
            response = client.post(
                '/api/admin/organizations/provision',
                data=json.dumps({
                    'organization_name': 'Test Organization'
                    # Missing other required fields
                }),
                content_type='application/json'
            )
            
            assert response.status_code == 400
    
    def test_provision_organization_invalid_email(self, app, admin_user):
        """
        Test provisioning with invalid email format.
        
        Requirements: 19.5, 22.4, 24.4
        """
        with app.test_client() as client:
            # Login as admin
            with client.session_transaction() as sess:
                sess['user_id'] = admin_user.id
            
            # Make request with invalid email
            response = client.post(
                '/api/admin/organizations/provision',
                data=json.dumps({
                    'organization_name': 'Test Organization',
                    'address': '123 Test St',
                    'contact_first_name': 'John',
                    'contact_last_name': 'Doe',
                    'contact_email': 'invalid-email'
                }),
                content_type='application/json'
            )
            
            assert response.status_code == 400
            data = json.loads(response.data)
            assert 'email' in data['error'].lower()
    
    def test_provision_organization_duplicate_email(self, app, admin_user):
        """
        Test provisioning with duplicate email.
        
        Requirements: 19.5, 22.4, 24.5
        """
        with app.test_client() as client:
            # Login as admin
            with client.session_transaction() as sess:
                sess['user_id'] = admin_user.id
            
            # Mock existing user
            with patch.object(User.query, 'filter') as mock_filter:
                mock_filter.return_value.first.return_value = Mock(spec=User)
                
                # Make request
                response = client.post(
                    '/api/admin/organizations/provision',
                    data=json.dumps({
                        'organization_name': 'Test Organization',
                        'address': '123 Test St',
                        'contact_first_name': 'John',
                        'contact_last_name': 'Doe',
                        'contact_email': 'existing@example.com'
                    }),
                    content_type='application/json'
                )
                
                assert response.status_code == 400
                data = json.loads(response.data)
                assert 'already exists' in data['error']
    
    def test_provision_organization_invalid_name(self, app, admin_user):
        """
        Test provisioning with invalid name fields.
        
        Requirements: 22.4, 24.6
        """
        with app.test_client() as client:
            # Login as admin
            with client.session_transaction() as sess:
                sess['user_id'] = admin_user.id
            
            # Make request with invalid first name (contains numbers)
            response = client.post(
                '/api/admin/organizations/provision',
                data=json.dumps({
                    'organization_name': 'Test Organization',
                    'address': '123 Test St',
                    'contact_first_name': 'John123',
                    'contact_last_name': 'Doe',
                    'contact_email': 'john@example.com'
                }),
                content_type='application/json'
            )
            
            assert response.status_code == 400
            data = json.loads(response.data)
            assert 'First name' in data['error']
    
    def test_provision_organization_permission_check(self, app, regular_user):
        """
        Test that non-admin users cannot provision organizations.
        
        Requirements: 19.1, 22.7
        """
        with app.test_client() as client:
            # Login as regular user (not admin)
            with client.session_transaction() as sess:
                sess['user_id'] = regular_user.id
            
            # Make request
            response = client.post(
                '/api/admin/organizations/provision',
                data=json.dumps({
                    'organization_name': 'Test Organization',
                    'address': '123 Test St',
                    'contact_first_name': 'John',
                    'contact_last_name': 'Doe',
                    'contact_email': 'john@example.com'
                }),
                content_type='application/json'
            )
            
            assert response.status_code == 403


class TestProvisioningStatusAPI:
    """Test provisioning status API endpoint."""
    
    def test_get_provisioning_status(self, app, admin_user):
        """
        Test getting provisioning status.
        
        Requirements: 19.12, 22.5
        """
        with app.test_client() as client:
            # Login as admin
            with client.session_transaction() as sess:
                sess['user_id'] = admin_user.id
            
            # Mock organization
            mock_org = Mock(spec=Organization)
            mock_org.id = 1
            mock_org.provisioning_status = 'complete'
            mock_org.provisioning_started_at = None
            mock_org.provisioning_completed_at = None
            mock_org.provisioning_error = None
            mock_org.primary_contact_user_id = 5
            
            with patch.object(Organization.query, 'get_or_404', return_value=mock_org), \
                 patch('redash.handlers.admin.organization_provisioning.OrganizationVDB') as mock_vdb_class:
                
                mock_vdb = Mock()
                mock_vdb.is_active = True
                mock_vdb_class.get_by_organization.return_value = mock_vdb
                
                # Make request
                response = client.get('/api/admin/organizations/1/provisioning/status')
                
                assert response.status_code == 200
                data = json.loads(response.data)
                assert data['organization_id'] == 1
                assert data['provisioning_status'] == 'complete'
                assert data['vdb_provisioned'] == True
                assert data['user_created'] == True


class TestProvisioningRetryAPI:
    """Test provisioning retry API endpoint."""
    
    def test_retry_vdb_provisioning(self, app, admin_user):
        """
        Test retrying VDB provisioning.
        
        Requirements: 19.12, 22.5, 24.3
        """
        with app.test_client() as client:
            # Login as admin
            with client.session_transaction() as sess:
                sess['user_id'] = admin_user.id
            
            # Mock organization
            mock_org = Mock(spec=Organization)
            mock_org.id = 1
            
            with patch.object(Organization.query, 'get_or_404', return_value=mock_org), \
                 patch('redash.handlers.admin.organization_provisioning.OrganizationProvisioningService') as mock_service_class:
                
                mock_service = mock_service_class.return_value
                mock_service.retry_provisioning_step.return_value = {
                    'success': True,
                    'vdb_id': '1234567'
                }
                
                # Make request
                response = client.post(
                    '/api/admin/organizations/1/provisioning/retry',
                    data=json.dumps({'step': 'vdb'}),
                    content_type='application/json'
                )
                
                assert response.status_code == 200
                data = json.loads(response.data)
                assert data['success'] == True
                assert data['step'] == 'vdb'
    
    def test_retry_invalid_step(self, app, admin_user):
        """
        Test retrying with invalid step name.
        
        Requirements: 22.5
        """
        with app.test_client() as client:
            # Login as admin
            with client.session_transaction() as sess:
                sess['user_id'] = admin_user.id
            
            # Mock organization
            mock_org = Mock(spec=Organization)
            mock_org.id = 1
            
            with patch.object(Organization.query, 'get_or_404', return_value=mock_org):
                # Make request with invalid step
                response = client.post(
                    '/api/admin/organizations/1/provisioning/retry',
                    data=json.dumps({'step': 'invalid_step'}),
                    content_type='application/json'
                )
                
                assert response.status_code == 400
                data = json.loads(response.data)
                assert 'Invalid step' in data['error']


class TestProvisioningRollbackAPI:
    """Test provisioning rollback API endpoint."""
    
    def test_rollback_provisioning(self, app, admin_user):
        """
        Test rolling back provisioning.
        
        Requirements: 21.6, 22.6, 24.5
        """
        with app.test_client() as client:
            # Login as admin
            with client.session_transaction() as sess:
                sess['user_id'] = admin_user.id
            
            # Mock organization
            mock_org = Mock(spec=Organization)
            mock_org.id = 1
            
            with patch.object(Organization.query, 'get_or_404', return_value=mock_org), \
                 patch('redash.handlers.admin.organization_provisioning.OrganizationProvisioningService') as mock_service_class:
                
                mock_service = mock_service_class.return_value
                mock_service.rollback_provisioning.return_value = {
                    'success': True,
                    'steps_rolled_back': ['vdb_deleted', 'organization_deleted'],
                    'errors': []
                }
                
                # Make request
                response = client.post(
                    '/api/admin/organizations/1/provisioning/rollback',
                    data=json.dumps({
                        'steps_completed': ['organization_created', 'vdb_provisioned']
                    }),
                    content_type='application/json'
                )
                
                assert response.status_code == 200
                data = json.loads(response.data)
                assert data['success'] == True
                assert 'vdb_deleted' in data['steps_rolled_back']


class TestSlugAvailabilityAPI:
    """Test slug availability check API endpoint."""
    
    def test_check_slug_available(self, app, admin_user):
        """
        Test checking available slug.
        
        Requirements: 19.3, 22.3, 24.3
        """
        with app.test_client() as client:
            # Login as admin
            with client.session_transaction() as sess:
                sess['user_id'] = admin_user.id
            
            with patch.object(Organization.query, 'filter') as mock_filter:
                mock_filter.return_value.first.return_value = None
                
                # Make request
                response = client.get('/api/admin/organizations/check-slug?slug=test-org')
                
                assert response.status_code == 200
                data = json.loads(response.data)
                assert data['slug'] == 'test-org'
                assert data['available'] == True
    
    def test_check_slug_unavailable(self, app, admin_user):
        """
        Test checking unavailable slug.
        
        Requirements: 19.3, 22.3, 24.3
        """
        with app.test_client() as client:
            # Login as admin
            with client.session_transaction() as sess:
                sess['user_id'] = admin_user.id
            
            with patch.object(Organization.query, 'filter') as mock_filter:
                mock_filter.return_value.first.return_value = Mock(spec=Organization)
                
                # Make request
                response = client.get('/api/admin/organizations/check-slug?slug=existing-org')
                
                assert response.status_code == 200
                data = json.loads(response.data)
                assert data['slug'] == 'existing-org'
                assert data['available'] == False
    
    def test_check_slug_missing_parameter(self, app, admin_user):
        """
        Test checking slug without parameter.
        
        Requirements: 22.3
        """
        with app.test_client() as client:
            # Login as admin
            with client.session_transaction() as sess:
                sess['user_id'] = admin_user.id
            
            # Make request without slug parameter
            response = client.get('/api/admin/organizations/check-slug')
            
            assert response.status_code == 400
            data = json.loads(response.data)
            assert 'required' in data['error'].lower()


class TestEmailAvailabilityAPI:
    """Test email availability check API endpoint."""
    
    def test_check_email_available(self, app, admin_user):
        """
        Test checking available email.
        
        Requirements: 19.5, 22.3, 24.5
        """
        with app.test_client() as client:
            # Login as admin
            with client.session_transaction() as sess:
                sess['user_id'] = admin_user.id
            
            with patch.object(User.query, 'filter') as mock_filter:
                mock_filter.return_value.first.return_value = None
                
                # Make request
                response = client.get('/api/admin/organizations/check-email?email=john@example.com')
                
                assert response.status_code == 200
                data = json.loads(response.data)
                assert data['email'] == 'john@example.com'
                assert data['available'] == True
    
    def test_check_email_unavailable(self, app, admin_user):
        """
        Test checking unavailable email.
        
        Requirements: 19.5, 22.3, 24.5
        """
        with app.test_client() as client:
            # Login as admin
            with client.session_transaction() as sess:
                sess['user_id'] = admin_user.id
            
            with patch.object(User.query, 'filter') as mock_filter:
                mock_filter.return_value.first.return_value = Mock(spec=User)
                
                # Make request
                response = client.get('/api/admin/organizations/check-email?email=existing@example.com')
                
                assert response.status_code == 200
                data = json.loads(response.data)
                assert data['email'] == 'existing@example.com'
                assert data['available'] == False
    
    def test_check_email_invalid_format(self, app, admin_user):
        """
        Test checking email with invalid format.
        
        Requirements: 19.5, 22.4, 24.4
        """
        with app.test_client() as client:
            # Login as admin
            with client.session_transaction() as sess:
                sess['user_id'] = admin_user.id
            
            # Make request with invalid email
            response = client.get('/api/admin/organizations/check-email?email=invalid-email')
            
            assert response.status_code == 400
            data = json.loads(response.data)
            assert 'email' in data['error'].lower()
    
    def test_check_email_missing_parameter(self, app, admin_user):
        """
        Test checking email without parameter.
        
        Requirements: 22.3
        """
        with app.test_client() as client:
            # Login as admin
            with client.session_transaction() as sess:
                sess['user_id'] = admin_user.id
            
            # Make request without email parameter
            response = client.get('/api/admin/organizations/check-email')
            
            assert response.status_code == 400
            data = json.loads(response.data)
            assert 'required' in data['error'].lower()


# Fixtures
@pytest.fixture
def app():
    """Create Flask app for testing."""
    from redash import create_app
    app = create_app()
    app.config['TESTING'] = True
    return app


@pytest.fixture
def admin_user():
    """Create mock admin user."""
    user = Mock(spec=User)
    user.id = 1
    user.email = 'admin@example.com'
    user.is_admin = True
    return user


@pytest.fixture
def regular_user():
    """Create mock regular user."""
    user = Mock(spec=User)
    user.id = 2
    user.email = 'user@example.com'
    user.is_admin = False
    return user
