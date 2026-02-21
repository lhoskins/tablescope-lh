import logging
from datetime import datetime

from flask import abort, flash, redirect, render_template, request, url_for, session

from flask_login import current_user, login_required, login_user, logout_user
from redash import __version__, limiter, models, settings
from redash.authentication import current_org, get_login_url, get_next_path
from redash.authentication.account import (BadSignature, SignatureExpired,
                                           send_password_reset_email,
                                           send_user_disabled_email,
                                           send_verify_email,
                                           validate_token)
from redash.handlers import routes
from redash.handlers.base import json_response, org_scoped_rule
from redash.version_check import get_latest_version
from redash.services.mfa_service import MFAService
from redash.services.sms_service import SMSService
from redash.handlers.mfa import generate_temp_token
from sqlalchemy.orm.exc import NoResultFound

logger = logging.getLogger(__name__)


def is_session_mfa_verified():
    """
    Check if current session is MFA-verified (Requirement 12.2).
    Returns True if session has valid MFA verification.
    """
    return session.get('mfa_verified', False)


def require_mfa_verification():
    """
    Check if current user requires MFA and if session is verified (Requirement 12.6).
    If user has privileged role but session is not MFA-verified, redirect to MFA challenge.
    """
    if not current_user.is_authenticated:
        return False
    
    # Check if user requires MFA
    if MFAService.is_mfa_required(current_user):
        # Check if user is enrolled
        if not MFAService.is_enrolled(current_user):
            # Redirect to enrollment
            session['mfa_enrollment_required'] = True
            return False
        
        # Check if session is MFA-verified
        if not is_session_mfa_verified():
            # Session not verified - need to challenge
            return False
    
    return True


def initiate_mfa_challenge(user, org_slug, next_path=None):
    """
    Initiate MFA challenge for a user by generating OTP and sending via SMS.
    
    This is a reusable helper function that can be called from both the login
    handler and the password setup flow (Requirements 1.5, 4.4).
    
    Args:
        user: User object
        org_slug: Organization slug for URL generation
        next_path: Optional redirect path after successful verification
        
    Returns:
        Response: Redirect to MFA challenge page or login page on error
    """
    try:
        # Generate and send OTP
        otp = MFAService.generate_otp(user)
        config = models.MFAConfig.query.filter_by(user_id=user.id).first()
        
        if not config:
            logger.error("MFA config not found for enrolled user {}".format(user.id))
            flash("MFA configuration error. Please contact support.")
            return redirect(url_for('redash.login', org_slug=org_slug))
        
        SMSService.send_otp(config.phone_number, otp, user=user)
        
        # Create temporary session token for MFA challenge
        temp_token = generate_temp_token(user.id)
        session['mfa_temp_token'] = temp_token
        session['mfa_phone_last4'] = config.get_masked_phone()[-4:]
        session['mfa_org_slug'] = org_slug
        session['mfa_next_path'] = next_path or url_for('redash.index', org_slug=org_slug)
        
        logger.info("MFA challenge initiated for user {} (from helper)".format(user.id))
        return redirect(url_for('redash.mfa_challenge', org_slug=org_slug))
        
    except Exception as e:
        logger.error("Failed to initiate MFA challenge for user {}: {}".format(user.id, str(e)))
        flash("Failed to send verification code. Please try again or contact support.")
        return redirect(url_for('redash.login', org_slug=org_slug))


def get_google_auth_url(next_path):
    if settings.MULTI_ORG:
        google_auth_url = url_for('google_oauth.authorize_org', next=next_path, org_slug=current_org.slug)
    else:
        google_auth_url = url_for('google_oauth.authorize', next=next_path)
    return google_auth_url


