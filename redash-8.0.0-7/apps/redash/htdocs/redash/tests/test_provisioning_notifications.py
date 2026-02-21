"""
Tests for Provisioning Notifications Service
"""

import unittest
from unittest.mock import Mock, patch, MagicMock

from redash.services.provisioning_notifications import ProvisioningNotificationService
from redash.models.organizations import Organization


class TestProvisioningNotificationService(unittest.TestCase):
    """Test cases for ProvisioningNotificationService."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.organization = Mock(spec=Organization)
        self.organization.id = 1
        self.organization.name = 'Test Organization'
        self.organization.slug = 'test-org'
        self.organization.address = '123 Test St'
        self.organization.primary_contact_first_name = 'John'
        self.organization.primary_contact_last_name = 'Doe'
        self.organization.primary_contact_email = 'john.doe@example.com'
        self.organization.provisioning_status = 'failed'
    
    @patch('redash.services.provisioning_notifications.settings')
    @patch('redash.services.provisioning_notifications.mail')
    def test_send_provisioning_failure_notification_success(self, mock_mail, mock_settings):
        """Test successful sending of provisioning failure notification."""
        # Configure mocks
        mock_settings.email_server_is_configured.return_value = True
        mock_settings.PROVISIONING_FAILURE_NOTIFICATION_EMAILS = ['admin@example.com']
        mock_settings.HOST = 'https://redash.example.com'
        
        # Call method
        error_details = 'VDB provisioning failed: Connection timeout'
        steps_completed = ['organization_created', 'folders_created']
        
        result = ProvisioningNotificationService.send_provisioning_failure_notification(
            self.organization,
            error_details,
            steps_completed
        )
        
        # Assertions
        self.assertTrue(result)
        mock_mail.send.assert_called_once()
        
        # Verify message content
        call_args = mock_mail.send.call_args
        message = call_args[0][0]
        
        self.assertIn('Test Organization', message.subject)
        self.assertEqual(['admin@example.com'], message.recipients)
        self.assertIn('VDB provisioning failed', message.body)
        self.assertIn('organization_created', message.body)
        self.assertIn('folders_created', message.body)
        self.assertIn('John Doe', message.body)
        self.assertIn('john.doe@example.com', message.body)
    
    @patch('redash.services.provisioning_notifications.settings')
    def test_send_notification_email_server_not_configured(self, mock_settings):
        """Test notification when email server is not configured."""
        # Configure mocks
        mock_settings.email_server_is_configured.return_value = False
        
        # Call method
        result = ProvisioningNotificationService.send_provisioning_failure_notification(
            self.organization,
            'Test error',
            []
        )
        
        # Assertions
        self.assertFalse(result)
    
    @patch('redash.services.provisioning_notifications.settings')
    def test_send_notification_no_recipients_configured(self, mock_settings):
        """Test notification when no recipients are configured."""
        # Configure mocks
        mock_settings.email_server_is_configured.return_value = True
        mock_settings.PROVISIONING_FAILURE_NOTIFICATION_EMAILS = []
        
        # Call method
        result = ProvisioningNotificationService.send_provisioning_failure_notification(
            self.organization,
            'Test error',
            []
        )
        
        # Assertions
        self.assertFalse(result)
    
    @patch('redash.services.provisioning_notifications.settings')
    @patch('redash.services.provisioning_notifications.mail')
    def test_send_notification_with_none_organization(self, mock_mail, mock_settings):
        """Test notification when organization is None (creation failed)."""
        # Configure mocks
        mock_settings.email_server_is_configured.return_value = True
        mock_settings.PROVISIONING_FAILURE_NOTIFICATION_EMAILS = ['admin@example.com']
        mock_settings.HOST = 'https://redash.example.com'
        
        # Call method with None organization
        result = ProvisioningNotificationService.send_provisioning_failure_notification(
            None,
            'Organization creation failed',
            []
        )
        
        # Assertions
        self.assertTrue(result)
        mock_mail.send.assert_called_once()
        
        # Verify message handles None organization
        call_args = mock_mail.send.call_args
        message = call_args[0][0]
        
        self.assertIn('Unknown Organization', message.subject)
        self.assertIn('Organization creation failed', message.body)
    
    @patch('redash.services.provisioning_notifications.settings')
    @patch('redash.services.provisioning_notifications.mail')
    def test_send_notification_mail_send_exception(self, mock_mail, mock_settings):
        """Test notification when mail.send raises an exception."""
        # Configure mocks
        mock_settings.email_server_is_configured.return_value = True
        mock_settings.PROVISIONING_FAILURE_NOTIFICATION_EMAILS = ['admin@example.com']
        mock_settings.HOST = 'https://redash.example.com'
        mock_mail.send.side_effect = Exception('SMTP connection failed')
        
        # Call method
        result = ProvisioningNotificationService.send_provisioning_failure_notification(
            self.organization,
            'Test error',
            []
        )
        
        # Assertions
        self.assertFalse(result)
    
    @patch('redash.services.provisioning_notifications.settings')
    @patch('redash.services.provisioning_notifications.mail')
    def test_send_notification_multiple_recipients(self, mock_mail, mock_settings):
        """Test notification with multiple recipients."""
        # Configure mocks
        mock_settings.email_server_is_configured.return_value = True
        mock_settings.PROVISIONING_FAILURE_NOTIFICATION_EMAILS = [
            'admin1@example.com',
            'admin2@example.com',
            'admin3@example.com'
        ]
        mock_settings.HOST = 'https://redash.example.com'
        
        # Call method
        result = ProvisioningNotificationService.send_provisioning_failure_notification(
            self.organization,
            'Test error',
            []
        )
        
        # Assertions
        self.assertTrue(result)
        
        # Verify all recipients are included
        call_args = mock_mail.send.call_args
        message = call_args[0][0]
        
        self.assertEqual(3, len(message.recipients))
        self.assertIn('admin1@example.com', message.recipients)
        self.assertIn('admin2@example.com', message.recipients)
        self.assertIn('admin3@example.com', message.recipients)
    
    @patch('redash.services.provisioning_notifications.settings')
    @patch('redash.services.provisioning_notifications.mail')
    def test_build_failure_email_body_content(self, mock_mail, mock_settings):
        """Test that email body contains all required information."""
        # Configure mocks
        mock_settings.email_server_is_configured.return_value = True
        mock_settings.PROVISIONING_FAILURE_NOTIFICATION_EMAILS = ['admin@example.com']
        mock_settings.HOST = 'https://redash.example.com'
        
        # Call method
        error_details = 'VDB provisioning failed: Connection timeout'
        steps_completed = [
            'slug_generated',
            'organization_created',
            'folders_created'
        ]
        
        result = ProvisioningNotificationService.send_provisioning_failure_notification(
            self.organization,
            error_details,
            steps_completed
        )
        
        # Get email body
        call_args = mock_mail.send.call_args
        message = call_args[0][0]
        body = message.body
        
        # Verify all required sections are present
        self.assertIn('ORGANIZATION PROVISIONING FAILURE ALERT', body)
        self.assertIn('Organization Information:', body)
        self.assertIn('Steps Completed Before Failure:', body)
        self.assertIn('Error Details:', body)
        self.assertIn('Recommended Actions:', body)
        
        # Verify organization details
        self.assertIn('Test Organization', body)
        self.assertIn('test-org', body)
        self.assertIn('123 Test St', body)
        self.assertIn('John Doe', body)
        self.assertIn('john.doe@example.com', body)
        
        # Verify error details
        self.assertIn('VDB provisioning failed: Connection timeout', body)
        
        # Verify steps
        self.assertIn('slug_generated', body)
        self.assertIn('organization_created', body)
        self.assertIn('folders_created', body)
        
        # Verify action items
        self.assertIn('Review the error details', body)
        self.assertIn('Check system logs', body)
        self.assertIn('Verify that all required services are running', body)
    
    @patch('redash.services.provisioning_notifications.settings')
    @patch('redash.services.provisioning_notifications.mail')
    def test_send_provisioning_success_notification(self, mock_mail, mock_settings):
        """Test sending success notification."""
        # Configure mocks
        mock_settings.email_server_is_configured.return_value = True
        mock_settings.PROVISIONING_FAILURE_NOTIFICATION_EMAILS = ['admin@example.com']
        mock_settings.HOST = 'https://redash.example.com'
        
        # Create mock VDB config and user
        vdb_config = Mock()
        vdb_config.vdb_id = '1234567'
        vdb_config.vdb_host = 'localhost'
        vdb_config.vdb_port = 35442
        
        user = Mock()
        user.id = 10
        
        # Call method
        result = ProvisioningNotificationService.send_provisioning_success_notification(
            self.organization,
            vdb_config,
            user
        )
        
        # Assertions
        self.assertTrue(result)
        mock_mail.send.assert_called_once()
        
        # Verify message content
        call_args = mock_mail.send.call_args
        message = call_args[0][0]
        
        self.assertIn('Successful', message.subject)
        self.assertIn('Test Organization', message.subject)
        self.assertIn('1234567', message.body)
        self.assertIn('localhost', message.body)
        self.assertIn('35442', message.body)


if __name__ == '__main__':
    unittest.main()
