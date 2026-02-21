import time
import logging

from inspect import isclass
from flask import Blueprint, current_app, request, session, redirect, url_for, flash

from flask_login import current_user, login_required
from flask_restful import Resource, abort
from redash import settings
from redash.authentication import current_org
from redash.models import db
from redash.tasks import record_event as record_event_task
from redash.utils import json_dumps
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import cast
from sqlalchemy.dialects import postgresql
from sqlalchemy_utils import sort_query

logger = logging.getLogger(__name__)

routes = Blueprint('redash', __name__, template_folder=settings.fix_assets_path('templates'))


# MFA enforcement is handled in the login flow (authentication.py)
# and in the BaseResource dispatch_request for API protection


class BaseResource(Resource):
    decorators = [login_required]

    def __init__(self, *args, **kwargs):
        super(BaseResource, self).__init__(*args, **kwargs)
        self._user = None

    def dispatch_request(self, *args, **kwargs):
        kwargs.pop('org_slug', None)
        
        # Check MFA requirement for authenticated users
        if current_user.is_authenticated and not current_user.is_api_user():
            from redash.services.mfa_service import MFAService
            
            # Exempt MFA-related endpoints from MFA checks (they need to work during enrollment/verification)
            mfa_exempt_endpoints = [
                'mfa_enroll',
                'mfa_enroll_verify',
                'mfa_enroll_status',
                'mfa_verify',
                'mfa_resend',
                'mfa_settings',
                'mfa_backup_codes'
            ]
            
            # Skip MFA check for MFA-related endpoints
            if request.endpoint not in mfa_exempt_endpoints:
                # Check if MFA enrollment is pending (set during password setup flow)
                # This flag is set when a privileged user completes password setup but hasn't enrolled in MFA yet
                if session.get('mfa_enrollment_required'):
                    org_slug = current_org.slug if current_org else None
                    redirect_url = url_for('redash.mfa_enroll', org_slug=org_slug) if org_slug else '/mfa/enroll'
                    logger.warning("[MFA] User {} has pending MFA enrollment - blocking API access to {}".format(
                        current_user.id, request.endpoint
                    ))
                    abort(403, message="MFA enrollment required. Please complete MFA enrollment to access this resource.", 
                          redirect=redirect_url)
                
                # Check if MFA is required for this user
                if MFAService.is_mfa_required(current_user):
                    # Check if user is enrolled
                    if not MFAService.is_enrolled(current_user):
                        # User needs to enroll - block API access
                        org_slug = current_org.slug if current_org else None
                        redirect_url = url_for('redash.mfa_enroll', org_slug=org_slug) if org_slug else '/mfa/enroll'
                        logger.warning("[MFA] User {} requires MFA but is not enrolled - blocking API access to {}".format(
                            current_user.id, request.endpoint
                        ))
                        abort(403, message="MFA enrollment required. Please complete enrollment before accessing the application.",
                              redirect=redirect_url)
                    
                    # Check if session is MFA-verified
                    if not session.get('mfa_verified', False):
                        org_slug = current_org.slug if current_org else None
                        redirect_url = url_for('redash.mfa_challenge', org_slug=org_slug) if org_slug else '/mfa/challenge'
                        logger.warning("[MFA] User {} requires MFA but session not verified - blocking API access to {}".format(
                            current_user.id, request.endpoint
                        ))
                        abort(403, message="MFA verification required. Please complete MFA challenge.",
                              redirect=redirect_url)

        return super(BaseResource, self).dispatch_request(*args, **kwargs)

    @property
    def current_user(self):
        return current_user._get_current_object()

    @property
    def current_org(self):
        return current_org._get_current_object()

    def record_event(self, options):
        record_event(self.current_org, self.current_user, options)

    # TODO: this should probably be somewhere else
    def update_model(self, model, updates):
        for k, v in updates.items():
            setattr(model, k, v)


def record_event(org, user, options):
    if user.is_api_user():
        options.update({
            'api_key': user.name,
            'org_id': org.id
        })
    else:
        options.update({
            'user_id': user.id,
            'user_name': user.name,
            'org_id': org.id
        })

    options.update({
        'user_agent': request.user_agent.string,
        'ip': request.remote_addr
    })

    if 'timestamp' not in options:
        options['timestamp'] = int(time.time())

    record_event_task.delay(options)


def require_fields(req, fields):
    for f in fields:
        if f not in req:
            abort(400)


def get_object_or_404(fn, *args, **kwargs):
    try:
        rv = fn(*args, **kwargs)
        if rv is None:
            abort(404)
    except NoResultFound:
        abort(404)
    return rv


def paginate(query_set, page, page_size, serializer, **kwargs):
    count = query_set.count()

    if page < 1:
        abort(400, message='Page must be positive integer.')

    if (page - 1) * page_size + 1 > count > 0:
        abort(400, message='Page is out of range.')

    if page_size > 250 or page_size < 1:
        abort(400, message='Page size is out of range (1-250).')

    results = query_set.paginate(page, page_size)

    # support for old function based serializers
    if isclass(serializer):
        items = serializer(results.items, **kwargs).serialize()
    else:
        items = [serializer(result) for result in results.items]

    return {
        'count': count,
        'page': page,
        'page_size': page_size,
        'results': items,
    }


def org_scoped_rule(rule):
    if settings.MULTI_ORG:
        return "/<org_slug>{}".format(rule)

    return rule


def json_response(response):
    return current_app.response_class(json_dumps(response), mimetype='application/json')


def filter_by_tags(result_set, column):
    if request.args.getlist('tags'):
        tags = request.args.getlist('tags')
        result_set = result_set.filter(cast(column, postgresql.ARRAY(db.Text)).contains(tags))
    return result_set


def order_results(results, default_order, allowed_orders, fallback=True):
    """
    Orders the given results with the sort order as requested in the
    "order" request query parameter or the given default order.
    """
    # See if a particular order has been requested
    requested_order = request.args.get('order', '').strip()

    # and if not (and no fallback is wanted) return results as is
    if not requested_order and not fallback:
        return results

    # and if it matches a long-form for related fields, falling
    # back to the default order
    selected_order = allowed_orders.get(requested_order, None)
    if selected_order is None and fallback:
        selected_order = default_order
    # The query may already have an ORDER BY statement attached
    # so we clear it here and apply the selected order
    return sort_query(results.order_by(None), selected_order)
