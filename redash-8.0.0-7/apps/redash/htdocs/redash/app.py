from flask import Flask
from werkzeug.contrib.fixers import ProxyFix

from . import settings


class Redash(Flask):
    """A custom Flask app for Redash"""
    def __init__(self, *args, **kwargs):
        kwargs.update({
            'template_folder': settings.STATIC_ASSETS_PATH,
            'static_folder': settings.STATIC_ASSETS_PATH,
            'static_path': '/static',
        })
        super(Redash, self).__init__(__name__, *args, **kwargs)
        # Make sure we get the right referral address even behind proxies like nginx.
        self.wsgi_app = ProxyFix(self.wsgi_app, settings.PROXIES_COUNT)
        # Configure Redash using our settings
        self.config.from_object('redash.settings')


def create_app():
    from . import authentication, extensions, handlers, limiter, mail, migrate, security
    from .handlers import chrome_logger
    from .handlers.webpack import configure_webpack
    from .metrics import request as request_metrics
    from .models import db, users
    from .utils import sentry
    from .version_check import reset_new_version_status
    import logging
    from flask import request as flask_request

    logger = logging.getLogger(__name__)

    sentry.init()
    app = Redash()
    
    # Validate VDB configuration and log warnings
    vdb_warnings = settings.validate_vdb_configuration()
    if vdb_warnings:
        logger.warning('=' * 80)
        logger.warning('VDB CONFIGURATION WARNINGS:')
        for warning in vdb_warnings:
            logger.warning('  - {}'.format(warning))
        logger.warning('=' * 80)

    # Add debug logging for all requests
    @app.before_request
    def log_request_info():
        logger.info('=' * 80)
        logger.info('REQUEST DEBUG:')
        logger.info('  Method: {}'.format(flask_request.method))
        logger.info('  URL: {}'.format(flask_request.url))
        logger.info('  Path: {}'.format(flask_request.path))
        logger.info('  Endpoint: {}'.format(flask_request.endpoint))
        logger.info('  View Args: {}'.format(flask_request.view_args))
        logger.info('  Headers: {}'.format(dict(flask_request.headers)))
        logger.info('=' * 80)

    # Check and update the cached version for use by the client
    app.before_first_request(reset_new_version_status)

    security.init_app(app)
    request_metrics.init_app(app)
    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    authentication.init_app(app)
    limiter.init_app(app)
    handlers.init_app(app)
    configure_webpack(app)
    extensions.init_app(app)
    chrome_logger.init_app(app)
    users.init_app(app)

    # Log all registered routes
    logger.info('=' * 80)
    logger.info('REGISTERED ROUTES:')
    for rule in app.url_map.iter_rules():
        methods = ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
        logger.info('  {} -> {} [{}]'.format(rule.rule, rule.endpoint, methods))
    logger.info('=' * 80)

    return app