def render_token_login_page(template, org_slug, token, invite):
    try:
        user_id = validate_token(token)
        org = current_org._get_current_object()
        user = models.User.get_by_id_and_org(user_id, org)
    except NoResultFound:
        logger.exception("Bad user id in token. Token= , User id= %s, Org=%s", user_id, token, org_slug)
        return render_template("error.html", error_message="Invalid invite link. Please ask for a new one."), 400
    except (SignatureExpired, BadSignature):
        logger.exception("Failed to verify invite token: %s, org=%s", token, org_slug)
        return render_template("error.html",
                               error_message="Your invite link has expired. Please ask for a new one."), 400

    if invite and user.details.get('is_invitation_pending') is False:
        return render_template("error.html",
                               error_message=("This invitation has already been accepted. "
                                              "Please try resetting your password instead.")), 400

    status_code = 200
    if request.method == 'POST':
        if 'password' not in request.form:
            flash('Bad Request')
            status_code = 400
        elif not request.form['password']:
            flash('Cannot use empty password.')
            status_code = 400
        elif len(request.form['password']) < 6:
            flash('Password length is too short (<6).')
            status_code = 400
        else:
            if invite:
                user.is_invitation_pending = False
            user.hash_password(request.form['password'])
            models.db.session.add(user)
            login_user(user)
            models.db.session.commit()
            
            # Check MFA requirement after password setup (Requirements 1.1, 1.2, 1.3, 2.1, 2.3)
            logger.info("[MFA] Checking MFA requirement for user {} after password setup".format(user.id))
            
            if MFAService.is_mfa_required(user):
                logger.info("[MFA] User {} requires MFA".format(user.id))
                
                if not MFAService.is_enrolled(user):
                    # User needs to enroll in MFA first (Requirement 1.2)
                    logger.info("[MFA] User {} not enrolled, redirecting to enrollment".format(user.id))
                    session['mfa_enrollment_required'] = True
                    return redirect(url_for('redash.mfa_enroll', org_slug=org_slug))
                else:
                    # User is enrolled - initiate MFA challenge (Requirement 1.3)
                    logger.info("[MFA] User {} enrolled, initiating MFA challenge".format(user.id))
                    return initiate_mfa_challenge(user, org_slug, url_for('redash.index', org_slug=org_slug))
            else:
                # Non-privileged user - mark session as MFA-verified and proceed (Requirement 2.3)
                logger.info("[MFA] User {} does not require MFA, granting access".format(user.id))
                session['mfa_verified'] = True
                session['mfa_verified_at'] = datetime.utcnow().isoformat()
                return redirect(url_for('redash.index', org_slug=org_slug))

    google_auth_url = get_google_auth_url(url_for('redash.index', org_slug=org_slug))

    return render_template(template,
                           show_google_openid=settings.GOOGLE_OAUTH_ENABLED,
                           google_auth_url=google_auth_url,
                           show_saml_login=current_org.get_setting('auth_saml_enabled'),
                           show_remote_user_login=settings.REMOTE_USER_LOGIN_ENABLED,
                           show_ldap_login=settings.LDAP_LOGIN_ENABLED,
                           org_slug=org_slug,
                           user=user), status_code


@routes.route(org_scoped_rule('/invite/<token>'), methods=['GET', 'POST'])
def invite(token, org_slug=None):
    return render_token_login_page("invite.html", org_slug, token, True)


@routes.route(org_scoped_rule('/reset/<token>'), methods=['GET', 'POST'])
def reset(token, org_slug=None):
    return render_token_login_page("reset.html", org_slug, token, False)


@routes.route(org_scoped_rule('/verify/<token>'), methods=['GET'])
def verify(token, org_slug=None):
    try:
        user_id = validate_token(token)
        org = current_org._get_current_object()
        user = models.User.get_by_id_and_org(user_id, org)
    except (BadSignature, NoResultFound):
        logger.exception("Failed to verify email verification token: %s, org=%s", token, org_slug)
        return render_template("error.html",
                               error_message="Your verification link is invalid. Please ask for a new one."), 400

    user.is_email_verified = True
    models.db.session.add(user)
    models.db.session.commit()

    template_context = {"org_slug": org_slug} if settings.MULTI_ORG else {}
    next_url = url_for('redash.index', **template_context)

    return render_template("verify.html", next_url=next_url)


