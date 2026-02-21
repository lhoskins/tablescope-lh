# -*- coding: utf-8 -*-
"""
MFA (Multi-Factor Authentication) handlers for enrollment, verification, and settings management.
"""
import logging

# Python 2/3 compatibility for secrets module
try:
    import secrets
except ImportError:
    # Python 2 fallback
    import random
    import string
    import base64
    
    class secrets:
        """Minimal secrets module implementation for Python 2."""
        
        @staticmethod
        def choice(seq):
            """Choose a random element from a non-empty sequence."""
            return random.SystemRandom().choice(seq)
        
        @staticmethod
        def token_urlsafe(nbytes=32):
            """Generate a random URL-safe token."""
            token_bytes = ''.join(
                chr(random.SystemRandom().randint(0, 255)) 
                for _ in range(nbytes)
            )
            return base64.urlsafe_b64encode(token_bytes).rstrip('=')

from flask import request
from flask_login import current_user, login_user

from redash import models, redis_connection
from redash.handlers.base import BaseResource
from redash.services.mfa_service import MFAService
from redash.services.sms_service import SMSService
from redash.permissions import require_access, require_permission, view_only

logger = logging.getLogger(__name__)


def generate_temp_token(user_id):
    """Generate a temporary session token for MFA verification state."""
    token = secrets.token_urlsafe(32)
    redis_key = "mfa:temp_token:{}".format(token)
    redis_connection.setex(redis_key, 300, str(user_id))  # 5 minutes
    return token


def validate_temp_token(token):
    """Validate temporary token and return user."""
    if not token:
        return None
    
    redis_key = "mfa:temp_token:{}".format(token)
    user_id = redis_connection.get(redis_key)
    
    if not user_id:
        return None
    
    try:
        user = models.User.get_by_id(int(user_id))
        return user
    except Exception as e:
        logger.error("Failed to get user from temp token: {}".format(str(e)))
        return None


class MFAVerifyResource(BaseResource):
    """
    Endpoint to verify MFA OTP or backup code during login.
    This endpoint does not require authentication as it's used during the login process.
    """
    decorators = []  # Override BaseResource decorators to allow unauthenticated access
    
    def post(self):
        """Verify OTP or backup code and complete authentication."""
        temp_token = request.json.get('temp_token')
        otp = request.json.get('otp')
        backup_code = request.json.get('backup_code')
        
        # Validate temp token and get user
        user = validate_temp_token(temp_token)
        if not user:
            return {'error': 'Invalid or expired session'}, 401
        
        try:
            if otp:
                # Get user's MFA config to get phone number
                config = models.MFAConfig.query.filter_by(user_id=user.id).first()
                if not config:
                    return {'error': 'MFA not configured'}, 400
                
                # Check if using Twilio Verify API
                from flask import current_app
                verify_service_sid = current_app.config.get('TWILIO_VERIFY_SERVICE_SID')
                
                verified = False
                if verify_service_sid:
                    # Use Twilio Verify API to check the code
                    try:
                        result = SMSService.verify_code_with_verify_api(config.phone_number, otp)
                        verified = result.get('success', False)
                        logger.info("Verify API check for user {}: {}".format(user.id, result.get('status')))
                    except Exception as e:
                        logger.error("Verify API check failed for user {}: {}".format(user.id, str(e)))
                        return {'error': str(e)}, 401
                else:
                    # Use our OTP verification
                    verified = MFAService.verify_otp(user, otp)
                
                if verified:
                    login_user(user)
                    
                    # Mark session as MFA-verified (Requirement 12.1)
                    from flask import session
                    from datetime import datetime
                    session['mfa_verified'] = True
                    session['mfa_verified_at'] = datetime.utcnow().isoformat()
                    
                    # Get redirect URL from session
                    org_slug = session.pop('mfa_org_slug', None)
                    next_path = session.pop('mfa_next_path', None)
                    
                    # Build redirect URL
                    if next_path:
                        redirect_url = next_path
                    elif org_slug:
                        redirect_url = '/{}'.format(org_slug)
                    else:
                        redirect_url = '/'
                    
                    # Delete temp token
                    redis_key = "mfa:temp_token:{}".format(temp_token)
                    redis_connection.delete(redis_key)
                    
                    logger.info("User {} successfully verified OTP, redirecting to {}".format(user.id, redirect_url))
                    
                    return {'status': 'success', 'redirect': redirect_url}, 200
                else:
                    return {'error': 'Invalid verification code'}, 401
                    
            elif backup_code:
                # Verify backup code
                success, remaining = MFAService.verify_backup_code(user, backup_code)
                if success:
                    login_user(user)
                    
                    # Mark session as MFA-verified (Requirement 12.1)
                    from flask import session
                    from datetime import datetime
                    session['mfa_verified'] = True
                    session['mfa_verified_at'] = datetime.utcnow().isoformat()
                    
                    # Get redirect URL from session
                    org_slug = session.pop('mfa_org_slug', None)
                    next_path = session.pop('mfa_next_path', None)
                    
                    # Build redirect URL
                    if next_path:
                        redirect_url = next_path
                    elif org_slug:
                        redirect_url = '/{}'.format(org_slug)
                    else:
                        redirect_url = '/'
                    
                    # Delete temp token
                    redis_key = "mfa:temp_token:{}".format(temp_token)
                    redis_connection.delete(redis_key)
                    
                    logger.info("User {} used backup code ({} remaining), redirecting to {}".format(user.id, remaining, redirect_url))
                    
                    warning = None
                    if remaining < 3:
                        warning = "You have {} backup codes remaining. Generate new codes soon.".format(remaining)
                    
                    return {
                        'status': 'success',
                        'redirect': redirect_url,
                        'warning': warning
                    }, 200
                else:
                    return {'error': 'Invalid backup code'}, 401
            else:
                return {'error': 'OTP or backup code required'}, 400
                
        except Exception as e:
            logger.error("MFA verification error for user {}: {}".format(user.id, str(e)))
            return {'error': str(e)}, 401


