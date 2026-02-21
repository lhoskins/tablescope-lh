import re
import time
from flask import request
from flask_restful import abort
from flask_login import current_user, login_user
from funcy import project
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import IntegrityError
from disposable_email_domains import blacklist
from funcy import partial

from redash import models, limiter
from redash.permissions import require_permission, require_admin_or_owner, is_admin_or_owner, \
    require_permission_or_owner, require_admin
from redash.handlers.base import BaseResource, require_fields, get_object_or_404, paginate, order_results as _order_results

from redash.authentication.account import invite_link_for_user, send_invite_email, send_password_reset_email, send_verify_email
from redash.settings import parse_boolean
from redash import settings
from redash.services.mfa_service import MFAService
from redash.services.mfa_audit_service import MFAAuditService


# Ordering map for relationships
order_map = {
    'name': 'name',
    '-name': '-name',
    'active_at': 'active_at',
    '-active_at': '-active_at',
    'created_at': 'created_at',
    '-created_at': '-created_at',
    'groups': 'group_ids',
    '-groups': '-group_ids',
}

order_results = partial(
    _order_results,
    default_order='-created_at',
    allowed_orders=order_map,
)


def invite_user(org, inviter, user, send_email=True):
    d = user.to_dict()

    invite_url = invite_link_for_user(user)
    if settings.email_server_is_configured() and send_email:
        send_invite_email(inviter, user, invite_url, org)
    else:
        d['invite_link'] = invite_url

    return d


class UserListResource(BaseResource):
    decorators = BaseResource.decorators + \
        [limiter.limit('200/day;50/hour', methods=['POST'])]

    def get_users(self, disabled, pending, search_term):
        if disabled:
            users = models.User.all_disabled(self.current_org)
        else:
            users = models.User.all(self.current_org)

        if pending is not None:
            users = models.User.pending(users, pending)

        if search_term:
            users = models.User.search(users, search_term)
            self.record_event({
                'action': 'search',
                'object_type': 'user',
                'term': search_term,
                'pending': pending,
            })
        else:
            self.record_event({
                'action': 'list',
                'object_type': 'user',
                'pending': pending,
            })

        # order results according to passed order parameter,
        # special-casing search queries where the database
        # provides an order by search rank
        return order_results(users, fallback=not bool(search_term))

    @require_permission('list_users')
    def get(self):
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 25, type=int)

        groups = {group.id: group for group in models.Group.all(self.current_org)}

        # Query role assignments for all users in the organization
        role_assignments = models.RoleAssignment.query.filter(
            models.RoleAssignment.org_id == self.current_org.id
        ).all()
        
        # Build lookup dictionary for role assignments by user_id
        user_roles = {}
        for assignment in role_assignments:
            if assignment.user_id not in user_roles:
                user_roles[assignment.user_id] = []
            user_roles[assignment.user_id].append(assignment)
        
        # Query project memberships for all users in the organization
        # Use options(noload) to prevent loading user relationships that could cache stale data
        from sqlalchemy.orm import noload
        project_members = models.ProjectMember.query.options(
            noload(models.ProjectMember.user),
            noload(models.ProjectMember.added_by)
        ).join(
            models.Project
        ).filter(
            models.Project.org_id == self.current_org.id
        ).all()
        
        # Build lookup dictionary for project memberships by user_id
        user_projects = {}
        for member in project_members:
            if member.user_id not in user_projects:
                user_projects[member.user_id] = []
            user_projects[member.user_id].append({
                'id': member.project_id,
                'name': member.project.name if member.project else None,
                'role': member.role
            })

        def serialize_user(user):
            d = user.to_dict()
            user_groups = []
            for group_id in set(d['groups']):
                group = groups.get(group_id)

                if group:
                    user_groups.append({'id': group.id, 'name': group.name})

            d['groups'] = user_groups
            
            # Add role_type field
            # Determine the highest role for the user
            assignments = user_roles.get(user.id, [])
            if assignments:
                # Priority order: super_admin > organization_admin > project_admin > project_owner > designer > default
                role_priority = {
                    'super_admin': 6,
                    'organization_admin': 5,
                    'project_admin': 4,
                    'project_owner': 3,
                    'designer': 2,
                    'default': 1
                }
                highest_role = max(assignments, key=lambda a: role_priority.get(a.role_type, 0))
                d['role_type'] = highest_role.role_type
            else:
                d['role_type'] = 'default'
            
            # Add projects field
            d['projects'] = user_projects.get(user.id, [])
            
            # Add MFA status
            d['mfa_enabled'] = MFAService.is_enrolled(user)

            return d

        search_term = request.args.get('q', '')

        disabled = request.args.get('disabled', 'false')  # get enabled users by default
        disabled = parse_boolean(disabled)

        pending = request.args.get('pending', None)  # get both active and pending by default
        if pending is not None:
            pending = parse_boolean(pending)

        users = self.get_users(disabled, pending, search_term)

        return paginate(users, page, page_size, serialize_user)

    @require_admin
    def post(self):
        req = request.get_json(force=True)
        require_fields(req, ('name', 'email'))

        if '@' not in req['email']:
            abort(400, message='Bad email address.')
        name, domain = req['email'].split('@', 1)

        if domain.lower() in blacklist or domain.lower() == 'qq.com':
            abort(400, message='Bad email address.')

        user = models.User(org=self.current_org,
                           name=req['name'],
                           email=req['email'],
                           is_invitation_pending=True,
                           group_ids=[self.current_org.default_group.id])

        try:
            models.db.session.add(user)
            models.db.session.commit()
        except IntegrityError as e:
            if "email" in e.message:
                abort(400, message='Email already taken.')
            abort(500)

        self.record_event({
            'action': 'create',
            'object_id': user.id,
            'object_type': 'user'
        })

        should_send_invitation = 'no_invite' not in request.args
        return invite_user(self.current_org, self.current_user, user, send_email=should_send_invitation)


