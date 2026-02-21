"""
File Upload Handler - Proxy to Java Servlet

Redash acts as a proxy, forwarding file uploads to the Java servlet
which handles file storage, VDB updates, and deployment.
"""

import os
import logging
import requests
from flask import request
from flask_login import login_required
from werkzeug.utils import secure_filename

from redash.handlers import routes
from redash.handlers.base import json_response, org_scoped_rule
from redash.authentication import current_org

logger = logging.getLogger(__name__)

# Allowed file extensions
ALLOWED_EXTENSIONS = {
    'xlsx', 'xls',  # Excel
    'csv', 'tsv',   # CSV/TSV
    'txt',          # Text
    'json',         # JSON
    'xml'           # XML
}

# Maximum file size (50MB)
MAX_FILE_SIZE = 50 * 1024 * 1024


def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@routes.route(org_scoped_rule('/api/upload'), methods=['POST'])
@login_required
def upload_file_proxy(org_slug=None):
    """
    Proxy file upload to Java servlet.
    
    Redash validates the request and adds org_id from session,
    then forwards everything to the servlet which handles:
    - File storage to customer folder
    - VDB foreign table insertion
    - VDB deployment
    
    Request:
        - file: File to upload (multipart/form-data)
        - replace: 'true' or 'false' (optional)
        
    Response:
        Forwards servlet response
    """
    try:
        logger.info("=== File Upload Proxy Started ===")
        
        # Validate file in request
        if 'file' not in request.files:
            logger.error("No file in request")
            return json_response({'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            logger.error("Empty filename")
            return json_response({'error': 'No file selected'}), 400
        
        # Validate file extension
        if not allowed_file(file.filename):
            logger.error("File type not allowed: {}".format(file.filename))
            return json_response({
                'error': 'File type not allowed. Allowed types: {}'.format(', '.join(ALLOWED_EXTENSIONS))
            }), 400
        
        # Get organization ID from session
        try:
            org_id = current_org.id
            logger.info("Organization ID: {}".format(org_id))
        except Exception as e:
            logger.error("Failed to get organization ID: {}".format(str(e)))
            return json_response({'error': 'Failed to get organization context'}), 500
        
        logger.info("Proxying upload for org {}: {}".format(org_id, file.filename))
        
        # Validate file size
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > MAX_FILE_SIZE:
            return json_response({
                'error': 'File too large. Maximum size: {}MB'.format(MAX_FILE_SIZE / (1024 * 1024))
            }), 400
        
        # Get replace parameter
        replace = request.form.get('replace', 'false').lower() == 'true'
        
        # Forward to Java servlet
        servlet_url = "http://localhost:8095/TeiidExcelImporterTest/upload"
        logger.info("Forwarding to servlet: {}".format(servlet_url))
        
        # Prepare multipart request for servlet
        file.seek(0)  # Reset file pointer
        files = {
            'file': (file.filename, file.stream, file.content_type or 'application/octet-stream')
        }
        data = {
            'replace': 'true' if replace else 'false'
        }
        params = {
            'org_id': str(org_id)
        }
        
        # Call servlet
        servlet_response = requests.post(
            servlet_url,
            files=files,
            data=data,
            params=params,
            timeout=60
        )
        
        logger.info("Servlet response status: {}".format(servlet_response.status_code))
        
        # Forward servlet response to client
        if servlet_response.status_code == 200:
            logger.info("Upload successful via servlet for org {}".format(org_id))
            try:
                return json_response(servlet_response.json()), 200
            except:
                return json_response({'success': True, 'message': servlet_response.text}), 200
                
        elif servlet_response.status_code == 409:
            # Conflict - file already exists
            logger.info("File conflict (409 from servlet)")
            try:
                return json_response(servlet_response.json()), 409
            except:
                return json_response({'error': 'File already exists'}), 409
                
        else:
            logger.error("Servlet failed with status {}: {}".format(
                servlet_response.status_code,
                servlet_response.text
            ))
            return json_response({
                'error': 'Upload failed: {}'.format(servlet_response.text)
            }), servlet_response.status_code
            
    except requests.exceptions.Timeout:
        logger.error("Servlet timeout")
        return json_response({'error': 'Upload timeout - file may be too large or servlet is busy'}), 504
        
    except requests.exceptions.ConnectionError:
        logger.error("Cannot connect to servlet")
        return json_response({'error': 'Upload service unavailable'}), 503
        
    except Exception as e:
        logger.error("Upload proxy failed: {}".format(str(e)))
        import traceback
        logger.error("Traceback: {}".format(traceback.format_exc()))
        return json_response({
            'error': 'Upload failed: {}'.format(str(e))
        }), 500