class MFAResendResource(BaseResource):
    """
    Endpoint to resend OTP code during MFA challenge.
    This endpoint does not require authentication as it's used during the login process.
    """
    decorators = []  # Override BaseResource decorators to allow unauthenticated access
    
    def post(self):
        """Resend OTP to user's registered phone."""
        temp_token = request.json.get('temp_token')
        
        # Validate temp token and get user
        user = validate_temp_token(temp_token)
        if not user:
            return {'error': 'Invalid or expired session'}, 401
        
        try:
            # Check if user has MFA config
            config = models.MFAConfig.query.filter_by(user_id=user.id, is_enabled=True).first()
            if not config:
                return {'error': 'MFA not enrolled'}, 400
            
            # Check if using Twilio Verify API
            from flask import current_app
            verify_service_sid = current_app.config.get('TWILIO_VERIFY_SERVICE_SID')
            
            if verify_service_sid:
                # Use Twilio Verify API - it generates its own code
                SMSService.send_otp(config.phone_number, None, user=user)
                logger.info("Resent OTP via Verify API to user {}".format(user.id))
            else:
                # Generate and send new OTP using our system
                otp = MFAService.generate_otp(user)
                SMSService.send_otp(config.phone_number, otp, user=user)
                logger.info("Resent OTP to user {}".format(user.id))
            
            return {'status': 'success', 'message': 'New code sent'}, 200
            
        except Exception as e:
            logger.error("Failed to resend OTP for user {}: {}".format(user.id, str(e)))
            return {'error': str(e)}, 500


class MFAEnrollResource(BaseResource):
    """
    Endpoint to enroll in MFA by providing phone number.
    """
    
    def post(self):
        """Initiate MFA enrollment with phone number."""
        phone_number = request.json.get('phone_number')
        
        if not phone_number:
            return {'error': 'Phone number required'}, 400
        
        try:
            # Enroll user
            config, backup_codes = MFAService.enroll_user(current_user, phone_number)
            
            # Check if using Verify API
            from flask import current_app
            verify_service_sid = current_app.config.get('TWILIO_VERIFY_SERVICE_SID')
            
            if verify_service_sid:
                # Using Verify API - it generates its own code
                SMSService.send_verification(phone_number, None, user=current_user)
                logger.info("User {} initiated MFA enrollment via Verify API".format(current_user.id))
            else:
                # Using direct SMS - generate our own OTP
                otp = MFAService.generate_otp(current_user)
                SMSService.send_verification(phone_number, otp, user=current_user)
                logger.info("User {} initiated MFA enrollment".format(current_user.id))
            
            return {
                'status': 'verification_required',
                'phone_masked': config.get_masked_phone(),
                'backup_codes': backup_codes,
                'message': 'Verification code sent. Enter it to complete enrollment.'
            }, 200
            
        except ValueError as e:
            return {'error': str(e)}, 400
        except Exception as e:
            logger.error("MFA enrollment error for user {}: {}".format(current_user.id, str(e)))
            return {'error': 'Failed to enroll in MFA'}, 500