class UserInviteResource(BaseResource):
    @require_admin
    def post(self, user_id):
        user = models.User.get_by_id_and_org(user_id, self.current_org)
        return invite_user(self.current_org, self.current_user, user)


class UserResetPasswordResource(BaseResource):
    @require_admin
    def post(self, user_id):
        user = models.User.get_by_id_and_org(user_id, self.current_org)
        if user.is_disabled:
            abort(404, message='Not found')
        reset_link = send_password_reset_email(user)

        return {
            'reset_link': reset_link,
        }


class UserRegenerateApiKeyResource(BaseResource):
    def post(self, user_id):
        user = models.User.get_by_id_and_org(user_id, self.current_org)
        if user.is_disabled:
            abort(404, message='Not found')
        if not is_admin_or_owner(user_id):
            abort(403)

        user.regenerate_api_key()
        models.db.session.commit()

        self.record_event({
            'action': 'regnerate_api_key',
            'object_id': user.id,
            'object_type': 'user'
        })

        return user.to_dict(with_api_key=True)


class UserResource(BaseResource):
    decorators = BaseResource.decorators + \
        [limiter.limit('50/hour', methods=['POST'])]

    def get(self, user_id):
        require_permission_or_owner('list_users', user_id)
        user = get_object_or_404(models.User.get_by_id_and_org, user_id, self.current_org)

        self.record_event({
            'action': 'view',
            'object_id': user_id,
            'object_type': 'user',
        })

        return user.to_dict(with_api_key=is_admin_or_owner(user_id))

    def post(self, user_id):
        require_admin_or_owner(user_id)
        user = models.User.get_by_id_and_org(user_id, self.current_org)

        req = request.get_json(True)

        params = project(req, ('email', 'name', 'password', 'old_password', 'group_ids'))

        if 'password' in params and 'old_password' not in params:
            abort(403, message="Must provide current password to update password.")

        if 'old_password' in params and not user.verify_password(params['old_password']):
            abort(403, message="Incorrect current password.")

        if 'password' in params:
            user.hash_password(params.pop('password'))
            params.pop('old_password')

        if 'group_ids' in params:
            if not self.current_user.has_permission('admin'):
                abort(403, message="Must be admin to change groups membership.")

            for group_id in params['group_ids']:
                try:
                    models.Group.get_by_id_and_org(group_id, self.current_org)
                except NoResultFound:
                    abort(400, message="Group id {} is invalid.".format(group_id))

            if len(params['group_ids']) == 0:
                params.pop('group_ids')

        if 'email' in params:
            _, domain = params['email'].split('@', 1)

            if domain.lower() in blacklist or domain.lower() == 'qq.com':
                abort(400, message='Bad email address.')

        email_address_changed = 'email' in params and params['email'] != user.email
        needs_to_verify_email = email_address_changed and settings.email_server_is_configured()
        if needs_to_verify_email:
            user.is_email_verified = False

        try:
            self.update_model(user, params)
            models.db.session.commit()

            if needs_to_verify_email:
                send_verify_email(user, self.current_org)

            # The user has updated their email or password. This should invalidate all _other_ sessions,
            # forcing them to log in again. Since we don't want to force _this_ session to have to go
            # through login again, we call `login_user` in order to update the session with the new identity details.
            if current_user.id == user.id:
                login_user(user, remember=True)
        except IntegrityError as e:
            if "email" in e.message:
                message = "Email already taken."
            else:
                message = "Error updating record"

            abort(400, message=message)

        self.record_event({
            'action': 'edit',
            'object_id': user.id,
            'object_type': 'user',
            'updated_fields': params.keys()
        })

        return user.to_dict(with_api_key=is_admin_or_owner(user_id))

    @require_admin
    def delete(self, user_id):
        user = models.User.get_by_id_and_org(user_id, self.current_org)
        # admin cannot delete self; current user is an admin (`@require_admin`)
        # so just check user id
        if user.id == current_user.id:
            abort(403, message="You cannot delete your own account. "
                               "Please ask another admin to do this for you.")
        elif not user.is_invitation_pending:
            abort(403, message="You cannot delete activated users. "
                               "Please disable the user instead.")
        
        # Trigger lifecycle hook for user deletion (before actual deletion)
        try:
            from redash.services.vdb_lifecycle_hooks import on_user_deleted
            on_user_deleted(user)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error('Failed to execute user deletion hook: {}'.format(str(e)))
        
        models.db.session.delete(user)
        models.db.session.commit()

        return user.to_dict(with_api_key=is_admin_or_owner(user_id))


