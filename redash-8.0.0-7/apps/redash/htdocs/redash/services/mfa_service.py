"""
MFA Service
Core service for managing Multi-Factor Authentication operations.
"""

import logging
import re
from datetime import datetime, timedelta
from flask import current_app

# Python 2/3 compatibility for secrets module
try:
    import secrets
except ImportError:
    # Python 2 fallback
    import random
    import string
    
    class secrets:
        """Minimal secrets module implementation for Python 2."""
        
        @staticmethod
        def choice(seq):
            """Choose a random element from a non-empty sequence."""
            return random.SystemRandom().choice(seq)

from redash import redis_connection
from redash.models import db, MFAConfig, MFABackupCode, User
from redash.models.users import Group
from redash.services.mfa_audit_service import MFAAuditService

logger = logging.getLogger(__name__)


class MFAService:
    """
    Service for managing MFA operations including OTP generation,
    verification, backup codes, and enrollment.
    
    Configuration is loaded from application settings (environment variables).
    """
    
    @staticmethod
    def _get_config(key, default):
        """
        Get MFA configuration value from app config.
        
        Args:
            key: Configuration key
            default: Default value if not configured
            
        Returns:
            Configuration value
        """
        try:
            return current_app.config.get(key, default)
        except RuntimeError:
            # Outside application context, use defaults
            return default
    
    @property
    def OTP_LENGTH(self):
        return self._get_config('MFA_OTP_LENGTH', 6)
    
    @property
    def OTP_EXPIRY_MINUTES(self):
        return self._get_config('MFA_OTP_EXPIRY_MINUTES', 10)
    
    @property
    def MAX_OTP_ATTEMPTS(self):
        return self._get_config('MFA_MAX_OTP_ATTEMPTS', 5)
    
    @property
    def LOCKOUT_MINUTES(self):
        return self._get_config('MFA_LOCKOUT_MINUTES', 15)
    
    @property
    def MAX_SMS_REQUESTS_PER_PERIOD(self):
        return self._get_config('MFA_MAX_SMS_REQUESTS_PER_PERIOD', 3)
    
    @property
    def SMS_REQUEST_PERIOD_MINUTES(self):
        return self._get_config('MFA_SMS_REQUEST_PERIOD_MINUTES', 10)
    
    @property
    def BACKUP_CODE_COUNT(self):
        return self._get_config('MFA_BACKUP_CODE_COUNT', 10)
    
    @property
    def BACKUP_CODE_WARNING_THRESHOLD(self):
        return self._get_config('MFA_BACKUP_CODE_WARNING_THRESHOLD', 3)
    
    @staticmethod
    def is_mfa_required(user):
        """
        Check if MFA is required for the user based on their role.
        
        Args:
            user: User object
            
        Returns:
            bool: True if MFA is enabled and user has privileged role requiring MFA
        """
        # First check if MFA is enabled in settings
        try:
            mfa_enabled = current_app.config.get('MFA_ENABLED', False)
            logger.info("[MFA] MFA_ENABLED setting: {}".format(mfa_enabled))
            if not mfa_enabled:
                logger.info("[MFA] MFA is disabled in settings, returning False")
                return False
        except RuntimeError:
            # Outside application context, check if MFA is configured
            from redash.settings import is_mfa_configured
            is_configured = is_mfa_configured()
            logger.info("[MFA] Outside app context, is_mfa_configured: {}".format(is_configured))
            if not is_configured:
                return False
        
        # Define privileged roles that require MFA
        # Both organization admins and super admins must use MFA
        privileged_roles = [
            Group.ROLE_ORG_ADMIN,      # Organization administrators
            Group.ROLE_SUPER_ADMIN     # Super administrators (SuperUser group)
        ]
        logger.info("[MFA] Checking user {} groups: {}".format(user.id, user.group_ids))
        
        # Check if user has any privileged role through group membership
        user_groups = Group.query.filter(Group.id.in_(user.group_ids)).all()
        logger.info("[MFA] Found {} groups for user {}".format(len(user_groups), user.id))
        
        for group in user_groups:
            role_type = getattr(group, 'role_type', None)
            group_name = getattr(group, 'name', 'Unknown')
            logger.info("[MFA] Group '{}' (ID: {}): type={}, role_type={}".format(
                group_name, group.id, group.type, role_type
            ))
            
            # Check if this group has a privileged role
            if role_type in privileged_roles:
                logger.info("[MFA] User {} has privileged role '{}' via group '{}' - MFA REQUIRED".format(
                    user.id, role_type, group_name
                ))
                return True
            
            # Also check by group name as a fallback (case-insensitive)
            # This handles cases where role_type might not be set correctly
            group_name_lower = group_name.lower()
            if 'admin' in group_name_lower or 'superuser' in group_name_lower:
                logger.info("[MFA] User {} is in admin/superuser group '{}' (by name) - MFA REQUIRED".format(
                    user.id, group_name
                ))
                return True
        
        logger.info("[MFA] User {} does not have privileged role, returning False".format(user.id))
        return False
    
    @staticmethod
    def is_enrolled(user):
        """
        Check if user has completed MFA enrollment.
        
        Args:
            user: User object
            
        Returns:
            bool: True if user is enrolled in MFA
        """
        return MFAConfig.is_enrolled(user.id)
    
    @staticmethod
    def enroll_user(user, phone_number):
        """
        Enroll a user in MFA with the provided phone number.
        
        Args:
            user: User object
            phone_number: Phone number in E.164 format
            
        Returns:
            tuple: (MFAConfig object, list of backup codes)
            
        Raises:
            ValueError: If phone number format is invalid
        """
        # Validate phone number format
        if not MFAService._validate_phone_number(phone_number):
            raise ValueError("Invalid phone number format. Use E.164 format (e.g., +1234567890)")
        
        # Create or update MFA config
        config = MFAConfig.query.filter_by(user_id=user.id).first()
        if not config:
            config = MFAConfig(
                user_id=user.id,
                phone_number=phone_number,
                phone_number_verified=False,
                enrolled_at=datetime.utcnow()
            )
            db.session.add(config)
        else:
            config.phone_number = phone_number
            config.phone_number_verified = False
            config.is_enabled = True
        
        # Generate backup codes
        backup_codes = MFAService._generate_backup_codes(user)
        
        db.session.commit()
        
        logger.info("User {} enrolled in MFA".format(user.id))
        
        # Log enrollment in audit log
        MFAAuditService.log_mfa_enrollment(
            user=user,
            phone_number_masked=config.get_masked_phone()
        )
        
        return config, backup_codes
    
    @staticmethod
    def generate_otp(user):
        """
        Generate a new OTP for the user and store it in Redis.
        
        Args:
            user: User object
            
        Returns:
            str: Generated OTP code
            
        Raises:
            Exception: If rate limit exceeded
        """
        service = MFAService()
        
        # Check rate limiting
        if not MFAService._check_sms_rate_limit(user.id):
            raise Exception("Too many SMS requests. Please wait before requesting another code.")
        
        # Generate OTP with configured length
        otp = ''.join(secrets.choice('0123456789') for _ in range(service.OTP_LENGTH))
        
        # Store in Redis with configured expiry
        redis_key = "mfa:otp:{}".format(user.id)
        redis_connection.setex(
            redis_key,
            service.OTP_EXPIRY_MINUTES * 60,
            otp
        )
        
        # Reset attempt counter
        attempts_key = "mfa:attempts:{}".format(user.id)
        redis_connection.delete(attempts_key)
        
        # Increment SMS request counter
        MFAService._increment_sms_request_counter(user.id)
        
        logger.info("Generated OTP for user {}".format(user.id))
        
        return otp
    
    @staticmethod
    def verify_otp(user, otp):
        """
        Verify the provided OTP for the user.
        
        Args:
            user: User object
            otp: OTP code to verify
            
        Returns:
            bool: True if OTP is valid
            
        Raises:
            Exception: If account is locked, OTP expired, or invalid
        """
        service = MFAService()
        
        # Check if account is locked
        if MFAService._is_account_locked(user.id):
            remaining = MFAService._get_lockout_remaining(user.id)
            raise Exception("Account locked due to too many failed attempts. Try again in {} minutes.".format(remaining))
        
        # Get stored OTP from Redis
        redis_key = "mfa:otp:{}".format(user.id)
        stored_otp = redis_connection.get(redis_key)
        
        if not stored_otp:
            # Log expired OTP attempt
            MFAAuditService.log_mfa_authentication_failure(
                user=user,
                reason='expired_otp'
            )
            raise Exception("OTP expired or not found. Please request a new code.")
        
        # Verify OTP
        if stored_otp.decode() == otp:
            # Success - delete OTP and reset counters
            redis_connection.delete(redis_key)
            redis_connection.delete("mfa:attempts:{}".format(user.id))
            
            # Update last used timestamp
            config = MFAConfig.query.filter_by(user_id=user.id).first()
            if config:
                config.mark_used()
                db.session.commit()
            
            logger.info("User {} successfully verified OTP".format(user.id))
            
            # Log successful authentication
            MFAAuditService.log_mfa_authentication_success(user=user)
            
            return True
        else:
            # Failed attempt
            MFAService._increment_failed_attempts(user.id)
            attempts = MFAService._get_failed_attempts(user.id)
            
            max_attempts = service.MAX_OTP_ATTEMPTS
            lockout_minutes = service.LOCKOUT_MINUTES
            
            if attempts >= max_attempts:
                MFAService._lock_account(user.id)
                logger.warning("User {} locked due to too many failed OTP attempts".format(user.id))
                
                # Log account lockout
                MFAAuditService.log_mfa_authentication_failure(
                    user=user,
                    reason='account_locked',
                    details={'attempts': attempts}
                )
                
                raise Exception("Too many failed attempts. Account locked for {} minutes.".format(lockout_minutes))
            
            logger.warning("User {} failed OTP verification (attempt {})".format(user.id, attempts))
            
            # Log failed attempt
            MFAAuditService.log_mfa_authentication_failure(
                user=user,
                reason='invalid_otp',
                details={'attempts': attempts, 'remaining_attempts': max_attempts - attempts}
            )
            
            raise Exception("Invalid OTP. {} attempts remaining.".format(max_attempts - attempts))
    
    @staticmethod
    def verify_backup_code(user, code):
        """
        Verify a backup code for the user.
        
        Args:
            user: User object
            code: Backup code to verify
            
        Returns:
            tuple: (success: bool, remaining_codes: int or None)
        """
        success, remaining = MFABackupCode.verify_and_use(user.id, code)
        
        if success:
            # Update last used timestamp
            config = MFAConfig.query.filter_by(user_id=user.id).first()
            if config:
                config.mark_used()
                db.session.commit()
            
            # Log backup code usage
            MFAAuditService.log_backup_code_usage(
                user=user,
                remaining_codes=remaining
            )
        else:
            # Log failed backup code attempt
            MFAAuditService.log_mfa_authentication_failure(
                user=user,
                reason='invalid_backup_code'
            )
        
        return success, remaining
    
    @staticmethod
    def regenerate_backup_codes(user):
        """
        Regenerate backup codes for a user.
        
        Args:
            user: User object
            
        Returns:
            list: New backup codes (plaintext)
        """
        # Invalidate all existing backup codes
        MFABackupCode.invalidate_all(user.id)
        
        # Generate new codes with configured count
        backup_codes = MFAService._generate_backup_codes(user)
        
        db.session.commit()
        
        logger.info("Regenerated backup codes for user {}".format(user.id))
        
        # Log backup codes regeneration
        MFAAuditService.log_backup_codes_regenerated(user=user)
        
        return backup_codes
    
    @staticmethod
    def update_phone_number(user, new_phone_number):
        """
        Update user's phone number (requires verification).
        
        Args:
            user: User object
            new_phone_number: New phone number in E.164 format
            
        Returns:
            MFAConfig: Updated config object
            
        Raises:
            ValueError: If phone number format is invalid
            Exception: If MFA not enrolled
        """
        if not MFAService._validate_phone_number(new_phone_number):
            raise ValueError("Invalid phone number format")
        
        config = MFAConfig.query.filter_by(user_id=user.id).first()
        if not config:
            raise Exception("MFA not enrolled")
        
        old_phone = config.phone_number
        old_phone_masked = config.get_masked_phone()
        
        config.phone_number = new_phone_number
        config.phone_number_verified = False
        
        db.session.commit()
        
        # Get new masked phone
        new_phone_masked = config.get_masked_phone()
        
        logger.info("User {} updated phone number".format(user.id))
        
        # Log phone number change
        MFAAuditService.log_phone_number_change(
            user=user,
            old_phone_masked=old_phone_masked,
            new_phone_masked=new_phone_masked
        )
        
        return config, old_phone
    
    @staticmethod
    def disable_mfa(user, admin_user=None):
        """
        Disable MFA for a user (admin action or self-service).
        
        Args:
            user: User object to disable MFA for
            admin_user: Admin user performing the action (optional)
        """
        config = MFAConfig.query.filter_by(user_id=user.id).first()
        if config:
            config.disable()
        
        # Invalidate all backup codes
        MFABackupCode.invalidate_all(user.id)
        
        db.session.commit()
        
        if admin_user:
            logger.info("Admin {} disabled MFA for user {}".format(admin_user.id, user.id))
        else:
            logger.info("User {} disabled their own MFA".format(user.id))
        
        # Log MFA disable action
        MFAAuditService.log_mfa_disabled(
            user=user,
            admin_user=admin_user
        )
    
    # Private helper methods
    
    @staticmethod
    def _validate_phone_number(phone_number):
        """
        Validate phone number format (E.164).
        
        Args:
            phone_number: Phone number string
            
        Returns:
            bool: True if valid E.164 format
        """
        pattern = r'^\+[1-9]\d{1,14}$'
        return re.match(pattern, phone_number) is not None
    
    @staticmethod
    def _generate_backup_codes(user):
        """
        Generate backup codes for a user (count from configuration).
        
        Args:
            user: User object
            
        Returns:
            list: Plaintext backup codes
        """
        service = MFAService()
        count = service.BACKUP_CODE_COUNT
        codes = MFABackupCode.generate_codes_for_user(user.id, count=count)
        return codes
    
    @staticmethod
    def _check_sms_rate_limit(user_id):
        """
        Check if user has exceeded SMS request rate limit.
        
        Args:
            user_id: User ID
            
        Returns:
            bool: True if within rate limit
        """
        service = MFAService()
        key = "mfa:sms_requests:{}".format(user_id)
        count = redis_connection.get(key)
        
        if count and int(count) >= service.MAX_SMS_REQUESTS_PER_PERIOD:
            return False
        
        return True
    
    @staticmethod
    def _increment_sms_request_counter(user_id):
        """
        Increment SMS request counter.
        
        Args:
            user_id: User ID
        """
        service = MFAService()
        key = "mfa:sms_requests:{}".format(user_id)
        count = redis_connection.incr(key)
        
        if count == 1:
            # Set expiry on first request
            redis_connection.expire(key, service.SMS_REQUEST_PERIOD_MINUTES * 60)
    
    @staticmethod
    def _increment_failed_attempts(user_id):
        """
        Increment failed OTP attempt counter.
        
        Args:
            user_id: User ID
        """
        service = MFAService()
        key = "mfa:attempts:{}".format(user_id)
        redis_connection.incr(key)
        redis_connection.expire(key, service.LOCKOUT_MINUTES * 60)
    
    @staticmethod
    def _get_failed_attempts(user_id):
        """
        Get number of failed OTP attempts.
        
        Args:
            user_id: User ID
            
        Returns:
            int: Number of failed attempts
        """
        key = "mfa:attempts:{}".format(user_id)
        count = redis_connection.get(key)
        return int(count) if count else 0
    
    @staticmethod
    def _is_account_locked(user_id):
        """
        Check if account is locked due to failed attempts.
        
        Args:
            user_id: User ID
            
        Returns:
            bool: True if account is locked
        """
        service = MFAService()
        attempts = MFAService._get_failed_attempts(user_id)
        return attempts >= service.MAX_OTP_ATTEMPTS
    
    @staticmethod
    def _lock_account(user_id):
        """
        Lock account for lockout period.
        
        Args:
            user_id: User ID
        """
        service = MFAService()
        key = "mfa:locked:{}".format(user_id)
        redis_connection.setex(key, service.LOCKOUT_MINUTES * 60, "1")
    
    @staticmethod
    def _get_lockout_remaining(user_id):
        """
        Get remaining lockout time in minutes.
        
        Args:
            user_id: User ID
            
        Returns:
            int: Remaining minutes
        """
        key = "mfa:locked:{}".format(user_id)
        ttl = redis_connection.ttl(key)
        return max(0, ttl // 60) if ttl > 0 else 0
