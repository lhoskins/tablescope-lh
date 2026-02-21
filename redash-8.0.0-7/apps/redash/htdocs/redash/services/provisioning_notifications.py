"""
Provisioning Notifications Service

Service for sending email notifications about organization provisioning events,
particularly failures and errors that require administrator attention.
"""

import logging
from datetime import datetime

from flask_mail import Message
from redash import mail, settings

logger = logging.getLogger(__name__)


class ProvisioningNotificationService:
    """
    Service for sending provisioning-related email notifications.
    
    This service handles sending notifications to system administrators
    when organization provisioning fails or encounters errors.
    """
    
    @staticmethod
    def send_provisioning_failure_notification(organization, error_details, steps_completed):
        """
        Send email notification to system administrators when provisioning fails.
        
        Args:
            organization: Organization instance (can be None if org creation failed)
            error_details (str): Detailed error message
            steps_completed (list): List of steps that were completed before failure
            
        Returns:
            bool: True if notification sent successfully, False otherwise
        """
        # Check if email server is configured
        if not settings.email_server_is_configured():
            logger.warning('Email server not configured, skipping provisioning failure notification')
            return False
        
        # Check if notification recipients are configured
        recipients = getattr(settings, 'PROVISIONING_FAILURE_NOTIFICATION_EMAILS', [])
        if not recipients:
            logger.warning('No provisioning failure notification recipients configured')
            return False
        
        try:
            # Build email subject
            org_name = organization.name if organization else 'Unknown Organization'
            subject = 'Organization Provisioning Failed: {}'.format(org_name)
            
            # Build email body
            body = ProvisioningNotificationService._build_failure_email_body(
                organization, error_details, steps_completed
            )
            
            # Create and send email
            msg = Message(
                subject=subject,
                recipients=recipients,
                body=body
            )
            
            mail.send(msg)
            
            logger.info('Provisioning failure notification sent to: {}'.format(', '.join(recipients)))
            return True
            
        except Exception as e:
            logger.error('Failed to send provisioning failure notification: {}'.format(str(e)))
            return False
    
    @staticmethod
    def _build_failure_email_body(organization, error_details, steps_completed):
        """
        Build the email body for provisioning failure notification.
        
        Args:
            organization: Organization instance (can be None)
            error_details (str): Detailed error message
            steps_completed (list): List of completed steps
            
        Returns:
            str: Email body text
        """
        # Organization information
        if organization:
            org_info = """
Organization Information:
- Name: {}
- Slug: {}
- ID: {}
- Address: {}
- Primary Contact: {} {} ({})
- Provisioning Status: {}
""".format(
                organization.name,
                organization.slug,
                organization.id,
                organization.address or 'N/A',
                organization.primary_contact_first_name or '',
                organization.primary_contact_last_name or '',
                organization.primary_contact_email or 'N/A',
                organization.provisioning_status or 'unknown'
            )
        else:
            org_info = """
Organization Information:
- Organization creation failed before record was created
"""
        
        # Steps completed
        steps_info = """
Steps Completed Before Failure:
{}
""".format('\n'.join('- {}'.format(step) for step in steps_completed) if steps_completed else '- None')
        
        # Error details
        error_info = """
Error Details:
{}
""".format(error_details)
        
        # Action items
        action_items = """
Recommended Actions:
1. Review the error details above to identify the root cause
2. Check system logs for additional context
3. Verify that all required services are running (Teiid, database, mail server)
4. If VDB provisioning failed, check Teiid servlet logs
5. If user creation failed, verify database connectivity
6. If invitation failed, verify mail server configuration
7. Use the admin interface to retry failed steps or rollback the provisioning
"""
        
        # Build complete email body
        body = """
ORGANIZATION PROVISIONING FAILURE ALERT

An organization provisioning attempt has failed and requires administrator attention.

{}

{}

{}

{}

Timestamp: {}
Host: {}

This is an automated notification from the Redash provisioning system.
""".format(
            org_info.strip(),
            steps_info.strip(),
            error_info.strip(),
            action_items.strip(),
            datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
            settings.HOST or 'Unknown'
        )
        
        return body
    
    @staticmethod
    def send_provisioning_success_notification(organization, vdb_config, user):
        """
        Send email notification when provisioning completes successfully.
        
        This is optional and can be used for audit/tracking purposes.
        
        Args:
            organization: Organization instance
            vdb_config: VDB configuration instance
            user: User instance
            
        Returns:
            bool: True if notification sent successfully, False otherwise
        """
        # Check if email server is configured
        if not settings.email_server_is_configured():
            logger.debug('Email server not configured, skipping success notification')
            return False
        
        # Check if notification recipients are configured
        recipients = settings.PROVISIONING_FAILURE_NOTIFICATION_EMAILS
        if not recipients:
            logger.debug('No notification recipients configured')
            return False
        
        try:
            # Build email subject
            subject = 'Organization Provisioning Successful: {}'.format(organization.name)
            
            # Build email body
            body = """
ORGANIZATION PROVISIONING SUCCESS

A new organization has been successfully provisioned.

Organization Information:
- Name: {}
- Slug: {}
- ID: {}
- Address: {}

VDB Information:
- VDB ID: {}
- VDB Host: {}
- VDB Port: {}

Primary Contact:
- Name: {} {}
- Email: {}
- User ID: {}
- Invitation Sent: Yes

Timestamp: {}
Host: {}

This is an automated notification from the Redash provisioning system.
""".format(
                organization.name,
                organization.slug,
                organization.id,
                organization.address or 'N/A',
                vdb_config.vdb_id if vdb_config else 'N/A',
                vdb_config.vdb_host if vdb_config else 'N/A',
                vdb_config.vdb_port if vdb_config else 'N/A',
                organization.primary_contact_first_name or '',
                organization.primary_contact_last_name or '',
                organization.primary_contact_email or 'N/A',
                user.id if user else 'N/A',
                datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
                settings.HOST or 'Unknown'
            )
            
            # Create and send email
            msg = Message(
                subject=subject,
                recipients=recipients,
                body=body
            )
            
            mail.send(msg)
            
            logger.info('Provisioning success notification sent to: {}'.format(', '.join(recipients)))
            return True
            
        except Exception as e:
            logger.error('Failed to send provisioning success notification: {}'.format(str(e)))
            return False