class UserDisableResource(BaseResource):
    @require_admin
    def post(self, user_id):
        user = models.User.get_by_id_and_org(user_id, self.current_org)
        # admin cannot disable self; current user is an admin (`@require_admin`)
        # so just check user id
        if user.id == current_user.id:
            abort(403, message="You cannot disable your own account. "
                               "Please ask another admin to do this for you.")
        user.disable()
        models.db.session.commit()

        return user.to_dict(with_api_key=is_admin_or_owner(user_id))

    @require_admin
    def delete(self, user_id):
        user = models.User.get_by_id_and_org(user_id, self.current_org)
        user.enable()
        models.db.session.commit()

        return user.to_dict(with_api_key=is_admin_or_owner(user_id))


class UserMFAResource(BaseResource):
    """
    Admin endpoint for managing user MFA settings.
    """
    
    @require_admin
    def get(self, user_id):
        """Get MFA status for a user."""
        user = models.User.get_by_id_and_org(user_id, self.current_org)
        
        mfa_config = models.MFAConfig.query.filter_by(user_id=user.id).first()
        
        if not mfa_config or not mfa_config.is_enabled:
            return {
                'mfa_enabled': False,
                'user_id': user.id,
                'user_name': user.name,
                'user_email': user.email
            }
        
        # Get backup codes count
        backup_codes_count = models.MFABackupCode.query.filter_by(
            user_id=user.id,
            is_used=False
        ).count()
        
        return {
            'mfa_enabled': True,
            'user_id': user.id,
            'user_name': user.name,
            'user_email': user.email,
            'phone_number_masked': mfa_config.get_masked_phone(),
            'enrolled_at': mfa_config.enrolled_at.isoformat() if mfa_config.enrolled_at else None,
            'last_used_at': mfa_config.last_used_at.isoformat() if mfa_config.last_used_at else None,
            'backup_codes_remaining': backup_codes_count
        }
    
    @require_admin
    def delete(self, user_id):
        """Disable MFA for a user (admin action)."""
        user = models.User.get_by_id_and_org(user_id, self.current_org)
        
        # Check if user has MFA enabled
        if not MFAService.is_enrolled(user):
            abort(400, message="User does not have MFA enabled.")
        
        # Get reason from request body (optional)
        req = request.get_json(silent=True) or {}
        reason = req.get('reason', 'Admin disabled MFA')
        
        # Disable MFA
        try:
            MFAService.disable_mfa(user, admin_user=self.current_user)
            
            # Log the admin action
            MFAAuditService.log_mfa_disabled(
                user=user,
                admin_user=self.current_user,
                reason=reason
            )
            
            # Send notification email to user
            try:
                from redash.authentication.account import send_mail
                
                subject = "Your MFA has been disabled"
                html = """
                <p>Hello {user_name},</p>
                
                <p>Your Multi-Factor Authentication (MFA) has been disabled by an administrator.</p>
                
                <p><strong>Details:</strong></p>
                <ul>
                    <li>Disabled by: {admin_name} ({admin_email})</li>
                    <li>Reason: {reason}</li>
                    <li>Date: {date}</li>
                </ul>
                
                <p>If you did not request this change or have concerns about your account security, 
                please contact your administrator immediately.</p>
                
                <p>You will need to re-enroll in MFA before accessing privileged features.</p>
                
                <p>Best regards,<br>
                TableScope Security Team</p>
                """.format(
                    user_name=user.name,
                    admin_name=self.current_user.name,
                    admin_email=self.current_user.email,
                    reason=reason,
                    date=time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
                )
                
                send_mail([user.email], subject, html)
            except Exception as e:
                # Log error but don't fail the request
                import logging
                logger = logging.getLogger(__name__)
                logger.error("Failed to send MFA disabled notification email: {}".format(str(e)))
            
            self.record_event({
                'action': 'disable_mfa',
                'object_id': user.id,
                'object_type': 'user',
                'admin_id': self.current_user.id,
                'reason': reason
            })
            
            return {
                'success': True,
                'message': 'MFA disabled successfully for user {}'.format(user.name),
                'user_id': user.id,
                'mfa_enabled': False
            }
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error("Failed to disable MFA for user {}: {}".format(user.id, str(e)))
            abort(500, message="Failed to disable MFA: {}".format(str(e)))
