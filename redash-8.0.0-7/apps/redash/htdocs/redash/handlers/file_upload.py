"""
File Upload Handler with Customer Folder Support

Handles file uploads to organization-specific folders for data isolation.
"""

import os
import logging
from flask import request
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from redash.handlers import routes
from redash.handlers.base import json_response, org_scoped_rule
from redash.authentication import current_org
from redash import settings
from redash.services.vdb_updater import VDBUpdaterService

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
    """
    Check if file extension is allowed.
    
    Args:
        filename: Name of the file
        
    Returns:
        True if extension is allowed, False otherwise
    """
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@routes.route(org_scoped_rule('/api/upload'), methods=['POST'])
@login_required
def upload_file(org_slug=None):
    """
    Upload file to user-specific folder.
    
    Request:
        - file: File to upload (multipart/form-data)
        
    Response:
        {
            "success": true,
            "filename": "data.xlsx",
            "path": "/opt/wildfly/teiidfiles/customers/1/123/uploads/data.xlsx",
            "org_id": 1,
            "user_id": 123,
            "size": 12345
        }
    """
    try:
        logger.info("=== File Upload Request Started ===")
        
        # Check if file is in request
        if 'file' not in request.files:
            logger.error("No file in request")
            return json_response({'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        # Check if file is selected
        if file.filename == '':
            logger.error("Empty filename")
            return json_response({'error': 'No file selected'}), 400
        
        # Check file extension
        if not allowed_file(file.filename):
            logger.error("File type not allowed: {}".format(file.filename))
            return json_response({
                'error': 'File type not allowed. Allowed types: {}'.format(', '.join(ALLOWED_EXTENSIONS))
            }), 400
        
        # Get organization ID and user ID from current user session
        try:
            org_id = current_org.id
            user_id = current_user.id
            logger.info("Organization ID: {}, User ID: {}".format(org_id, user_id))
        except Exception as e:
            logger.error("Failed to get organization/user context: {}".format(str(e)))
            return json_response({'error': 'Failed to get user context'}), 500
        
        logger.info("File upload request from org {}, user {}: {}".format(org_id, user_id, file.filename))
        
        # Check if upload is for a shared project
        project_id = request.form.get('project_id')
        is_shared_project = False
        
        if project_id:
            try:
                from redash.models.project import Project
                project = Project.query.get(int(project_id))
                
                if project and project.org_id == org_id:
                    # Check if project is shared using the is_shared flag (set during migration)
                    is_shared_project = project.is_shared
                    logger.info("Upload is for project {}: is_shared={} (from project.is_shared flag)".format(project_id, is_shared_project))
                else:
                    logger.warning("Project {} not found or doesn't belong to org {}".format(project_id, org_id))
            except Exception as e:
                logger.error("Failed to check project status: {}".format(str(e)))
                # Continue with private upload if project check fails
        
        # Use CustomerFolderService to ensure folders exist
        from redash.services.customer_folders import CustomerFolderService
        
        folder_service = CustomerFolderService()
        
        # Determine upload folder based on project status
        if is_shared_project:
            # Upload to shared folder for shared projects
            logger.info("Uploading to shared folder for shared project {}".format(project_id))
            
            # Ensure shared folders exist
            if not folder_service.create_shared_folders(org_id):
                logger.error("Failed to create shared folders for org {}".format(org_id))
                return json_response({'error': 'Failed to create shared folders. Please contact administrator.'}), 500
            
            uploads_folder = folder_service.get_shared_uploads_folder(org_id)
            logger.info("Shared uploads folder: {}".format(uploads_folder))
        else:
            # Upload to user's private folder for private projects or no project context
            logger.info("Uploading to user's private folder")
            
            # Ensure user folders exist
            logger.info("Ensuring user folders exist for org {}, user {}".format(org_id, user_id))
            if not folder_service.create_user_folders(org_id, user_id):
                logger.error("Failed to create user folders for org {}, user {}".format(org_id, user_id))
                return json_response({'error': 'Failed to create user folders. Please contact administrator.'}), 500
            
            uploads_folder = folder_service.get_user_uploads_folder(org_id, user_id)
            logger.info("User uploads folder: {}".format(uploads_folder))
        
        # Verify folder is accessible
        if not os.path.exists(uploads_folder):
            logger.error("User uploads folder does not exist: {}".format(uploads_folder))
            return json_response({'error': 'Upload folder does not exist. Please contact administrator.'}), 500
        
        if not os.access(uploads_folder, os.W_OK):
            logger.error("User uploads folder is not writable: {}".format(uploads_folder))
            return json_response({'error': 'Upload folder is not writable. Please contact administrator.'}), 500
        
        # Secure the filename
        filename = secure_filename(file.filename)
        
        # Validate file path to prevent directory traversal attacks
        if not filename or filename == '':
            logger.error("Empty filename after secure_filename")
            return json_response({'error': 'Invalid filename'}), 400
        
        # Additional validation (prevent directory traversal)
        if '..' in filename or '/' in filename or '\\' in filename:
            logger.warning("Invalid file path rejected for org {}, user {}: {}".format(org_id, user_id, filename))
            return json_response({'error': 'Invalid file path'}), 400
        
        # Build full file path
        file_path = os.path.join(uploads_folder, filename)
        
        # Validate that the file path is within the user's uploads folder
        # This prevents directory traversal attacks
        file_path_real = os.path.realpath(file_path)
        uploads_folder_real = os.path.realpath(uploads_folder)
        
        if not file_path_real.startswith(uploads_folder_real):
            logger.error("Security violation: file path outside user folder for org {}, user {}: {}".format(
                org_id, user_id, file_path
            ))
            return json_response({'error': 'Security error: invalid file path'}), 400
        
        # Check if file already exists (unless replace=true)
        replace = request.form.get('replace', 'false').lower() == 'true'
        
        if os.path.exists(file_path) and not replace:
            logger.info("File already exists for org {}: {}".format(org_id, filename))
            return json_response({
                'error': 'File "{}" already exists. Use replace option to overwrite.'.format(filename),
                'filename': filename,
                'exists': True
            }), 409
        
        # Check file size
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > MAX_FILE_SIZE:
            return json_response({
                'error': 'File too large. Maximum size: {}MB'.format(MAX_FILE_SIZE / (1024 * 1024))
            }), 400
        
        # Store content type before saving
        content_type = file.content_type or 'application/octet-stream'
        
        # Save file (will overwrite if replace=true)
        file.save(file_path)
        
        # Set file permissions to 0755 (rwxr-xr-x) so WildFly can read and execute it
        try:
            os.chmod(file_path, 0o755)
            logger.info("Set file permissions to 0755 (rwxr-xr-x) for: {}".format(file_path))
        except OSError as e:
            # If we can't chmod (e.g., file owned by root), that's OK as long as it's readable
            logger.warning("Could not set file permissions (file may be owned by root): {}".format(str(e)))
            # Verify file is at least readable
            if not os.access(file_path, os.R_OK):
                logger.error("File is not readable after upload: {}".format(file_path))
                return json_response({'error': 'File uploaded but is not readable. Please contact administrator.'}), 500
        
        if replace:
            logger.info("File replaced for org {}, user {}: {} ({} bytes)".format(
                org_id, user_id, filename, file_size
            ))
        
        logger.info("File uploaded successfully for org {}, user {}: {} ({} bytes)".format(
            org_id, user_id, filename, file_size
        ))
        
        # Call Java servlet to insert foreign table/view into VDB
        # IMPORTANT: This must complete before any VDB redeployment to avoid race conditions
        servlet_success = False
        servlet_error = None
        try:
            import requests
            import time
            servlet_url = "http://localhost:8095/TeiidExcelImporterTest/upload"
            logger.info("Calling Java servlet to update VDB with table definition: {}".format(servlet_url))
            
            # Determine VDB type based on project status
            vdb_type = 'shared' if is_shared_project else 'user'
            logger.info("VDB type for upload: {}".format(vdb_type))
            
            # Re-open the file to send to servlet
            with open(file_path, 'rb') as f:
                files = {'file': (filename, f, content_type)}
                data = {
                    'org_id': str(org_id),
                    'user_id': str(user_id),
                    'vdb_type': vdb_type,
                    'replace': 'true' if replace else 'false'
                }
                params = {
                    'org_id': str(org_id),
                    'user_id': str(user_id),
                    'vdb_type': vdb_type
                }
                
                # Increase timeout to 60 seconds to allow Excel processing to complete
                # This prevents race conditions where VDB is redeployed before table definitions are added
                servlet_response = requests.post(
                    servlet_url,
                    files=files,
                    data=data,
                    params=params,
                    timeout=60
                )
                
                if servlet_response.status_code == 200:
                    servlet_success = True
                    logger.info("Java servlet updated {} VDB successfully for org {}".format(vdb_type, org_id))
                    logger.info("Servlet response: {}".format(servlet_response.text))
                    
                    # Parse response to check for actual success
                    try:
                        response_json = servlet_response.json()
                        if response_json.get('status') == 'success':
                            logger.info("VDB table/view created successfully for file: {}".format(filename))
                        elif response_json.get('status') == 'conflict':
                            logger.info("VDB table/view already exists for file: {}".format(filename))
                            servlet_success = True  # Still consider this a success
                        else:
                            servlet_error = response_json.get('error', 'Unknown error')
                            logger.warning("Servlet returned non-success status: {}".format(response_json))
                    except Exception as json_err:
                        logger.warning("Could not parse servlet response as JSON: {}".format(str(json_err)))
                elif servlet_response.status_code == 409:
                    # Conflict - table already exists, this is OK
                    servlet_success = True
                    logger.info("VDB table/view already exists for file: {} (conflict response)".format(filename))
                else:
                    servlet_error = "Status {}: {}".format(servlet_response.status_code, servlet_response.text)
                    logger.error("Java servlet failed with status {}: {}".format(
                        servlet_response.status_code,
                        servlet_response.text
                    ))
                    logger.error("Request details - URL: {}, org_id: {}, user_id: {}, vdb_type: {}, filename: {}".format(
                        servlet_url, org_id, user_id, vdb_type, filename
                    ))
        except requests.exceptions.Timeout:
            servlet_error = "Servlet request timed out after 60 seconds"
            logger.error("Java servlet timed out for org {}, user {}: {}".format(org_id, user_id, servlet_error))
        except Exception as e:
            servlet_error = str(e)
            # Don't fail the upload if servlet call fails
            logger.error("Failed to call Java servlet for org {}, user {}: {}".format(org_id, user_id, str(e)))
            import traceback
            logger.error("Traceback: {}".format(traceback.format_exc()))
        
        # VDB updates are now handled by the Java servlet
        # The servlet will update the correct VDB (shared or user) based on vdb_type parameter
        logger.info("VDB update delegated to Java servlet (vdb_type: {}, success: {})".format(vdb_type, servlet_success))
        
        # Return success with file info and servlet status
        response_data = {
            'success': True,
            'filename': filename,
            'path': file_path,
            'org_id': org_id,
            'user_id': user_id,
            'size': file_size,
            'vdb_updated': servlet_success
        }
        
        # Include servlet error if there was one (but don't fail the upload)
        if servlet_error:
            response_data['vdb_error'] = servlet_error
            logger.warning("File uploaded but VDB update had issues: {}".format(servlet_error))
        
        return json_response(response_data)
        
    except Exception as e:
        logger.error("File upload failed: {}".format(str(e)))
        return json_response({
            'error': 'File upload failed: {}'.format(str(e))
        }), 500


@routes.route(org_scoped_rule('/api/files'), methods=['GET'])
@login_required
def list_files(org_slug=None):
    """
    List uploaded files for current user.
    
    Query Parameters:
        - folder_type: 'uploads' or 'vdb' (default: 'uploads')
        
    Response:
        {
            "success": true,
            "files": ["data.xlsx", "report.csv"],
            "org_id": 1,
            "user_id": 123,
            "folder": "/opt/wildfly/teiidfiles/customers/1/123/uploads"
        }
    """
    try:
        # Get organization ID and user ID
        org_id = current_org.id
        user_id = current_user.id
        
        # Get folder type
        folder_type = request.args.get('folder_type', 'uploads')
        
        if folder_type not in ['uploads', 'vdb']:
            return json_response({'error': 'Invalid folder_type'}), 400
        
        # Get customer folder service
        from redash.services.customer_folders import CustomerFolderService
        folder_service = CustomerFolderService()
        
        # Get folder path for user
        if folder_type == 'uploads':
            folder_path = folder_service.get_user_uploads_folder(org_id, user_id)
        else:
            folder_path = folder_service.get_user_vdb_folder(org_id, user_id)
        
        # List files in user's folder
        files = []
        if os.path.exists(folder_path):
            files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
        
        return json_response({
            'success': True,
            'files': files,
            'org_id': org_id,
            'user_id': user_id,
            'folder': folder_path
        })
        
    except Exception as e:
        logger.error("Failed to list files: {}".format(str(e)))
        return json_response({
            'error': 'Failed to list files: {}'.format(str(e))
        }), 500


@routes.route(org_scoped_rule('/api/files/<filename>'), methods=['DELETE'])
@login_required
def delete_file(filename, org_slug=None):
    """
    Delete an uploaded file from user's folder.
    
    Path Parameters:
        - filename: Name of file to delete
        
    Response:
        {
            "success": true,
            "filename": "data.xlsx",
            "message": "File deleted successfully"
        }
    """
    try:
        # Get organization ID and user ID
        org_id = current_org.id
        user_id = current_user.id
        
        # Get customer folder service
        from redash.services.customer_folders import CustomerFolderService
        folder_service = CustomerFolderService()
        
        # Secure filename
        filename = secure_filename(filename)
        
        # Validate filename
        if not filename or filename == '':
            return json_response({'error': 'Invalid filename'}), 400
        
        # Additional validation (prevent directory traversal)
        if '..' in filename or '/' in filename or '\\' in filename:
            logger.warning("Invalid file path rejected for org {}, user {}: {}".format(org_id, user_id, filename))
            return json_response({'error': 'Invalid file path'}), 400
        
        # Get file path in user's uploads folder
        uploads_folder = folder_service.get_user_uploads_folder(org_id, user_id)
        file_path = os.path.join(uploads_folder, filename)
        
        # Validate that the file path is within the user's uploads folder
        file_path_real = os.path.realpath(file_path)
        uploads_folder_real = os.path.realpath(uploads_folder)
        
        if not file_path_real.startswith(uploads_folder_real):
            logger.error("Security violation: file path outside user folder for org {}, user {}: {}".format(
                org_id, user_id, file_path
            ))
            return json_response({'error': 'Security error: invalid file path'}), 400
        
        # Check if file exists
        if not os.path.exists(file_path):
            return json_response({'error': 'File not found'}), 404
        
        # Delete file
        os.remove(file_path)
        
        logger.info("File deleted for org {}, user {}: {}".format(org_id, user_id, filename))
        
        return json_response({
            'success': True,
            'filename': filename,
            'message': 'File deleted successfully'
        })
        
    except Exception as e:
        logger.error("Failed to delete file: {}".format(str(e)))
        return json_response({
            'error': 'Failed to delete file: {}'.format(str(e))
        }), 500
