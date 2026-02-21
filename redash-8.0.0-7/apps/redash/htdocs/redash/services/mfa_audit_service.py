# -*- coding: utf-8 -*-
"""
MFA Audit Service

Handles audit logging for all MFA-related events for compliance and security monitoring.
"""

import logging
import json
from flask import request

from redash.models import db, AuditLog

logger = logging.getLogger(__name__)


class MFAAuditService:
    """
    Service for logging MFA-related audit events.
    
    Logs all MFA events including enrollment, authentication attempts,
    backup code usage, phone number changes, and admin actions.
    """
    
    # MFA Action Types
    ACTION_MFA_ENROLLED = 'mfa_enrolled'
    ACTION_MFA_SUCCESS = 'mfa_authentication_success'
    ACTION_MFA_FAILURE = 'mfa_authentication_failure'
    ACTION_MFA_BACKUP_CODE_USED = 'mfa_backup_code_used'
    ACTION_MFA_PHONE_CHANGED = 'mfa_phone_number_changed'
    ACTION_MFA_DISABLED = 'mfa_disabled'
    ACTION_MFA_ADMIN_DISABLED = 'mfa_admin_disabled'
    ACTION_SMS_DELIVERY_FAILURE = 'mfa_sms_delivery_failure'
    ACTION_MFA_BACKUP_CODES_REGENERATED = 'mfa_backup_codes_regenerated'
    
    @staticmethod
    def log_mfa_enrollment(user, phone_number_masked, success=True, details=None):
        """
        Log MFA enrollment event.
        
        Args:
            user: User object who enrolled
            phone_number_masked: Masked phone number (e.g., ****1234)
            success: Whether enrollment was successful
            details: Additional details (optional)
        """
        audit_details = {
            'phone_number_masked': phone_number_masked,
        }
        
        if details:
            audit_details.update(details)
        
        MFAAuditService._create_audit_log(
            action=MFAAuditService.ACTION_MFA_ENROLLED,
            user=user,
            success=success,
            details=audit_details
        )
        
        logger.info("Audit: User {} enrolled in MFA".format(user.id))
    
    @staticmethod
    def log_mfa_authentication_success(user, details=None):
        """
        Log successful MFA authentication with IP and timestamp.
        
        Args:
            user: User object who authenticated
            details: Additional details (optional)
        """
        audit_details = {
            'authentication_method': 'otp',
        }
        
        if details:
            audit_details.update(details)
        
        MFAAuditService._create_audit_log(
            action=MFAAuditService.ACTION_MFA_SUCCESS,
            user=user,
            success=True,
            details=audit_details
        )
        
        logger.info("Audit: User {} successfully authenticated with MFA".format(user.id))
    
    @staticmethod
    def log_mfa_authentication_failure(user, reason, details=None):
        """
        Log failed MFA authentication attempt with details.
        
        Args:
            user: User object who attempted authentication
            reason: Reason for failure (e.g., 'invalid_otp', 'expired_otp', 'account_locked')
            details: Additional details (optional)
        """
        audit_details = {
            'failure_reason': reason,
        }
        
        if details:
            audit_details.update(details)
        
        MFAAuditService._create_audit_log(
            action=MFAAuditService.ACTION_MFA_FAILURE,
            user=user,
            success=False,
            details=audit_details
        )
        
        logger.warning("Audit: User {} failed MFA authentication: {}".format(user.id, reason))
    
    @staticmethod
    def log_backup_code_usage(user, remaining_codes, details=None):
        """
        Log backup code usage.
        
        Args:
            user: User object who used backup code
            remaining_codes: Number of remaining backup codes
            details: Additional details (optional)
        """
        audit_details = {
            'authentication_method': 'backup_code',
            'remaining_codes': remaining_codes,
        }
        
        if details:
            audit_details.update(details)
        
        MFAAuditService._create_audit_log(
            action=MFAAuditService.ACTION_MFA_BACKUP_CODE_USED,
            user=user,
            success=True,
            details=audit_details
        )
        
        logger.info("Audit: User {} used backup code ({} remaining)".format(user.id, remaining_codes))
    
    @staticmethod
    def log_phone_number_change(user, old_phone_masked, new_phone_masked, details=None):
        """
        Log phone number change with masked values.
        
        Args:
            user: User object who changed phone number
            old_phone_masked: Old phone number (masked)
            new_phone_masked: New phone number (masked)
            details: Additional details (optional)
        """
        audit_details = {
            'old_phone_masked': old_phone_masked,
            'new_phone_masked': new_phone_masked,
        }
        
        if details:
            audit_details.update(details)
        
        MFAAuditService._create_audit_log(
            action=MFAAuditService.ACTION_MFA_PHONE_CHANGED,
            user=user,
            success=True,
            details=audit_details
        )
        
        logger.info("Audit: User {} changed MFA phone number".format(user.id))
    
    @staticmethod
    def log_mfa_disabled(user, admin_user=None, reason=None, details=None):
        """
        Log MFA disable action (self-service or admin action).
        
        Args:
            user: User object whose MFA was disabled
            admin_user: Admin user who performed the action (None for self-service)
            reason: Reason for disabling MFA (optional)
            details: Additional details (optional)
        """
        audit_details = {}
        
        if admin_user:
            # Admin disabled MFA for another user
            audit_details['admin_user_id'] = admin_user.id
            audit_details['admin_email'] = admin_user.email
            action = MFAAuditService.ACTION_MFA_ADMIN_DISABLED
        else:
            # User disabled their own MFA
            action = MFAAuditService.ACTION_MFA_DISABLED
        
        if reason:
            audit_details['reason'] = reason
        
        if details:
            audit_details.update(details)
        
        MFAAuditService._create_audit_log(
            action=action,
            user=user,
            success=True,
            details=audit_details
        )
        
        if admin_user:
            logger.info("Audit: Admin {} disabled MFA for user {}".format(admin_user.id, user.id))
        else:
            logger.info("Audit: User {} disabled their own MFA".format(user.id))
    
    @staticmethod
    def log_sms_delivery_failure(user, phone_number_masked, error_message, details=None):
        """
        Log SMS delivery failure.
        
        Args:
            user: User object for whom SMS failed
            phone_number_masked: Masked phone number
            error_message: Error message from SMS provider
            details: Additional details (optional)
        """
        audit_details = {
            'phone_number_masked': phone_number_masked,
            'error_message': error_message,
        }
        
        if details:
            audit_details.update(details)
        
        MFAAuditService._create_audit_log(
            action=MFAAuditService.ACTION_SMS_DELIVERY_FAILURE,
            user=user,
            success=False,
            details=audit_details
        )
        
        logger.error("Audit: SMS delivery failed for user {}: {}".format(user.id, error_message))
    
    @staticmethod
    def log_backup_codes_regenerated(user, details=None):
        """
        Log backup codes regeneration.
        
        Args:
            user: User object who regenerated backup codes
            details: Additional details (optional)
        """
        audit_details = {}
        
        if details:
            audit_details.update(details)
        
        MFAAuditService._create_audit_log(
            action=MFAAuditService.ACTION_MFA_BACKUP_CODES_REGENERATED,
            user=user,
            success=True,
            details=audit_details
        )
        
        logger.info("Audit: User {} regenerated backup codes".format(user.id))
    
    @staticmethod
    def _create_audit_log(action, user, success, details):
        """
        Create an audit log entry.
        
        Args:
            action: Action type (string)
            user: User object
            success: Whether action was successful
            details: Dictionary of additional details
        """
        try:
            # Get request context
            ip_address = None
            user_agent = None
            
            if request:
                ip_address = request.remote_addr
                user_agent = request.headers.get('User-Agent')
            
            # Create audit log entry
            audit_log = AuditLog(
                action=action,
                success=success,
                user_id=user.id,
                org_id=user.org_id,
                resource_type='mfa',
                resource_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                details=json.dumps(details) if details else None
            )
            
            db.session.add(audit_log)
            db.session.commit()
            
        except Exception as e:
            logger.error("Failed to create audit log for action {}: {}".format(action, str(e)))
            # Don't raise exception - audit logging should not break the main flow
            try:
                db.session.rollback()
            except:
                pass
