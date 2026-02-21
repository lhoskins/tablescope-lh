"""
Teiid Configuration API

Handles one-time setup and management of Teiid environment configuration.
"""

import logging
from flask import request
from flask_login import login_required
from redash.handlers import routes
from redash.handlers.base import json_response, org_scoped_rule
from redash.permissions import require_super_admin
from redash import models

logger = logging.getLogger(__name__)


@routes.route(org_scoped_rule('/api/admin/teiid-config'), methods=['GET'])
@require_super_admin
@login_required
def get_teiid_config(org_slug=None):
    """
    Get current Teiid configuration.
    
    Response:
        {
            "id": 1,
            "servlet_url": "http://localhost:8095/TeiidExcelImporterTest/vdb-management",
            "servlet_api_key": "***",  # Masked
            "teiid_host": "localhost",
            "teiid_port": 31020,
            "teiid_use_ssl": true,
            "customer_base_path": "/opt/wildfly/teiidfiles/customers",
            "vdb_base_path": "/opt/wildfly/teiidfiles",
            "template_vdb_name": "MyVDBTest",
            "vdb_enabled": true,
            "created_at": "2025-11-15T10:00:00",
            "updated_at": "2025-11-15T10:00:00"
        }
    """
    try:
        # Query teiid_config table
        result = models.db.session.execute(
            """
            SELECT 
                id, servlet_url, servlet_api_key, teiid_host, teiid_port, 
                teiid_use_ssl, customer_base_path, vdb_base_path, 
                template_vdb_name, vdb_enabled, created_at, updated_at
            FROM teiid_config 
            WHERE id = 1
            """
        ).fetchone()
        
        if not result:
            # Return default configuration if not set up yet
            return json_response({
                'configured': False,
                'message': 'Teiid configuration not set up yet. Please configure in Admin UI.',
                'defaults': {
                    'servlet_url': 'http://localhost:8095/TeiidExcelImporterTest/vdb-management',
                    'teiid_host': 'localhost',
                    'teiid_port': 31020,
                    'teiid_use_ssl': True,
                    'customer_base_path': '/opt/wildfly/teiidfiles/customers',
                    'vdb_base_path': '/opt/wildfly/teiidfiles',
                    'template_vdb_name': 'MyVDBTest',
                    'vdb_enabled': True
                }
            })
        
        # Return configuration (mask API key)
        config = {
            'id': result[0],
            'servlet_url': result[1],
            'servlet_api_key': '***' + result[2][-4:] if result[2] and len(result[2]) > 4 else '***',
            'teiid_host': result[3],
            'teiid_port': result[4],
            'teiid_use_ssl': result[5],
            'customer_base_path': result[6],
            'vdb_base_path': result[7],
            'template_vdb_name': result[8],
            'vdb_enabled': result[9],
            'created_at': result[10].isoformat() if result[10] else None,
            'updated_at': result[11].isoformat() if result[11] else None,
            'configured': True
        }
        
        return json_response(config)
        
    except Exception as e:
        logger.error("Failed to get Teiid config: {}".format(str(e)))
        return json_response({
            'error': 'Failed to get Teiid configuration: {}'.format(str(e))
        }, status=500)


