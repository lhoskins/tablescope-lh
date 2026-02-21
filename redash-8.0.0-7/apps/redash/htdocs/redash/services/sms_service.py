"""
SMS Service
Service for sending SMS messages via Twilio for MFA operations.
"""

import logging
import time
from flask import current_app

logger = logging.getLogger(__name__)


class SMSService:
    """
    Service for sending SMS messages using Twilio.
    Handles OTP delivery, verification codes, and notifications.
    """
    
    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 2
    
    @staticmethod
    def _get_twilio_client():
        """
        Get configured Twilio client.
        
        Returns:
            Client: Twilio client instance
            
        Raises:
            Exception: If Twilio credentials not configured
        """
        try:
            from twilio.rest import Client
        except ImportError:
            logger.error("Twilio library not installed. Install with: pip install twilio")
            raise Exception("SMS service not available. Contact administrator.")
        
        account_sid = current_app.config.get('TWILIO_ACCOUNT_SID')
        auth_token = current_app.config.get('TWILIO_AUTH_TOKEN')
        
        if not account_sid or not auth_token:
            logger.error("Twilio credentials not configured in application settings")
            raise Exception("SMS service not configured. Contact administrator.")
        
        return Client(account_sid, auth_token)
    
    @staticmethod
    def _get_from_number():
        """
        Get configured Twilio phone number.
        
        Returns:
            str: Twilio phone number
            
        Raises:
            Exception: If phone number not configured
        """
        from_number = current_app.config.get('TWILIO_PHONE_NUMBER')
        
        if not from_number:
            logger.error("Twilio phone number not configured")
            raise Exception("SMS service not configured. Contact administrator.")
        
        return from_number
    
    @staticmethod
    def _get_verify_service_sid():
        """
        Get configured Twilio Verify Service SID.
        
        Returns:
            str: Twilio Verify Service SID or None if not configured
        """
        return current_app.config.get('TWILIO_VERIFY_SERVICE_SID')
    
    @staticmethod
    def _send_sms_with_retry(to_number, message, retry_count=0):
        """
        Send SMS with retry logic for transient failures.
        
        Args:
            to_number: Recipient phone number in E.164 format
            message: Message text to send
            retry_count: Current retry attempt (internal use)
            
        Returns:
            dict: Message details including SID and status
            
        Raises:
            Exception: If SMS fails after all retries
        """
        try:
            from twilio.base.exceptions import TwilioRestException
        except ImportError:
            raise Exception("SMS service not available")
        
        try:
            client = SMSService._get_twilio_client()
            from_number = SMSService._get_from_number()
            
            # Send SMS
            message_obj = client.messages.create(
                body=message,
                from_=from_number,
                to=to_number
            )
            
            # Log successful delivery
            logger.info("SMS sent successfully to {}. SID: {}, Status: {}".format(
                to_number[-4:],  # Only log last 4 digits for privacy
                message_obj.sid,
                message_obj.status
            ))
            
            return {
                'sid': message_obj.sid,
                'status': message_obj.status,
                'to': to_number,
                'success': True
            }
            
        except TwilioRestException as e:
            logger.error("Twilio API error: {} (Code: {})".format(e.msg, e.code))
            
            # Check if error is retryable
            retryable_codes = [
                20429,  # Too many requests (rate limit)
                20500,  # Internal server error
                20503,  # Service unavailable
                21610,  # Message send failed (temporary)
            ]
            
            if e.code in retryable_codes and retry_count < SMSService.MAX_RETRIES:
                # Retry with exponential backoff
                wait_time = SMSService.RETRY_DELAY_SECONDS * (2 ** retry_count)
                logger.info("Retrying SMS send in {} seconds (attempt {}/{})".format(
                    wait_time,
                    retry_count + 1,
                    SMSService.MAX_RETRIES
                ))
                time.sleep(wait_time)
                return SMSService._send_sms_with_retry(to_number, message, retry_count + 1)
            
            # Non-retryable error or max retries reached
            if e.code == 21211:
                raise Exception("Invalid phone number. Please check the number and try again.")
            elif e.code == 21408:
                raise Exception("Permission denied to send to this number. Contact administrator.")
            elif e.code == 21614:
                raise Exception("Phone number is not capable of receiving SMS.")
            else:
                raise Exception("Failed to send SMS: {}".format(e.msg))
                
        except Exception as e:
            logger.error("Unexpected error sending SMS: {}".format(str(e)))
            
            # Retry for unexpected errors
            if retry_count < SMSService.MAX_RETRIES:
                wait_time = SMSService.RETRY_DELAY_SECONDS * (2 ** retry_count)
                logger.info("Retrying SMS send after unexpected error (attempt {}/{})".format(
                    retry_count + 1,
                    SMSService.MAX_RETRIES
                ))
                time.sleep(wait_time)
                return SMSService._send_sms_with_retry(to_number, message, retry_count + 1)
            
            raise Exception("Failed to send SMS after {} retries. Please try again or use a backup code.".format(
                SMSService.MAX_RETRIES
            ))
    
    @staticmethod
    def send_otp(phone_number, otp_code, user=None):
        """
        Send OTP code via SMS for MFA login.
        Uses Twilio Verify API if configured, falls back to direct SMS.
        
        Args:
            phone_number: Recipient phone number in E.164 format
            otp_code: 6-digit OTP code
            user: User object (optional, for audit logging)
            
        Returns:
            dict: Message delivery details
            
        Raises:
            Exception: If SMS delivery fails
        """
        verify_service_sid = SMSService._get_verify_service_sid()
        
        # Use Twilio Verify API if configured (bypasses A2P 10DLC requirement)
        if verify_service_sid:
            logger.info("Using Twilio Verify API for OTP to phone ending in {}".format(phone_number[-4:]))
            return SMSService._send_verification_via_verify_api(phone_number, user)
        
        # Fall back to direct SMS (requires A2P 10DLC registration)
        app_name = current_app.config.get('NAME', 'TableScope')
        
        message = "Your {} verification code is: {}. This code expires in 10 minutes.".format(
            app_name,
            otp_code
        )
        
        logger.info("Sending OTP to phone ending in {}".format(phone_number[-4:]))
        
        try:
            result = SMSService._send_sms_with_retry(phone_number, message)
            logger.info("OTP sent successfully to {}".format(phone_number[-4:]))
            return result
        except Exception as e:
            logger.error("Failed to send OTP: {}".format(str(e)))
            
            # Log SMS delivery failure in audit log
            if user:
                from redash.services.mfa_audit_service import MFAAuditService
                phone_masked = '****' + phone_number[-4:] if len(phone_number) >= 4 else '****'
                MFAAuditService.log_sms_delivery_failure(
                    user=user,
                    phone_number_masked=phone_masked,
                    error_message=str(e)
                )
            
            raise
    
    @staticmethod
    def send_verification(phone_number, verification_code, user=None):
        """
        Send verification code via SMS for phone number enrollment.
        Uses Twilio Verify API if configured, falls back to direct SMS.
        
        Args:
            phone_number: Recipient phone number in E.164 format
            verification_code: Verification code
            user: User object (optional, for audit logging)
            
        Returns:
            dict: Message delivery details
            
        Raises:
            Exception: If SMS delivery fails
        """
        verify_service_sid = SMSService._get_verify_service_sid()
        
        # Use Twilio Verify API if configured (bypasses A2P 10DLC requirement)
        if verify_service_sid:
            logger.info("Using Twilio Verify API for phone ending in {}".format(phone_number[-4:]))
            return SMSService._send_verification_via_verify_api(phone_number, user)
        
        # Fall back to direct SMS (requires A2P 10DLC registration)
        app_name = current_app.config.get('NAME', 'TableScope')
        
        message = "Welcome to {}! Your phone verification code is: {}. Enter this code to complete your MFA enrollment.".format(
            app_name,
            verification_code
        )
        
        logger.info("Sending verification code to phone ending in {}".format(phone_number[-4:]))
        
        try:
            result = SMSService._send_sms_with_retry(phone_number, message)
            logger.info("Verification code sent successfully to {}".format(phone_number[-4:]))
            return result
        except Exception as e:
            logger.error("Failed to send verification code: {}".format(str(e)))
            
            # Log SMS delivery failure in audit log
            if user:
                from redash.services.mfa_audit_service import MFAAuditService
                phone_masked = '****' + phone_number[-4:] if len(phone_number) >= 4 else '****'
                MFAAuditService.log_sms_delivery_failure(
                    user=user,
                    phone_number_masked=phone_masked,
                    error_message=str(e)
                )
            
            raise
    
    @staticmethod
    def _send_verification_via_verify_api(phone_number, user=None):
        """
        Send verification code using Twilio Verify API.
        This bypasses A2P 10DLC requirements and works with trial accounts.
        
        Args:
            phone_number: Recipient phone number in E.164 format
            user: User object (optional, for audit logging)
            
        Returns:
            dict: Verification details
            
        Raises:
            Exception: If verification send fails
        """
        try:
            from twilio.base.exceptions import TwilioRestException
        except ImportError:
            raise Exception("SMS service not available")
        
        try:
            client = SMSService._get_twilio_client()
            verify_service_sid = SMSService._get_verify_service_sid()
            
            # Send verification using Verify API
            verification = client.verify \
                .services(verify_service_sid) \
                .verifications \
                .create(to=phone_number, channel='sms')
            
            logger.info("Verify API: Verification sent to {}. SID: {}, Status: {}".format(
                phone_number[-4:],
                verification.sid,
                verification.status
            ))
            
            return {
                'sid': verification.sid,
                'status': verification.status,
                'to': phone_number,
                'success': True,
                'method': 'verify_api'
            }
            
        except TwilioRestException as e:
            logger.error("Twilio Verify API error: {} (Code: {})".format(e.msg, e.code))
            
            # Handle specific error codes
            if e.code == 60200:
                raise Exception("Invalid phone number format. Please use E.164 format (+1XXXXXXXXXX).")
            elif e.code == 60203:
                raise Exception("Maximum verification attempts reached. Please try again later.")
            elif e.code == 60212:
                raise Exception("Too many verification requests. Please wait before trying again.")
            else:
                raise Exception("Failed to send verification: {}".format(e.msg))
                
        except Exception as e:
            logger.error("Unexpected error with Verify API: {}".format(str(e)))
            
            # Log SMS delivery failure
            if user:
                from redash.services.mfa_audit_service import MFAAuditService
                phone_masked = '****' + phone_number[-4:] if len(phone_number) >= 4 else '****'
                MFAAuditService.log_sms_delivery_failure(
                    user=user,
                    phone_number_masked=phone_masked,
                    error_message=str(e)
                )
            
            raise Exception("Failed to send verification code. Please try again.")
    
    @staticmethod
    def send_notification(phone_number, notification_message):
        """
        Send notification SMS for security events (e.g., phone number changes).
        
        Args:
            phone_number: Recipient phone number in E.164 format
            notification_message: Notification message text
            
        Returns:
            dict: Message delivery details
            
        Raises:
            Exception: If SMS delivery fails
        """
        app_name = current_app.config.get('NAME', 'TableScope')
        
        message = "{}: {}".format(app_name, notification_message)
        
        logger.info("Sending notification to phone ending in {}".format(phone_number[-4:]))
        
        try:
            result = SMSService._send_sms_with_retry(phone_number, message)
            logger.info("Notification sent successfully to {}".format(phone_number[-4:]))
            return result
        except Exception as e:
            # For notifications, we log but don't raise - they're not critical
            logger.error("Failed to send notification SMS: {}".format(str(e)))
            # Return failure status instead of raising
            return {
                'success': False,
                'error': str(e)
            }
    
    @staticmethod
    def verify_code_with_verify_api(phone_number, code):
        """
        Verify a code using Twilio Verify API.
        
        Args:
            phone_number: Phone number in E.164 format
            code: Verification code entered by user
            
        Returns:
            dict: Verification result with success status
            
        Raises:
            Exception: If verification fails
        """
        try:
            from twilio.base.exceptions import TwilioRestException
        except ImportError:
            raise Exception("SMS service not available")
        
        try:
            client = SMSService._get_twilio_client()
            verify_service_sid = SMSService._get_verify_service_sid()
            
            if not verify_service_sid:
                raise Exception("Verify Service not configured")
            
            # Check verification code
            verification_check = client.verify \
                .services(verify_service_sid) \
                .verification_checks \
                .create(to=phone_number, code=code)
            
            logger.info("Verify API: Code check for {}. Status: {}".format(
                phone_number[-4:],
                verification_check.status
            ))
            
            if verification_check.status == 'approved':
                return {
                    'success': True,
                    'status': 'approved',
                    'method': 'verify_api'
                }
            else:
                return {
                    'success': False,
                    'status': verification_check.status,
                    'method': 'verify_api'
                }
            
        except TwilioRestException as e:
            logger.error("Twilio Verify API check error: {} (Code: {})".format(e.msg, e.code))
            
            # Handle specific error codes
            if e.code == 60202:
                raise Exception("Maximum check attempts reached. Please request a new code.")
            elif e.code == 60203:
                raise Exception("Verification code expired. Please request a new code.")
            elif e.code == 60200:
                raise Exception("Invalid phone number format.")
            else:
                raise Exception("Verification failed: {}".format(e.msg))
                
        except Exception as e:
            logger.error("Unexpected error checking verification code: {}".format(str(e)))
            raise Exception("Failed to verify code. Please try again.")
