"""
Unit tests for SMS Service.

Tests the SMS service including:
- Twilio client initialization
- OTP sending with retry logic
- Verification code sending
- Notification sending
- Error handling for Twilio API failures
- Retry logic for transient failures
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from twilio.base.exceptions import TwilioRestException

from redash.services.sms_service import SMSService


class TestTwilioClientInitialization:
    """Test Twilio client initialization."""
    
    @patch('redash.services.sms_service.current_app')
    def test_get_twilio_client_success(self, mock_app):
        """
        Test successful Twilio client initialization.
        
        Requirements: 8.1
        """
        mock_app.config.get.side_effect = lambda key: {
            'TWILIO_ACCOUNT_SID': 'AC123456',
            'TWILIO_AUTH_TOKEN': 'auth_token_123'
        }.get(key)
        
        with patch('redash.services.sms_service.Client') as mock_client:
            client = SMSService._get_twilio_client()
            
            mock_client.assert_called_once_with('AC123456', 'auth_token_123')
    
    @patch('redash.services.sms_service.current_app')
    def test_get_twilio_client_missing_credentials(self, mock_app):
        """
        Test Twilio client initialization fails without credentials.
        
        Requirements: 8.1, 8.4
        """
        mock_app.config.get.return_value = None
        
        with pytest.raises(Exception) as exc_info:
            SMSService._get_twilio_client()
        
        assert 'SMS service not configured' in str(exc_info.value)
    
    @patch('redash.services.sms_service.current_app')
    def test_get_from_number_success(self, mock_app):
        """
        Test getting configured Twilio phone number.
        
        Requirements: 8.1
        """
        mock_app.config.get.return_value = '+18444935528'
        
        from_number = SMSService._get_from_number()
        
        assert from_number == '+18444935528'
    
    @patch('redash.services.sms_service.current_app')
    def test_get_from_number_not_configured(self, mock_app):
        """
        Test getting phone number fails when not configured.
        
        Requirements: 8.1, 8.4
        """
        mock_app.config.get.return_value = None
        
        with pytest.raises(Exception) as exc_info:
            SMSService._get_from_number()
        
        assert 'SMS service not configured' in str(exc_info.value)


class TestSendOTP:
    """Test OTP sending functionality."""
    
    @patch('redash.services.sms_service.current_app')
    @patch('redash.services.sms_service.SMSService._get_twilio_client')
    @patch('redash.services.sms_service.SMSService._get_from_number')
    def test_send_otp_success(self, mock_from_number, mock_client_getter, mock_app):
        """
        Test successful OTP sending.
        
        Requirements: 8.2, 8.5
        """
        mock_app.config.get.return_value = 'TableScope'
        mock_from_number.return_value = '+18444935528'
        
        mock_client = Mock()
        mock_message = Mock()
        mock_message.sid = 'SM123456'
        mock_message.status = 'queued'
        mock_client.messages.create.return_value = mock_message
        mock_client_getter.return_value = mock_client
        
        result = SMSService.send_otp('+12345678901', '123456')
        
        assert result['success'] == True
        assert result['sid'] == 'SM123456'
        assert result['status'] == 'queued'
        
        # Verify message was sent with correct content
        mock_client.messages.create.assert_called_once()
        call_args = mock_client.messages.create.call_args
        assert 'TableScope' in call_args[1]['body']
        assert '123456' in call_args[1]['body']
        assert call_args[1]['to'] == '+12345678901'
        assert call_args[1]['from_'] == '+18444935528'
    
    @patch('redash.services.sms_service.current_app')
    @patch('redash.services.sms_service.SMSService._get_twilio_client')
    @patch('redash.services.sms_service.SMSService._get_from_number')
    def test_send_otp_twilio_error(self, mock_from_number, mock_client_getter, mock_app):
        """
        Test OTP sending with Twilio API error.
        
        Requirements: 8.4, 8.7
        """
        mock_app.config.get.return_value = 'TableScope'
        mock_from_number.return_value = '+18444935528'
        
        mock_client = Mock()
        mock_client.messages.create.side_effect = TwilioRestException(
            status=400,
            uri='/Messages',
            msg='Invalid phone number',
            code=21211
        )
        mock_client_getter.return_value = mock_client
        
        with pytest.raises(Exception) as exc_info:
            SMSService.send_otp('+12345678901', '123456')
        
        assert 'Invalid phone number' in str(exc_info.value)


class TestSendVerification:
    """Test verification code sending functionality."""
    
    @patch('redash.services.sms_service.current_app')
    @patch('redash.services.sms_service.SMSService._get_twilio_client')
    @patch('redash.services.sms_service.SMSService._get_from_number')
    def test_send_verification_success(self, mock_from_number, mock_client_getter, mock_app):
        """
        Test successful verification code sending.
        
        Requirements: 8.3, 8.5
        """
        mock_app.config.get.return_value = 'TableScope'
        mock_from_number.return_value = '+18444935528'
        
        mock_client = Mock()
        mock_message = Mock()
        mock_message.sid = 'SM789012'
        mock_message.status = 'sent'
        mock_client.messages.create.return_value = mock_message
        mock_client_getter.return_value = mock_client
        
        result = SMSService.send_verification('+12345678901', '654321')
        
        assert result['success'] == True
        assert result['sid'] == 'SM789012'
        
        # Verify message contains verification code
        call_args = mock_client.messages.create.call_args
        assert '654321' in call_args[1]['body']
        assert 'verification' in call_args[1]['body'].lower()


class TestSendNotification:
    """Test notification sending functionality."""
    
    @patch('redash.services.sms_service.current_app')
    @patch('redash.services.sms_service.SMSService._get_twilio_client')
    @patch('redash.services.sms_service.SMSService._get_from_number')
    def test_send_notification_success(self, mock_from_number, mock_client_getter, mock_app):
        """
        Test successful notification sending.
        
        Requirements: 8.3, 8.5
        """
        mock_app.config.get.return_value = 'TableScope'
        mock_from_number.return_value = '+18444935528'
        
        mock_client = Mock()
        mock_message = Mock()
        mock_message.sid = 'SM345678'
        mock_message.status = 'delivered'
        mock_client.messages.create.return_value = mock_message
        mock_client_getter.return_value = mock_client
        
        result = SMSService.send_notification('+12345678901', 'Your phone number has been changed')
        
        assert result['success'] == True
        assert result['sid'] == 'SM345678'
        
        # Verify message contains notification
        call_args = mock_client.messages.create.call_args
        assert 'phone number has been changed' in call_args[1]['body']
    
    @patch('redash.services.sms_service.current_app')
    @patch('redash.services.sms_service.SMSService._get_twilio_client')
    @patch('redash.services.sms_service.SMSService._get_from_number')
    def test_send_notification_failure_does_not_raise(self, mock_from_number, mock_client_getter, mock_app):
        """
        Test notification failure does not raise exception.
        
        Requirements: 8.3, 8.4
        """
        mock_app.config.get.return_value = 'TableScope'
        mock_from_number.return_value = '+18444935528'
        
        mock_client = Mock()
        mock_client.messages.create.side_effect = TwilioRestException(
            status=500,
            uri='/Messages',
            msg='Service unavailable',
            code=20500
        )
        mock_client_getter.return_value = mock_client
        
        # Should not raise exception
        result = SMSService.send_notification('+12345678901', 'Test notification')
        
        assert result['success'] == False
        assert 'error' in result


class TestRetryLogic:
    """Test retry logic for transient failures."""
    
    @patch('redash.services.sms_service.time.sleep')
    @patch('redash.services.sms_service.current_app')
    @patch('redash.services.sms_service.SMSService._get_twilio_client')
    @patch('redash.services.sms_service.SMSService._get_from_number')
    def test_retry_on_rate_limit(self, mock_from_number, mock_client_getter, mock_app, mock_sleep):
        """
        Test retry logic on rate limit error.
        
        Requirements: 8.6
        """
        mock_app.config.get.return_value = 'TableScope'
        mock_from_number.return_value = '+18444935528'
        
        mock_client = Mock()
        # First call fails with rate limit, second succeeds
        mock_message = Mock()
        mock_message.sid = 'SM999999'
        mock_message.status = 'sent'
        
        mock_client.messages.create.side_effect = [
            TwilioRestException(status=429, uri='/Messages', msg='Too many requests', code=20429),
            mock_message
        ]
        mock_client_getter.return_value = mock_client
        
        result = SMSService.send_otp('+12345678901', '123456')
        
        assert result['success'] == True
        assert mock_client.messages.create.call_count == 2
        mock_sleep.assert_called_once_with(2)  # First retry delay
    
    @patch('redash.services.sms_service.time.sleep')
    @patch('redash.services.sms_service.current_app')
    @patch('redash.services.sms_service.SMSService._get_twilio_client')
    @patch('redash.services.sms_service.SMSService._get_from_number')
    def test_retry_exponential_backoff(self, mock_from_number, mock_client_getter, mock_app, mock_sleep):
        """
        Test exponential backoff in retry logic.
        
        Requirements: 8.6
        """
        mock_app.config.get.return_value = 'TableScope'
        mock_from_number.return_value = '+18444935528'
        
        mock_client = Mock()
        mock_message = Mock()
        mock_message.sid = 'SM888888'
        mock_message.status = 'sent'
        
        # Fail twice, then succeed
        mock_client.messages.create.side_effect = [
            TwilioRestException(status=503, uri='/Messages', msg='Service unavailable', code=20503),
            TwilioRestException(status=503, uri='/Messages', msg='Service unavailable', code=20503),
            mock_message
        ]
        mock_client_getter.return_value = mock_client
        
        result = SMSService.send_otp('+12345678901', '123456')
        
        assert result['success'] == True
        assert mock_client.messages.create.call_count == 3
        
        # Verify exponential backoff: 2s, 4s
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(2)  # First retry
        mock_sleep.assert_any_call(4)  # Second retry
    
    @patch('redash.services.sms_service.time.sleep')
    @patch('redash.services.sms_service.current_app')
    @patch('redash.services.sms_service.SMSService._get_twilio_client')
    @patch('redash.services.sms_service.SMSService._get_from_number')
    def test_max_retries_exceeded(self, mock_from_number, mock_client_getter, mock_app, mock_sleep):
        """
        Test failure after maximum retries.
        
        Requirements: 8.6
        """
        mock_app.config.get.return_value = 'TableScope'
        mock_from_number.return_value = '+18444935528'
        
        mock_client = Mock()
        # Always fail with retryable error
        mock_client.messages.create.side_effect = TwilioRestException(
            status=500,
            uri='/Messages',
            msg='Internal server error',
            code=20500
        )
        mock_client_getter.return_value = mock_client
        
        with pytest.raises(Exception) as exc_info:
            SMSService.send_otp('+12345678901', '123456')
        
        assert 'Failed to send SMS after 3 retries' in str(exc_info.value)
        assert mock_client.messages.create.call_count == 4  # Initial + 3 retries
    
    @patch('redash.services.sms_service.current_app')
    @patch('redash.services.sms_service.SMSService._get_twilio_client')
    @patch('redash.services.sms_service.SMSService._get_from_number')
    def test_no_retry_on_non_retryable_error(self, mock_from_number, mock_client_getter, mock_app):
        """
        Test no retry on non-retryable errors.
        
        Requirements: 8.6
        """
        mock_app.config.get.return_value = 'TableScope'
        mock_from_number.return_value = '+18444935528'
        
        mock_client = Mock()
        # Non-retryable error (invalid phone number)
        mock_client.messages.create.side_effect = TwilioRestException(
            status=400,
            uri='/Messages',
            msg='Invalid phone number',
            code=21211
        )
        mock_client_getter.return_value = mock_client
        
        with pytest.raises(Exception) as exc_info:
            SMSService.send_otp('+12345678901', '123456')
        
        assert 'Invalid phone number' in str(exc_info.value)
        assert mock_client.messages.create.call_count == 1  # No retries


class TestErrorHandling:
    """Test error handling for various Twilio API failures."""
    
    @patch('redash.services.sms_service.current_app')
    @patch('redash.services.sms_service.SMSService._get_twilio_client')
    @patch('redash.services.sms_service.SMSService._get_from_number')
    def test_handle_invalid_phone_number_error(self, mock_from_number, mock_client_getter, mock_app):
        """
        Test handling of invalid phone number error.
        
        Requirements: 8.4
        """
        mock_app.config.get.return_value = 'TableScope'
        mock_from_number.return_value = '+18444935528'
        
        mock_client = Mock()
        mock_client.messages.create.side_effect = TwilioRestException(
            status=400,
            uri='/Messages',
            msg='Invalid phone number',
            code=21211
        )
        mock_client_getter.return_value = mock_client
        
        with pytest.raises(Exception) as exc_info:
            SMSService.send_otp('+12345678901', '123456')
        
        assert 'Invalid phone number' in str(exc_info.value)
    
    @patch('redash.services.sms_service.current_app')
    @patch('redash.services.sms_service.SMSService._get_twilio_client')
    @patch('redash.services.sms_service.SMSService._get_from_number')
    def test_handle_permission_denied_error(self, mock_from_number, mock_client_getter, mock_app):
        """
        Test handling of permission denied error.
        
        Requirements: 8.4
        """
        mock_app.config.get.return_value = 'TableScope'
        mock_from_number.return_value = '+18444935528'
        
        mock_client = Mock()
        mock_client.messages.create.side_effect = TwilioRestException(
            status=403,
            uri='/Messages',
            msg='Permission denied',
            code=21408
        )
        mock_client_getter.return_value = mock_client
        
        with pytest.raises(Exception) as exc_info:
            SMSService.send_otp('+12345678901', '123456')
        
        assert 'Permission denied' in str(exc_info.value)
    
    @patch('redash.services.sms_service.current_app')
    @patch('redash.services.sms_service.SMSService._get_twilio_client')
    @patch('redash.services.sms_service.SMSService._get_from_number')
    def test_handle_sms_not_capable_error(self, mock_from_number, mock_client_getter, mock_app):
        """
        Test handling of phone not capable of SMS error.
        
        Requirements: 8.4
        """
        mock_app.config.get.return_value = 'TableScope'
        mock_from_number.return_value = '+18444935528'
        
        mock_client = Mock()
        mock_client.messages.create.side_effect = TwilioRestException(
            status=400,
            uri='/Messages',
            msg='Phone not capable of SMS',
            code=21614
        )
        mock_client_getter.return_value = mock_client
        
        with pytest.raises(Exception) as exc_info:
            SMSService.send_otp('+12345678901', '123456')
        
        assert 'not capable of receiving SMS' in str(exc_info.value)


class TestLogging:
    """Test logging for SMS delivery status."""
    
    @patch('redash.services.sms_service.logger')
    @patch('redash.services.sms_service.current_app')
    @patch('redash.services.sms_service.SMSService._get_twilio_client')
    @patch('redash.services.sms_service.SMSService._get_from_number')
    def test_log_successful_delivery(self, mock_from_number, mock_client_getter, mock_app, mock_logger):
        """
        Test logging of successful SMS delivery.
        
        Requirements: 8.7
        """
        mock_app.config.get.return_value = 'TableScope'
        mock_from_number.return_value = '+18444935528'
        
        mock_client = Mock()
        mock_message = Mock()
        mock_message.sid = 'SM123456'
        mock_message.status = 'sent'
        mock_client.messages.create.return_value = mock_message
        mock_client_getter.return_value = mock_client
        
        SMSService.send_otp('+12345678901', '123456')
        
        # Verify logging calls
        assert mock_logger.info.call_count >= 2
        # Check that SID and status are logged
        log_calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any('SM123456' in str(call) for call in log_calls)
    
    @patch('redash.services.sms_service.logger')
    @patch('redash.services.sms_service.current_app')
    @patch('redash.services.sms_service.SMSService._get_twilio_client')
    @patch('redash.services.sms_service.SMSService._get_from_number')
    def test_log_delivery_failure(self, mock_from_number, mock_client_getter, mock_app, mock_logger):
        """
        Test logging of SMS delivery failure.
        
        Requirements: 8.7
        """
        mock_app.config.get.return_value = 'TableScope'
        mock_from_number.return_value = '+18444935528'
        
        mock_client = Mock()
        mock_client.messages.create.side_effect = TwilioRestException(
            status=400,
            uri='/Messages',
            msg='Invalid phone number',
            code=21211
        )
        mock_client_getter.return_value = mock_client
        
        try:
            SMSService.send_otp('+12345678901', '123456')
        except Exception:
            pass
        
        # Verify error logging
        assert mock_logger.error.call_count >= 1