@routes.route(org_scoped_rule('/api/admin/teiid-config'), methods=['POST', 'PUT'])
@require_super_admin
@login_required
def update_teiid_config(org_slug=None):
    """
    Update Teiid configuration (one-time setup or update).
    
    Request Body:
        {
            "servlet_url": "http://localhost:8095/TeiidExcelImporterTest/vdb-management",
            "servlet_api_key": "your_api_key",
            "teiid_host": "localhost",
            "teiid_port": 31020,
            "teiid_use_ssl": true,
            "customer_base_path": "/opt/wildfly/teiidfiles/customers",
            "vdb_base_path": "/opt/wildfly/teiidfiles",
            "template_vdb_name": "MyVDBTest",
            "vdb_enabled": true
        }
    
    Response:
        {
            "success": true,
            "message": "Teiid configuration updated successfully",
            "config": { ... }
        }
    """
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['servlet_url', 'servlet_api_key', 'customer_base_path']
        missing_fields = [f for f in required_fields if f not in data]
        
        if missing_fields:
            return json_response({
                'error': 'Missing required fields: {}'.format(', '.join(missing_fields))
            }, status=400)
        
        # Check if configuration exists
        existing = models.db.session.execute(
            "SELECT id FROM teiid_config WHERE id = 1"
        ).fetchone()
        
        if existing:
            # Update existing configuration
            models.db.session.execute(
                """
                UPDATE teiid_config SET
                    servlet_url = :servlet_url,
                    servlet_api_key = :servlet_api_key,
                    teiid_host = :teiid_host,
                    teiid_port = :teiid_port,
                    teiid_use_ssl = :teiid_use_ssl,
                    customer_base_path = :customer_base_path,
                    vdb_base_path = :vdb_base_path,
                    template_vdb_name = :template_vdb_name,
                    vdb_enabled = :vdb_enabled,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                """,
                {
                    'servlet_url': data['servlet_url'],
                    'servlet_api_key': data['servlet_api_key'],
                    'teiid_host': data.get('teiid_host', 'localhost'),
                    'teiid_port': data.get('teiid_port', 31020),
                    'teiid_use_ssl': data.get('teiid_use_ssl', True),
                    'customer_base_path': data['customer_base_path'],
                    'vdb_base_path': data.get('vdb_base_path', '/opt/wildfly/teiidfiles'),
                    'template_vdb_name': data.get('template_vdb_name', 'MyVDBTest'),
                    'vdb_enabled': data.get('vdb_enabled', True)
                }
            )
            message = 'Teiid configuration updated successfully'
        else:
            # Insert new configuration
            models.db.session.execute(
                """
                INSERT INTO teiid_config (
                    id, servlet_url, servlet_api_key, teiid_host, teiid_port,
                    teiid_use_ssl, customer_base_path, vdb_base_path,
                    template_vdb_name, vdb_enabled
                ) VALUES (
                    1, :servlet_url, :servlet_api_key, :teiid_host, :teiid_port,
                    :teiid_use_ssl, :customer_base_path, :vdb_base_path,
                    :template_vdb_name, :vdb_enabled
                )
                """,
                {
                    'servlet_url': data['servlet_url'],
                    'servlet_api_key': data['servlet_api_key'],
                    'teiid_host': data.get('teiid_host', 'localhost'),
                    'teiid_port': data.get('teiid_port', 31020),
                    'teiid_use_ssl': data.get('teiid_use_ssl', True),
                    'customer_base_path': data['customer_base_path'],
                    'vdb_base_path': data.get('vdb_base_path', '/opt/wildfly/teiidfiles'),
                    'template_vdb_name': data.get('template_vdb_name', 'MyVDBTest'),
                    'vdb_enabled': data.get('vdb_enabled', True)
                }
            )
            message = 'Teiid configuration created successfully'
        
        models.db.session.commit()
        
        logger.info("Teiid configuration updated: {}".format(data['servlet_url']))
        
        # Return updated configuration (mask API key)
        return json_response({
            'success': True,
            'message': message,
            'config': {
                'servlet_url': data['servlet_url'],
                'servlet_api_key': '***' + data['servlet_api_key'][-4:] if len(data['servlet_api_key']) > 4 else '***',
                'teiid_host': data.get('teiid_host', 'localhost'),
                'teiid_port': data.get('teiid_port', 31020),
                'teiid_use_ssl': data.get('teiid_use_ssl', True),
                'customer_base_path': data['customer_base_path'],
                'vdb_base_path': data.get('vdb_base_path', '/opt/wildfly/teiidfiles'),
                'template_vdb_name': data.get('template_vdb_name', 'MyVDBTest'),
                'vdb_enabled': data.get('vdb_enabled', True)
            }
        })
        
    except Exception as e:
        models.db.session.rollback()
        logger.error("Failed to update Teiid config: {}".format(str(e)))
        return json_response({
            'error': 'Failed to update Teiid configuration: {}'.format(str(e))
        }, status=500)


@routes.route(org_scoped_rule('/api/admin/teiid-config/test'), methods=['POST'])
@require_super_admin
@login_required
def test_teiid_connection(org_slug=None):
    """
    Test connection to Teiid servlet.
    
    Request Body:
        {
            "servlet_url": "http://localhost:8095/TeiidExcelImporterTest/vdb-management",
            "servlet_api_key": "your_api_key"
        }
    
    Response:
        {
            "success": true,
            "message": "Connection successful",
            "servlet_accessible": true
        }
    """
    try:
        import requests
        
        data = request.get_json()
        servlet_url = data.get('servlet_url')
        api_key = data.get('servlet_api_key')
        
        if not servlet_url or not api_key:
            return json_response({
                'error': 'Missing servlet_url or servlet_api_key'
            }, status=400)
        
        # Test connection to servlet
        response = requests.get(
            servlet_url.rstrip('/') + '/status',
            headers={'X-API-Key': api_key},
            timeout=5
        )
        
        if response.status_code == 200:
            return json_response({
                'success': True,
                'message': 'Connection to Teiid servlet successful',
                'servlet_accessible': True
            })
        else:
            return json_response({
                'success': False,
                'message': 'Servlet returned status code: {}'.format(response.status_code),
                'servlet_accessible': False
            }, status=400)
            
    except requests.exceptions.Timeout:
        return json_response({
            'success': False,
            'message': 'Connection timeout - servlet not accessible',
            'servlet_accessible': False
        }, status=400)
    except requests.exceptions.ConnectionError:
        return json_response({
            'success': False,
            'message': 'Connection error - servlet not accessible',
            'servlet_accessible': False
        }, status=400)
    except Exception as e:
        logger.error("Failed to test Teiid connection: {}".format(str(e)))
        return json_response({
            'success': False,
            'message': 'Failed to test connection: {}'.format(str(e)),
            'servlet_accessible': False
        }, status=500)