class MFAEnrollVerifyResource(BaseResource):
    """
    Endpoint to verify phone number during enrollment.
    """
    
    def post(self):
        """Verify OTP to complete enrollment."""
        otp = request.json.get('otp')
        
        if not otp:
            return {'error': 'OTP required'}, 400
        
        try:
            # Check if using Verify API
            from flask import current_app
            verify_service_sid = current_app.config.get('TWILIO_VERIFY_SERVICE_SID')
            
            # Get user's phone number
            config = models.MFAConfig.query.filter_by(user_id=current_user.id).first()
            if not config:
                return {'error': 'MFA config not found'}, 404
            
            verified = False
            
            if verify_service_sid:
                # Use Verify API to check the code
                try:
                    result = SMSService.verify_code_with_verify_api(config.phone_number, otp)
                    verified = result.get('success', False)
                    logger.info("Verify API check for user {}: {}".format(current_user.id, result.get('status')))
                except Exception as e:
                    logger.error("Verify API check failed for user {}: {}".format(current_user.id, str(e)))
                    return {'error': str(e)}, 401
            else:
                # Use our OTP verification
                verified = MFAService.verify_otp(current_user, otp)
            
            if verified:
                # Mark phone as verified
                config.phone_number_verified = True
                models.db.session.commit()
                
                # Mark session as MFA-verified after enrollment
                from flask import session
                from datetime import datetime
                session['mfa_verified'] = True
                session['mfa_verified_at'] = datetime.utcnow().isoformat()
                session.pop('mfa_enrollment_required', None)
                session.pop('pending_user_id', None)
                
                logger.info("User {} completed MFA enrollment".format(current_user.id))
                
                return {
                    'status': 'success',
                    'message': 'MFA enrollment complete'
                }, 200
            else:
                return {'error': 'Invalid OTP'}, 401
                
        except Exception as e:
            logger.error("MFA enrollment verification error for user {}: {}".format(current_user.id, str(e)))
            return {'error': str(e)}, 401


class MFAEnrollStatusResource(BaseResource):
    """
    Endpoint to check MFA enrollment status.
    """
    
    def get(self):
        """Get current user's MFA enrollment status."""
        is_required = MFAService.is_mfa_required(current_user)
        is_enrolled = MFAService.is_enrolled(current_user)
        
        config = models.MFAConfig.query.filter_by(user_id=current_user.id).first()
        
        response = {
            'required': is_required,
            'enrolled': is_enrolled,
            'phone_verified': config.phone_number_verified if config else False
        }
        
        if config:
            response['phone_masked'] = config.get_masked_phone()
        
        return response, 200