@routes.route(org_scoped_rule('/forgot'), methods=['GET', 'POST'])
def forgot_password(org_slug=None):
    if not current_org.get_setting('auth_password_login_enabled'):
        abort(404)

    submitted = False
    if request.method == 'POST' and request.form['email']:
        submitted = True
        email = request.form['email']
        try:
            org = current_org._get_current_object()
            user = models.User.get_by_email_and_org(email, org)
            if user.is_disabled:
                send_user_disabled_email(user)
            else:
                send_password_reset_email(user)
        except NoResultFound:
            logging.error("No user found for forgot password: %s", email)

    return render_template("forgot.html", submitted=submitted)


@routes.route(org_scoped_rule('/verification_email/'), methods=['POST'])
def verification_email(org_slug=None):
    if not current_user.is_email_verified:
        send_verify_email(current_user, current_org)

    return json_response({
        "message": "Please check your email inbox in order to verify your email address."
    })


@routes.route(org_scoped_rule('/login'), methods=['GET', 'POST'])
@limiter.limit(settings.THROTTLE_LOGIN_PATTERN)
def login(org_slug=None):
    # We intentionally use == as otherwise it won't actually use the proxy. So weird :O
    # noinspection PyComparisonWithNone
    if current_org == None and not settings.MULTI_ORG:
        return redirect('/setup')
    elif current_org == None:
        return redirect('/')

    index_url = url_for('redash.index', org_slug=org_slug)
    unsafe_next_path = request.args.get('next', index_url)
    next_path = get_next_path(unsafe_next_path)
    if current_user.is_authenticated:
        return redirect(next_path)

    if request.method == 'POST':
        try:
            org = current_org._get_current_object()
            user = models.User.get_by_email_and_org(request.form['email'], org)
            if user and not user.is_disabled and user.verify_password(request.form['password']):
                # Check if MFA is required for this user
                logger.info("[MFA] Checking MFA requirement for user {} (email: {})".format(user.id, user.email))
                is_mfa_required = MFAService.is_mfa_required(user)
                logger.info("[MFA] MFA required for user {}: {}".format(user.id, is_mfa_required))
                
                if is_mfa_required:
                    # Check if user is enrolled in MFA
                    is_enrolled = MFAService.is_enrolled(user)
                    logger.info("[MFA] User {} enrolled: {}".format(user.id, is_enrolled))
                    
                    if not is_enrolled:
                        # User needs to enroll in MFA - log them in first (Requirement 1.9)
                        remember = ('remember' in request.form)
                        login_user(user, remember=remember)
                        session['mfa_enrollment_required'] = True
                        return redirect(url_for('redash.mfa_enroll', org_slug=org_slug))
                    
                    # Check if session is already MFA-verified for this user (Requirement 12.2)
                    # This prevents requiring MFA again during the same session
                    if is_session_mfa_verified() and current_user.is_authenticated and current_user.id == user.id:
                        logger.info("User {} already MFA-verified in this session, skipping challenge".format(user.id))
                        remember = ('remember' in request.form)
                        login_user(user, remember=remember)
                        return redirect(next_path)
                    
                    # User is enrolled - initiate MFA challenge using helper function
                    return initiate_mfa_challenge(user, org_slug, next_path)
                
                # Non-privileged user or MFA not required - complete login
                remember = ('remember' in request.form)
                login_user(user, remember=remember)
                
                # Mark session as verified (no MFA required for this user)
                session['mfa_verified'] = True
                session['mfa_verified_at'] = datetime.utcnow().isoformat()
                
                return redirect(next_path)
            else:
                flash("Wrong email or password.")
        except NoResultFound:
            flash("Wrong email or password.")

    google_auth_url = get_google_auth_url(next_path)

    return render_template("login.html",
                           org_slug=org_slug,
                           next=next_path,
                           email=request.form.get('email', ''),
                           show_google_openid=settings.GOOGLE_OAUTH_ENABLED,
                           google_auth_url=google_auth_url,
                           show_password_login=current_org.get_setting('auth_password_login_enabled'),
                           show_saml_login=current_org.get_setting('auth_saml_enabled'),
                           show_remote_user_login=settings.REMOTE_USER_LOGIN_ENABLED,
                           show_ldap_login=settings.LDAP_LOGIN_ENABLED)


