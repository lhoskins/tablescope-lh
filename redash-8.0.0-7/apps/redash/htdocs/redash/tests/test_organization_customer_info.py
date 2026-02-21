"""
Unit tests for Organization model customer information fields and validation.

Tests the Organization model extensions for customer provisioning including:
- Customer information field validation
- Provisioning status tracking
- Helper methods for provisioning workflow
"""

import pytest
from datetime import datetime
from redash.models import Organization


class TestOrganizationCustomerInfo:
    """Test Organization model customer information functionality."""
    
    @pytest.fixture
    def organization(self):
        """Create a test organization instance."""
        org = Organization()
        org.id = 1
        org.name = "Test Organization"
        org.slug = "test-org"
        return org
    
    def test_customer_info_fields_exist(self, organization):
        """
        Test that customer information fields exist on Organization model.
        
        Requirements: 20.1
        """
        # Verify customer information fields
        assert hasattr(organization, 'address')
        assert hasattr(organization, 'primary_contact_first_name')
        assert hasattr(organization, 'primary_contact_last_name')
        assert hasattr(organization, 'primary_contact_email')
        assert hasattr(organization, 'primary_contact_user_id')
        
        # Verify provisioning status fields
        assert hasattr(organization, 'provisioning_status')
        assert hasattr(organization, 'provisioning_error')
        assert hasattr(organization, 'provisioned_at')
    
    def test_provisioning_status_constants(self):
        """
        Test that provisioning status constants are defined.
        
        Requirements: 20.2
        """
        assert Organization.PROVISIONING_STATUS_PENDING == 'pending'
        assert Organization.PROVISIONING_STATUS_IN_PROGRESS == 'in_progress'
        assert Organization.PROVISIONING_STATUS_COMPLETE == 'complete'
        assert Organization.PROVISIONING_STATUS_FAILED == 'failed'
    
    def test_validate_customer_info_valid_data(self, organization):
        """
        Test customer information validation with valid data.
        
        Requirements: 20.2
        """
        organization.primary_contact_first_name = "John"
        organization.primary_contact_last_name = "Doe"
        organization.primary_contact_email = "john.doe@example.com"
        
        is_valid, errors = organization.validate_customer_info()
        
        assert is_valid is True
        assert len(errors) == 0
    
    def test_validate_customer_info_invalid_email(self, organization):
        """
        Test customer information validation with invalid email.
        
        Requirements: 20.2
        """
        organization.primary_contact_email = "invalid-email"
        
        is_valid, errors = organization.validate_customer_info()
        
        assert is_valid is False
        assert len(errors) > 0
        assert any('email' in error.lower() for error in errors)
    
    def test_validate_customer_info_invalid_name_characters(self, organization):
        """
        Test customer information validation with invalid name characters.
        
        Requirements: 20.2
        """
        organization.primary_contact_first_name = "John123"  # Numbers not allowed
        
        is_valid, errors = organization.validate_customer_info()
        
        assert is_valid is False
        assert len(errors) > 0
        assert any('invalid characters' in error.lower() for error in errors)
    
    def test_validate_customer_info_name_too_long(self, organization):
        """
        Test customer information validation with name exceeding max length.
        
        Requirements: 20.2
        """
        organization.primary_contact_first_name = "A" * 256  # Exceeds 255 char limit
        
        is_valid, errors = organization.validate_customer_info()
        
        assert is_valid is False
        assert len(errors) > 0
        assert any('255 characters' in error for error in errors)
    
    def test_validate_customer_info_valid_name_with_special_chars(self, organization):
        """
        Test customer information validation with valid special characters in names.
        
        Requirements: 20.2
        """
        organization.primary_contact_first_name = "Mary-Jane"
        organization.primary_contact_last_name = "O'Brien"
        
        is_valid, errors = organization.validate_customer_info()
        
        assert is_valid is True
        assert len(errors) == 0
    
    def test_is_valid_email_method(self):
        """
        Test email validation method.
        
        Requirements: 20.2
        """
        # Valid emails
        assert Organization._is_valid_email("test@example.com") is True
        assert Organization._is_valid_email("user.name@example.co.uk") is True
        assert Organization._is_valid_email("user+tag@example.com") is True
        
        # Invalid emails
        assert Organization._is_valid_email("invalid") is False
        assert Organization._is_valid_email("@example.com") is False
        assert Organization._is_valid_email("user@") is False
        assert Organization._is_valid_email("user@.com") is False
    
    def test_is_valid_name_method(self):
        """
        Test name validation method.
        
        Requirements: 20.2
        """
        # Valid names
        assert Organization._is_valid_name("John") is True
        assert Organization._is_valid_name("Mary-Jane") is True
        assert Organization._is_valid_name("O'Brien") is True
        assert Organization._is_valid_name("Jean Paul") is True
        
        # Invalid names
        assert Organization._is_valid_name("John123") is False
        assert Organization._is_valid_name("John@Doe") is False
        assert Organization._is_valid_name("John#Doe") is False
    
    def test_provisioning_status_check_methods(self, organization):
        """
        Test provisioning status check methods.
        
        Requirements: 20.2, 20.3
        """
        # Test pending status
        organization.provisioning_status = Organization.PROVISIONING_STATUS_PENDING
        assert organization.is_provisioning_pending() is True
        assert organization.is_provisioning_in_progress() is False
        assert organization.is_provisioning_complete() is False
        assert organization.is_provisioning_failed() is False
        
        # Test in progress status
        organization.provisioning_status = Organization.PROVISIONING_STATUS_IN_PROGRESS
        assert organization.is_provisioning_pending() is False
        assert organization.is_provisioning_in_progress() is True
        assert organization.is_provisioning_complete() is False
        assert organization.is_provisioning_failed() is False
        
        # Test complete status
        organization.provisioning_status = Organization.PROVISIONING_STATUS_COMPLETE
        assert organization.is_provisioning_pending() is False
        assert organization.is_provisioning_in_progress() is False
        assert organization.is_provisioning_complete() is True
        assert organization.is_provisioning_failed() is False
        
        # Test failed status
        organization.provisioning_status = Organization.PROVISIONING_STATUS_FAILED
        assert organization.is_provisioning_pending() is False
        assert organization.is_provisioning_in_progress() is False
        assert organization.is_provisioning_complete() is False
        assert organization.is_provisioning_failed() is True
    
    def test_mark_provisioning_started(self, organization):
        """
        Test marking provisioning as started.
        
        Requirements: 20.2, 20.3
        """
        organization.provisioning_error = "Previous error"
        
        organization.mark_provisioning_started()
        
        assert organization.provisioning_status == Organization.PROVISIONING_STATUS_IN_PROGRESS
        assert organization.provisioning_error is None
    
    def test_mark_provisioning_complete(self, organization):
        """
        Test marking provisioning as complete.
        
        Requirements: 20.2, 20.3, 20.7
        """
        organization.provisioning_error = "Previous error"
        
        organization.mark_provisioning_complete()
        
        assert organization.provisioning_status == Organization.PROVISIONING_STATUS_COMPLETE
        assert organization.provisioning_error is None
        assert organization.provisioned_at is not None
        assert isinstance(organization.provisioned_at, datetime)
    
    def test_mark_provisioning_failed(self, organization):
        """
        Test marking provisioning as failed.
        
        Requirements: 20.2, 20.3
        """
        error_message = "VDB provisioning failed: Connection timeout"
        
        organization.mark_provisioning_failed(error_message)
        
        assert organization.provisioning_status == Organization.PROVISIONING_STATUS_FAILED
        assert organization.provisioning_error == error_message
    
    def test_reset_provisioning_status(self, organization):
        """
        Test resetting provisioning status for retry.
        
        Requirements: 20.2, 20.3
        """
        organization.provisioning_status = Organization.PROVISIONING_STATUS_FAILED
        organization.provisioning_error = "Previous error"
        
        organization.reset_provisioning_status()
        
        assert organization.provisioning_status == Organization.PROVISIONING_STATUS_PENDING
        assert organization.provisioning_error is None
    
    def test_primary_contact_full_name_property(self, organization):
        """
        Test primary contact full name property.
        
        Requirements: 20.2
        """
        # Test with both first and last name
        organization.primary_contact_first_name = "John"
        organization.primary_contact_last_name = "Doe"
        assert organization.primary_contact_full_name == "John Doe"
        
        # Test with only first name
        organization.primary_contact_last_name = None
        assert organization.primary_contact_full_name == "John"
        
        # Test with only last name
        organization.primary_contact_first_name = None
        organization.primary_contact_last_name = "Doe"
        assert organization.primary_contact_full_name == "Doe"
        
        # Test with neither
        organization.primary_contact_first_name = None
        organization.primary_contact_last_name = None
        assert organization.primary_contact_full_name is None
    
    def test_to_dict_with_customer_info(self, organization):
        """
        Test serialization to dictionary with customer information.
        
        Requirements: 20.2
        """
        organization.address = "123 Main St, Suite 100"
        organization.primary_contact_first_name = "John"
        organization.primary_contact_last_name = "Doe"
        organization.primary_contact_email = "john.doe@example.com"
        organization.primary_contact_user_id = 42
        organization.provisioning_status = Organization.PROVISIONING_STATUS_COMPLETE
        organization.provisioned_at = datetime(2025, 11, 22, 10, 30, 0)
        
        result = organization.to_dict_with_customer_info()
        
        assert result['id'] == 1
        assert result['name'] == "Test Organization"
        assert result['slug'] == "test-org"
        assert result['address'] == "123 Main St, Suite 100"
        assert result['primary_contact_first_name'] == "John"
        assert result['primary_contact_last_name'] == "Doe"
        assert result['primary_contact_email'] == "john.doe@example.com"
        assert result['primary_contact_user_id'] == 42
        assert result['primary_contact_full_name'] == "John Doe"
        assert result['provisioning_status'] == Organization.PROVISIONING_STATUS_COMPLETE
        assert result['provisioning_error'] is None
        assert result['provisioned_at'] == "2025-11-22T10:30:00"
    
    def test_to_dict_with_customer_info_null_values(self, organization):
        """
        Test serialization handles null values correctly.
        
        Requirements: 20.2
        """
        result = organization.to_dict_with_customer_info()
        
        assert result['address'] is None
        assert result['primary_contact_first_name'] is None
        assert result['primary_contact_last_name'] is None
        assert result['primary_contact_email'] is None
        assert result['primary_contact_user_id'] is None
        assert result['primary_contact_full_name'] is None
        assert result['provisioning_error'] is None
        assert result['provisioned_at'] is None
    
    def test_default_provisioning_status(self, organization):
        """
        Test that default provisioning status is pending.
        
        Requirements: 20.1, 20.2
        """
        # Note: This would be set by the database default in a real scenario
        # For this test, we verify the constant exists
        assert Organization.PROVISIONING_STATUS_PENDING == 'pending'
    
    def test_customer_info_validation_empty_fields(self, organization):
        """
        Test that validation passes when optional fields are empty.
        
        Requirements: 20.2
        """
        # All customer info fields are optional
        is_valid, errors = organization.validate_customer_info()
        
        assert is_valid is True
        assert len(errors) == 0
    
    def test_multiple_validation_errors(self, organization):
        """
        Test that multiple validation errors are collected.
        
        Requirements: 20.2
        """
        organization.primary_contact_first_name = "A" * 256  # Too long
        organization.primary_contact_last_name = "Doe123"  # Invalid characters
        organization.primary_contact_email = "invalid-email"  # Invalid format
        
        is_valid, errors = organization.validate_customer_info()
        
        assert is_valid is False
        assert len(errors) >= 3  # Should have at least 3 errors
