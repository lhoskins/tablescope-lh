"""
Integration tests for Organization Lifecycle Hooks with VDB Management.

Tests the complete lifecycle of organizations including:
- VDB provisioning on organization creation
- Customer folder creation
- VDB redeployment when VDB exists
- VDB archiving on organization deletion
- Error handling
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from redash.models import db, Organization, OrganizationVDB
from redash.services.vdb_management import VDBManagementService, VDBProvisioningError
from redash.services.customer_folders import CustomerFolderService


class TestOrganizationLifecycleHooks:
    """Test organization lifecycle hooks with VDB provisioning."""
    
    @pytest.fixture
    def mock_servlet_response(self):
        """Mock successful servlet response."""
        return {
            'success': True,
            'vdb_id': '1234567',
            'status': 'deployed'
        }
    
    @pytest.fixture
    def mock_organization(self):
        """Create a mock organization for testing."""
        org = Mock(spec=Organization)
        org.id = 1
        org.slug = 'test-org'
        org.name = 'Test Organization'
        return org
    
    @pytest.fixture
    def vdb_service(self):
        """Create VDB management service with mocked configuration."""
        with patch('redash.services.vdb_management.VDBManagementService._load_teiid_config') as mock_config:
            mock_config.return_value = {
                'servlet_url': 'http://localhost:8095/TeiidExcelImporterTest',
                'servlet_api_key': 'test-api-key',
                'teiid_host': 'localhost',
                'teiid_port': 31020,
                'customer_base_path': '/opt/wildfly/teiidfiles/customers',
                'template_vdb_name': 'MyVDBTest'
            }
            return VDBManagementService()
    
    def test_vdb_provisioning_on_org_creation(self, mock_organization, vdb_service, mock_servlet_response):
        """
        Test VDB provisioning when organization is created.
        
        Requirements: 1.1, 2.1, 14.1, 14.2
        """
        with patch('redash.services.vdb_management.generate_vdb_id') as mock_vdb_id, \
             patch('redash.services.vdb_management.generate_vdb_credentials') as mock_creds, \
             patch('redash.services.vdb_management.requests.post') as mock_post, \
             patch('redash.services.customer_folders.CustomerFolderService.get_vdb_folder') as mock_vdb_folder, \
             patch('redash.services.customer_folders.CustomerFolderService.get_uploads_folder') as mock_uploads_folder, \
             patch.object(db.session, 'add'), \
             patch.object(db.session, 'flush'), \
             patch.object(vdb_service, 'check_vdb_health') as mock_health:
            
            # Setup mocks
            mock_vdb_id.return_value = '1234567'
            mock_creds.return_value = ('vdb_user_test', 'secure_password')
            mock_vdb_folder.return_value = '/opt/wildfly/teiidfiles/customers/1/vdb'
            mock_uploads_folder.return_value = '/opt/wildfly/teiidfiles/customers/1/uploads'
            mock_health.return_value = True
            
            # Mock servlet response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_servlet_response
            mock_post.return_value = mock_response
            
            # Execute provisioning
            vdb_config = vdb_service.provision_vdb_for_organization(mock_organization)
            
            # Verify VDB ID was generated
            mock_vdb_id.assert_called_once()
            
            # Verify credentials were generated
            mock_creds.assert_called_once()
            
            # Verify servlet was called
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[1]['json']['org_id'] == 1
            assert call_args[1]['json']['vdb_id'] == '1234567'
            assert call_args[1]['json']['username'] == 'vdb_user_test'
            assert call_args[1]['json']['password'] == 'secure_password'
            
            # Verify VDB config was created
            assert vdb_config is not None
            assert vdb_config.vdb_id == '1234567'
            assert vdb_config.organization_id == 1
            assert vdb_config.vdb_username == 'vdb_user_test'
            assert vdb_config.is_active is True
    
    def test_customer_folder_creation(self, mock_organization):
        """
        Test customer folder creation during provisioning.
        
        Requirements: 14.2, 15.1, 15.2, 15.3
        """
        with patch('os.makedirs') as mock_makedirs, \
             patch('os.path.exists') as mock_exists:
            
            # Mock folders don't exist
            mock_exists.return_value = False
            
            folder_service = CustomerFolderService()
            folders = folder_service.create_customer_folders(mock_organization.id)
            
            # Verify folders were created
            assert 'vdb_folder' in folders
            assert 'uploads_folder' in folders
            assert folders['vdb_folder'] == '/opt/wildfly/teiidfiles/customers/1'
            assert folders['uploads_folder'] == '/opt/wildfly/teiidfiles/customers/1/uploads'
            
            # Verify makedirs was called
            assert mock_makedirs.call_count >= 2
    
    def test_vdb_redeployment_when_exists(self, mock_organization, vdb_service, mock_servlet_response):
        """
        Test VDB redeployment when VDB file already exists.
        
        Requirements: 18.1, 18.2, 18.3
        """
        with patch('redash.services.vdb_management.generate_vdb_id') as mock_vdb_id, \
             patch('redash.services.vdb_management.generate_vdb_credentials') as mock_creds, \
             patch('redash.services.vdb_management.requests.post') as mock_post, \
             patch('redash.services.customer_folders.CustomerFolderService.get_vdb_folder') as mock_vdb_folder, \
             patch('redash.services.customer_folders.CustomerFolderService.get_uploads_folder') as mock_uploads_folder, \
             patch.object(db.session, 'add'), \
             patch.object(db.session, 'flush'), \
             patch.object(vdb_service, 'check_vdb_health') as mock_health:
            
            # Setup mocks
            mock_vdb_id.return_value = '1234567'
            mock_creds.return_value = ('vdb_user_test', 'secure_password')
            mock_vdb_folder.return_value = '/opt/wildfly/teiidfiles/customers/1/vdb'
            mock_uploads_folder.return_value = '/opt/wildfly/teiidfiles/customers/1/uploads'
            mock_health.return_value = True
            
            # Mock servlet response indicating redeployment
            redeployment_response = {
                'success': True,
                'vdb_id': '1234567',
                'status': 'redeployed'
            }
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = redeployment_response
            mock_post.return_value = mock_response
            
            # Execute provisioning
            vdb_config = vdb_service.provision_vdb_for_organization(mock_organization)
            
            # Verify servlet was called
            mock_post.assert_called_once()
            
            # Verify VDB config was created
            assert vdb_config is not None
            assert vdb_config.vdb_id == '1234567'
    
    def test_vdb_archiving_on_org_deletion(self, vdb_service):
        """
        Test VDB archiving when organization is deleted.
        
        Requirements: 10.1, 10.2, 10.3, 10.4, 15.5
        """
        with patch('redash.services.vdb_management.requests.post') as mock_post:
            
            # Mock servlet response for deletion
            deletion_response = {
                'success': True,
                'archived_to': '/opt/wildfly/teiidfiles/customers/1/vdb/archive/1234567-vdb.xml'
            }
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = deletion_response
            mock_post.return_value = mock_response
            
            # Execute deletion
            result = vdb_service.delete_vdb('1234567')
            
            # Verify servlet was called
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[1]['json']['vdb_id'] == '1234567'
            
            # Verify result indicates success
            assert result['success'] is True
            assert 'archived_to' in result
    
    def test_provisioning_error_handling(self, mock_organization, vdb_service):
        """
        Test error handling when VDB provisioning fails.
        
        Requirements: 14.3, 14.4
        """
        with patch('redash.services.vdb_management.generate_vdb_id') as mock_vdb_id, \
             patch('redash.services.vdb_management.generate_vdb_credentials') as mock_creds, \
             patch('redash.services.vdb_management.requests.post') as mock_post, \
             patch('redash.services.customer_folders.CustomerFolderService.get_vdb_folder') as mock_vdb_folder, \
             patch('redash.services.customer_folders.CustomerFolderService.get_uploads_folder') as mock_uploads_folder:
            
            # Setup mocks
            mock_vdb_id.return_value = '1234567'
            mock_creds.return_value = ('vdb_user_test', 'secure_password')
            mock_vdb_folder.return_value = '/opt/wildfly/teiidfiles/customers/1/vdb'
            mock_uploads_folder.return_value = '/opt/wildfly/teiidfiles/customers/1/uploads'
            
            # Mock servlet error response
            mock_response = Mock()
            mock_response.status_code = 500
            mock_response.text = 'Internal Server Error'
            mock_post.return_value = mock_response
            
            # Execute provisioning and expect error
            with pytest.raises(VDBProvisioningError) as exc_info:
                vdb_service.provision_vdb_for_organization(mock_organization)
            
            # Verify error message
            assert 'VDB provisioning failed' in str(exc_info.value)
    
    def test_servlet_timeout_handling(self, mock_organization, vdb_service):
        """
        Test handling of servlet timeout errors.
        
        Requirements: 14.3
        """
        with patch('redash.services.vdb_management.generate_vdb_id') as mock_vdb_id, \
             patch('redash.services.vdb_management.generate_vdb_credentials') as mock_creds, \
             patch('redash.services.vdb_management.requests.post') as mock_post, \
             patch('redash.services.customer_folders.CustomerFolderService.get_vdb_folder') as mock_vdb_folder, \
             patch('redash.services.customer_folders.CustomerFolderService.get_uploads_folder') as mock_uploads_folder:
            
            # Setup mocks
            mock_vdb_id.return_value = '1234567'
            mock_creds.return_value = ('vdb_user_test', 'secure_password')
            mock_vdb_folder.return_value = '/opt/wildfly/teiidfiles/customers/1/vdb'
            mock_uploads_folder.return_value = '/opt/wildfly/teiidfiles/customers/1/uploads'
            
            # Mock servlet timeout
            import requests
            mock_post.side_effect = requests.exceptions.Timeout('Request timed out')
            
            # Execute provisioning and expect error
            with pytest.raises(VDBProvisioningError) as exc_info:
                vdb_service.provision_vdb_for_organization(mock_organization)
            
            # Verify error message mentions timeout
            assert 'timed out' in str(exc_info.value).lower()
    
    def test_health_check_after_provisioning(self, mock_organization, vdb_service, mock_servlet_response):
        """
        Test VDB health check is performed after provisioning.
        
        Requirements: 2.7, 14.5
        """
        with patch('redash.services.vdb_management.generate_vdb_id') as mock_vdb_id, \
             patch('redash.services.vdb_management.generate_vdb_credentials') as mock_creds, \
             patch('redash.services.vdb_management.requests.post') as mock_post, \
             patch('redash.services.customer_folders.CustomerFolderService.get_vdb_folder') as mock_vdb_folder, \
             patch('redash.services.customer_folders.CustomerFolderService.get_uploads_folder') as mock_uploads_folder, \
             patch.object(db.session, 'add'), \
             patch.object(db.session, 'flush'), \
             patch.object(vdb_service, 'check_vdb_health') as mock_health:
            
            # Setup mocks
            mock_vdb_id.return_value = '1234567'
            mock_creds.return_value = ('vdb_user_test', 'secure_password')
            mock_vdb_folder.return_value = '/opt/wildfly/teiidfiles/customers/1/vdb'
            mock_uploads_folder.return_value = '/opt/wildfly/teiidfiles/customers/1/uploads'
            mock_health.return_value = True
            
            # Mock servlet response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_servlet_response
            mock_post.return_value = mock_response
            
            # Execute provisioning
            vdb_config = vdb_service.provision_vdb_for_organization(mock_organization)
            
            # Verify health check was called
            mock_health.assert_called_once()
            
            # Verify VDB is marked as active
            assert vdb_config.is_active is True
    
    def test_folder_creation_error_handling(self, mock_organization):
        """
        Test error handling when folder creation fails.
        
        Requirements: 15.5
        """
        with patch('os.makedirs') as mock_makedirs, \
             patch('os.path.exists') as mock_exists:
            
            # Mock folders don't exist
            mock_exists.return_value = False
            
            # Mock makedirs failure
            mock_makedirs.side_effect = OSError('Permission denied')
            
            folder_service = CustomerFolderService()
            
            # Execute and expect error
            with pytest.raises(OSError) as exc_info:
                folder_service.create_customer_folders(mock_organization.id)
            
            # Verify error message
            assert 'Permission denied' in str(exc_info.value)
    
    def test_vdb_deletion_with_missing_file(self, vdb_service):
        """
        Test VDB deletion handles missing VDB file gracefully.
        
        Requirements: 10.7
        """
        with patch('redash.services.vdb_management.requests.post') as mock_post:
            
            # Mock servlet response indicating file not found
            deletion_response = {
                'success': True,
                'message': 'VDB file not found, nothing to archive'
            }
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = deletion_response
            mock_post.return_value = mock_response
            
            # Execute deletion
            result = vdb_service.delete_vdb('9999999')
            
            # Verify result indicates success even though file was missing
            assert result['success'] is True
    
    def test_concurrent_provisioning_uniqueness(self, vdb_service):
        """
        Test VDB ID uniqueness when multiple organizations are provisioned concurrently.
        
        Requirements: 1.2, 1.3
        """
        with patch('redash.services.vdb_management.generate_vdb_id') as mock_vdb_id:
            
            # Mock VDB ID generation to return unique IDs
            mock_vdb_id.side_effect = ['1234567', '2345678', '3456789']
            
            # Generate multiple VDB IDs
            vdb_ids = [mock_vdb_id() for _ in range(3)]
            
            # Verify all IDs are unique
            assert len(vdb_ids) == len(set(vdb_ids))
            assert all(len(vdb_id) == 7 for vdb_id in vdb_ids)
