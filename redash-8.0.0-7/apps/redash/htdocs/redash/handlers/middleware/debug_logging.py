"""
Debug logging middleware for tracing requests.

This middleware logs all incoming requests to help diagnose routing issues.
"""

import logging
from flask import request

logger = logging.getLogger(__name__)


class DebugLoggingMiddleware:
    """
    Middleware to log all incoming requests for debugging.
    """
    
    def __init__(self, app):
        self.app = app
        
    def __call__(self, environ, start_response):
        # Log the incoming request
        method = environ.get('REQUEST_METHOD', 'UNKNOWN')
        path = environ.get('PATH_INFO', 'UNKNOWN')
        query = environ.get('QUERY_STRING', '')
        
        logger.info('=' * 80)
        logger.info('INCOMING REQUEST:')
        logger.info('  Method: {}'.format(method))
        logger.info('  Path: {}'.format(path))
        logger.info('  Query: {}'.format(query))
        logger.info('  Content-Type: {}'.format(environ.get('CONTENT_TYPE', 'N/A')))
        logger.info('  User-Agent: {}'.format(environ.get('HTTP_USER_AGENT', 'N/A')))
        
        # Log authorization header (masked)
        auth = environ.get('HTTP_AUTHORIZATION', 'N/A')
        if auth and auth != 'N/A':
            logger.info('  Authorization: {}...'.format(auth[:20]))
        else:
            logger.info('  Authorization: {}'.format(auth))
        
        logger.info('=' * 80)
        
        # Call the actual application
        return self.app(environ, start_response)


def init_debug_logging(app):
    """
    Initialize debug logging middleware.
    
    Args:
        app: Flask application instance
    """
    logger.info('Initializing debug logging middleware')
    app.wsgi_app = DebugLoggingMiddleware(app.wsgi_app)
    logger.info('Debug logging middleware initialized')
