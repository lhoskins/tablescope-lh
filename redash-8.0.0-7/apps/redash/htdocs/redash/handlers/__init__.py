import os
from flask import jsonify, Blueprint, send_from_directory, render_template
from flask_login import login_required
from werkzeug.exceptions import NotFound

from redash.handlers.api import api
from redash.handlers.base import routes
from redash.monitor import get_status
from redash.permissions import require_super_admin
from redash.security import talisman

# Path to the Vite build output
TABLESCOPE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '../../client/tablescope')
)

# Path to the templates directory
TEMPLATES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '../../redash/templates')
)

@routes.route('/ping', methods=['GET'])
@talisman(force_https=False)
def ping():
    return 'PONG.'

@routes.route('/status.json')
@login_required
@require_super_admin
def status_api():
    status = get_status()
    return jsonify(status)

# Define the Blueprint for the tablescope app
tablescope_blueprint = Blueprint(
    'tablescope',
    __name__,
    static_folder=TABLESCOPE_DIR,  # Serve static assets from Vite's output
    template_folder=TEMPLATES_DIR  # Explicitly define the template folder
)

@tablescope_blueprint.route('/<org_slug>/tablescope')
def serve_tablescope_with_redash(org_slug):
    """
    Render the template wrapping the Vite app with the Redash header and sidebar.
    """
    return render_template('tablescope_wrapper.html', vite_base_path='/development/tablescope/')

@tablescope_blueprint.route('/<org_slug>/tablescope/<path:path>')
def serve_tablescope_static(org_slug, path):
    """
    Serve static files (e.g., JS, CSS, images) for the tablescope app.
    """
    try:
        return send_from_directory(TABLESCOPE_DIR, path)
    except NotFound:
        return "File '{}' not found in '{}'.".format(path, TABLESCOPE_DIR), 404

def init_app(app):
    """
    Initialize the Flask app with custom routes and blueprints.
    """
    import logging
    from flask import request as flask_request
    
    logger = logging.getLogger(__name__)
    
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
        logger.info('=' * 80)
    
    # Import all handler modules BEFORE registering blueprints
    # This ensures all @routes.route() decorators are executed
    logger.info('Importing handler modules...')
    from redash.handlers import embed, queries, static, authentication, admin, setup, organization, admin_organizations, file_upload, organization_vdb, teiid_config, profile
    from redash.handlers.admin import organization_provisioning
    logger.info('Successfully imported organization_provisioning module')
    
    # Now register the blueprints (routes should be attached by now)
    logger.info('Registering blueprints...')
    app.register_blueprint(routes)  # Register the base routes
    logger.info('Registered routes blueprint')
    app.register_blueprint(tablescope_blueprint)  # Register the tablescope blueprint
    logger.info('Registered tablescope blueprint')
    api.init_app(app)
    logger.info('Initialized API')
    
    # Log all registered routes after initialization
    logger.info('=' * 80)
    logger.info('REGISTERED ROUTES:')
    provisioning_routes_found = False
    for rule in app.url_map.iter_rules():
        methods = ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
        rule_str = str(rule.rule)
        
        # Highlight provisioning routes
        if 'provision' in rule_str.lower():
            logger.info('  *** PROVISIONING ROUTE: {} -> {} [{}]'.format(rule_str, rule.endpoint, methods))
            provisioning_routes_found = True
        elif 'vdb' in rule_str.lower():
            logger.info('  *** VDB ROUTE: {} -> {} [{}]'.format(rule_str, rule.endpoint, methods))
        else:
            logger.info('  {} -> {} [{}]'.format(rule_str, rule.endpoint, methods))
    
    if not provisioning_routes_found:
        logger.error('*** WARNING: No provisioning routes found in registered routes! ***')
        logger.error('*** This will cause HTTP 405 errors for provisioning endpoints ***')
    else:
        logger.info('*** Provisioning routes successfully registered ***')
    
    logger.info('=' * 80)