class MFASettingsResource(BaseResource):
    """
    Endpoint to manage MFA settings.
    """
    
    def get(self):
        """Get current MFA settings."""
        try:
            config = models.MFAConfig.query.filter_by(user_id=current_user.id).first()
            
            # Check if MFA is required for this user
            try:
                is_required = MFAService.is_mfa_required(current_user)
            except Exception as e:
                logger.error("[MFA Settings] Error checking if MFA required for user {}: {}".format(current_user.id, str(e)))
                is_required = False  # Default to False if check fails
            
            # Build response with consistent structure (Requirement 1.3)
            try:
                if not config:
                    # Non-enrolled user - return all fields with null/0 values
                    response_data = {
                        'enrolled': False,
                        'required': is_required,
                        'phone_masked': None,
                        'enrolled_at': None,
                        'last_used_at': None,
                        'backup_codes_remaining': 0
                    }
                else:
                    # Enrolled user - return actual values
                    # Count unused backup codes
                    unused_codes = models.MFABackupCode.query.filter_by(
                        user_id=current_user.id,
                        is_used=False
                    ).count()
                    
                    response_data = {
                        'enrolled': True,
                        'required': is_required,
                        'phone_masked': config.get_masked_phone(),
                        'enrolled_at': config.enrolled_at.isoformat() if config.enrolled_at else None,
                        'last_used_at': config.last_used_at.isoformat() if config.last_used_at else None,
                        'backup_codes_remaining': unused_codes
                    }
                
                # Validate response structure before returning (Requirement 4.1, 4.2)
                required_fields = ['enrolled', 'required', 'phone_masked', 'enrolled_at', 'last_used_at', 'backup_codes_remaining']
                for field in required_fields:
                    if field not in response_data:
                        logger.warning("[MFA Settings] Missing field in response for user {}: {}".format(current_user.id, field))
                        # Add missing field with default value
                        if field == 'backup_codes_remaining':
                            response_data[field] = 0
                        elif field in ['enrolled', 'required']:
                            response_data[field] = False
                        else:
                            response_data[field] = None
                
                # Log complete response data before returning (Requirement 2.1)
                logger.info("[MFA Settings] Returning response for user {}: enrolled={}, required={}, fields={}".format(
                    current_user.id, 
                    response_data.get('enrolled'), 
                    response_data.get('required'),
                    len(response_data)
                ))
                logger.info("[MFA Settings] Complete response data for user {}: {}".format(
                    current_user.id,
                    response_data
                ))
                
                return response_data, 200
                
            except Exception as e:
                # Catch serialization errors (Requirement 1.4, 2.3)
                import traceback
                logger.error("[MFA Settings] Error building response for user {}: {}".format(current_user.id, str(e)))
                logger.error("[MFA Settings] Exception details: {}".format(repr(e)))
                # Log full stack trace for debugging (Requirement 2.3)
                logger.error("[MFA Settings] Full stack trace:\n{}".format(traceback.format_exc()))
                # Return a safe default response with descriptive error message (Requirement 2.4)
                return {
                    'enrolled': False,
                    'required': False,
                    'phone_masked': None,
                    'enrolled_at': None,
                    'last_used_at': None,
                    'backup_codes_remaining': 0
                }, 200
                
        except Exception as e:
            # Log exceptions with full stack trace (Requirement 2.3)
            import traceback
            logger.error("[MFA Settings] Error loading MFA settings for user {}: {}".format(current_user.id, str(e)))
            logger.error("[MFA Settings] Full stack trace:\n{}".format(traceback.format_exc()))
            # Return descriptive error message (Requirement 2.4)
            return {
                'error': 'Failed to load MFA settings',
                'message': 'An error occurred while loading your MFA settings. Please try again or contact support if the issue persists.',
                'details': str(e)
            }, 500
    
    def put(self):
        """Update MFA settings (phone number)."""
        new_phone = request.json.get('phone_number')
        password = request.json.get('password')
        
        if not new_phone or not password:
            return {'error': 'Phone number and password required'}, 400
        
        # Verify password
        if not current_user.verify_password(password):
            return {'error': 'Invalid password'}, 401
        
        try:
            config = MFAService.update_phone_number(current_user, new_phone)
            
            # Send verification OTP
            otp = MFAService.generate_otp(current_user)
            SMSService.send_verification(new_phone, otp, user=current_user)
            
            logger.info("User {} updated MFA phone number".format(current_user.id))
            
            return {
                'status': 'verification_required',
                'phone_masked': config.get_masked_phone(),
                'message': 'Verification code sent to new number'
            }, 200
            
        except Exception as e:
            logger.error("Failed to update phone for user {}: {}".format(current_user.id, str(e)))
            return {'error': str(e)}, 400


class MFABackupCodesResource(BaseResource):
    """
    Endpoint to regenerate backup codes.
    """
    
    def post(self):
        """Regenerate backup codes."""
        password = request.json.get('password')
        
        if not password:
            return {'error': 'Password required'}, 400
        
        # Verify password
        if not current_user.verify_password(password):
            return {'error': 'Invalid password'}, 401
        
        try:
            backup_codes = MFAService.regenerate_backup_codes(current_user)
            
            logger.info("User {} regenerated backup codes".format(current_user.id))
            
            return {
                'backup_codes': backup_codes,
                'message': 'New backup codes generated. Save them securely.'
            }, 200
            
        except Exception as e:
            logger.error("Backup code regeneration error for user {}: {}".format(current_user.id, str(e)))
            return {'error': 'Failed to regenerate backup codes'}, 500