@routes.route(org_scoped_rule('/logout'))
def logout(org_slug=None):
    # Clear all MFA session state consistently (Requirements 2.2, 3.4, 12.4)
    # This ensures no MFA-related session data persists after logout
    mfa_session_keys = [
        'mfa_verified',
        'mfa_verified_at',
        'mfa_temp_token',
        'mfa_phone_last4',
        'mfa_enrollment_required',
        'mfa_org_slug',
        'mfa_next_path',
        'pending_user_id',
    ]
    for key in mfa_session_keys:
        session.pop(key, None)
    
    logout_user()
    return redirect(get_login_url(next=None))


@routes.route(org_scoped_rule('/mfa/challenge'), methods=['GET'])
def mfa_challenge(org_slug=None):
    """
    Display MFA challenge page for OTP entry.
    
    Session validation ensures users cannot access this page without proper state
    (Requirements 3.4, 4.2).
    """
    temp_token = session.get('mfa_temp_token')
    phone_last4 = session.get('mfa_phone_last4')
    
    # Validate session has required MFA challenge state (Requirement 3.4)
    if not temp_token:
        logger.warning("[MFA Challenge] No temp token in session, redirecting to login")
        flash("Session expired. Please log in again.")
        return redirect(url_for('redash.login', org_slug=org_slug))
    
    # Validate the temp token is still valid in Redis (Requirement 4.2)
    from redash.handlers.mfa import validate_temp_token
    user = validate_temp_token(temp_token)
    if not user:
        logger.warning("[MFA Challenge] Temp token invalid or expired, clearing session and redirecting to login")
        # Clear stale MFA session data
        session.pop('mfa_temp_token', None)
        session.pop('mfa_phone_last4', None)
        session.pop('mfa_org_slug', None)
        session.pop('mfa_next_path', None)
        flash("Session expired. Please log in again.")
        return redirect(url_for('redash.login', org_slug=org_slug))
    
    return render_template("mfa_challenge.html",
                          org_slug=org_slug,
                          temp_token=temp_token,
                          phone_last4=phone_last4)


@routes.route(org_scoped_rule('/mfa/enroll'), methods=['GET'])
def mfa_enroll(org_slug=None):
    """
    Display MFA enrollment page.
    
    Session validation ensures users cannot access this page without proper state
    (Requirements 3.4, 4.2).
    """
    # Validate user is authenticated (Requirement 3.4)
    if not current_user.is_authenticated:
        logger.warning("[MFA Enroll] Unauthenticated user attempted to access enrollment page")
        flash("Please log in to continue.")
        return redirect(url_for('redash.login', org_slug=org_slug))
    
    # Check if enrollment is required via session flag (Requirement 4.2)
    if not session.get('mfa_enrollment_required'):
        # Double-check if user actually needs MFA enrollment
        # This handles cases where session flag might be missing but user still needs enrollment
        if MFAService.is_mfa_required(current_user) and not MFAService.is_enrolled(current_user):
            # User needs enrollment but flag wasn't set - set it now
            logger.info("[MFA Enroll] Setting mfa_enrollment_required flag for user {}".format(current_user.id))
            session['mfa_enrollment_required'] = True
        else:
            # User doesn't need enrollment - redirect to main app
            logger.info("[MFA Enroll] User {} does not require enrollment, redirecting to index".format(current_user.id))
            return redirect(url_for('redash.index', org_slug=org_slug))
    
    # Verify user still requires MFA (in case group membership changed)
    if not MFAService.is_mfa_required(current_user):
        logger.info("[MFA Enroll] User {} no longer requires MFA, clearing flag and redirecting".format(current_user.id))
        session.pop('mfa_enrollment_required', None)
        session['mfa_verified'] = True
        session['mfa_verified_at'] = datetime.utcnow().isoformat()
        return redirect(url_for('redash.index', org_slug=org_slug))
    
    # Check if user is already enrolled (shouldn't happen but handle gracefully)
    if MFAService.is_enrolled(current_user):
        logger.info("[MFA Enroll] User {} is already enrolled, redirecting to MFA challenge".format(current_user.id))
        session.pop('mfa_enrollment_required', None)
        return initiate_mfa_challenge(current_user, org_slug, url_for('redash.index', org_slug=org_slug))
    
    return render_template("mfa_enroll.html", org_slug=org_slug)


def base_href():
    if settings.MULTI_ORG:
        base_href = url_for('redash.index', _external=True, org_slug=current_org.slug)
    else:
        base_href = url_for('redash.index', _external=True)

    return base_href


def date_time_format_config():
    date_format = current_org.get_setting('date_format')
    date_format_list = set(["DD/MM/YY", "MM/DD/YY", "YYYY-MM-DD", settings.DATE_FORMAT])
    time_format = current_org.get_setting('time_format')
    time_format_list = set(["HH:mm", "HH:mm:ss", "HH:mm:ss.SSS", settings.TIME_FORMAT])
    return {
        'dateFormat': date_format,
        'dateFormatList': list(date_format_list),
        'timeFormatList': list(time_format_list),
        'dateTimeFormat': "{0} {1}".format(date_format, time_format),
    }


def number_format_config():
    return {
        'integerFormat': current_org.get_setting('integer_format'),
        'floatFormat': current_org.get_setting('float_format'),
    }


def client_config():
    if not current_user.is_api_user() and current_user.is_authenticated:
        client_config = {
            'newVersionAvailable': bool(get_latest_version()),
            'version': __version__
        }
    else:
        client_config = {}
 
    if current_user.has_permission('admin') and current_org.get_setting('beacon_consent') is None:
        client_config['showBeaconConsentMessage'] = True

    defaults = {
        'allowScriptsInUserInput': settings.ALLOW_SCRIPTS_IN_USER_INPUT,
        'showPermissionsControl': current_org.get_setting("feature_show_permissions_control"),
        'allowCustomJSVisualizations': settings.FEATURE_ALLOW_CUSTOM_JS_VISUALIZATIONS,
        'autoPublishNamedQueries': settings.FEATURE_AUTO_PUBLISH_NAMED_QUERIES,
        'extendedAlertOptions': settings.FEATURE_EXTENDED_ALERT_OPTIONS,
        'mailSettingsMissing': not settings.email_server_is_configured(),
        'dashboardRefreshIntervals': settings.DASHBOARD_REFRESH_INTERVALS,
        'queryRefreshIntervals': settings.QUERY_REFRESH_INTERVALS,
        'googleLoginEnabled': settings.GOOGLE_OAUTH_ENABLED,
        'pageSize': settings.PAGE_SIZE,
        'pageSizeOptions': settings.PAGE_SIZE_OPTIONS,
        'tableCellMaxJSONSize': settings.TABLE_CELL_MAX_JSON_SIZE,
    }

    client_config.update(defaults)
    client_config.update({
        'basePath': base_href()
    })
    client_config.update(date_time_format_config())
    client_config.update(number_format_config())

    return client_config


def messages():
    messages = []

    if not current_user.is_email_verified:
        messages.append('email-not-verified')

    if settings.ALLOW_PARAMETERS_IN_EMBEDS:
        messages.append('using-deprecated-embed-feature')

    return messages


@routes.route('/api/config', methods=['GET'])
def config(org_slug=None):
    return json_response({
        'org_slug': current_org.slug,
        'client_config': client_config()
    })


@routes.route(org_scoped_rule('/api/session'), methods=['GET'])
@login_required
def session_info(org_slug=None):
    if current_user.is_api_user():
        user = {
            'permissions': [],
            'apiKey': current_user.id
        }
    else:
        user = {
            'profile_image_url': current_user.profile_image_url,
            'id': current_user.id,
            'name': current_user.name,
            'email': current_user.email,
            'groups': current_user.group_ids,
            'permissions': current_user.permissions
        }

    return json_response({
        'user': user,
        'messages': messages(),
        'org_slug': current_org.slug,
        'org_id': current_org.id,
        'org_name': current_org.name,
        'client_config': client_config(),
        'mfa_verified': is_session_mfa_verified()  # Include MFA verification status
    })
