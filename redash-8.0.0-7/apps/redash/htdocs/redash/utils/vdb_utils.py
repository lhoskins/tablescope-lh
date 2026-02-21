"""
VDB Utilities

Utility functions for VDB (Virtual Database) management including:
- VDB identifier generation (random 7-digit numbers)
- VDB credential generation
- VDB ID validation and sanitization
"""

import re
import random
import logging

from redash.utils import generate_token

logger = logging.getLogger(__name__)


def generate_vdb_id():
    """
    Generate a random 7-digit VDB identifier.
    
    The VDB ID is a random 7-digit number (1000000-9999999) that is unique
    across all organizations. This ID is used as the VDB name in Teiid.
    
    Returns:
        String of 7 random digits (e.g., "1234567", "9876543")
        
    Examples:
        >>> vdb_id = generate_vdb_id()
        >>> len(vdb_id)
        7
        >>> vdb_id.isdigit()
        True
        >>> 1000000 <= int(vdb_id) <= 9999999
        True
    """
    # Import here to avoid circular dependency
    from redash.models.organization_vdb import OrganizationVDB
    
    # Generate random 7-digit number
    max_attempts = 100
    for attempt in range(max_attempts):
        vdb_id = str(random.randint(1000000, 9999999))
        
        # Check uniqueness against database
        if not OrganizationVDB.get_by_vdb_id(vdb_id):
            logger.info('Generated unique VDB ID: {}'.format(vdb_id))
            return vdb_id
        
        logger.debug('VDB ID collision on attempt {}: {}'.format(attempt + 1, vdb_id))
    
    # If we couldn't find a unique ID after max_attempts, raise an error
    raise RuntimeError(
        'Failed to generate unique VDB ID after {} attempts. '
        'This is extremely unlikely and may indicate a database issue.'.format(max_attempts)
    )


def generate_vdb_credentials():
    """
    Generate VDB credentials (username and password).
    
    NOTE: Currently using fixed credentials 'test'/'test' based on production
    testing that resolved timeout issues. In the future, this can be changed
    to generate random credentials for better security.
    
    Returns:
        Tuple of (username, password)
        - username: 'test' (fixed for now)
        - password: 'test' (fixed for now)
        
    Examples:
        >>> username, password = generate_vdb_credentials()
        >>> username == 'test'
        True
        >>> password == 'test'
        True
    """
    # Fixed credentials based on production testing
    # These credentials resolved timeout issues when connecting to Teiid
    # TODO: Consider making these configurable via environment variables
    username = 'test'
    password = 'test'
    
    return username, password


def validate_vdb_id(vdb_id):
    """
    Validate that a VDB identifier follows the correct format.
    
    Rules:
    - Must be exactly 7 digits
    - Range: 1000000-9999999
    
    Args:
        vdb_id: VDB identifier to validate (string or int)
        
    Returns:
        True if valid, False otherwise
        
    Examples:
        >>> validate_vdb_id('1234567')
        True
        >>> validate_vdb_id(1234567)
        True
        >>> validate_vdb_id('123456')
        False
        >>> validate_vdb_id('12345678')
        False
        >>> validate_vdb_id('abcdefg')
        False
    """
    if not vdb_id:
        return False
    
    # Convert to string if integer
    vdb_id_str = str(vdb_id)
    
    # Check if it's exactly 7 digits
    if not re.match(r'^\d{7}$', vdb_id_str):
        return False
    
    # Check range (1000000-9999999)
    vdb_id_int = int(vdb_id_str)
    if not (1000000 <= vdb_id_int <= 9999999):
        return False
    
    return True


def get_customer_folder_path(org_id, base_path='/opt/wildfly/teiidfiles/customers'):
    """
    Get the customer folder path for an organization.
    
    Args:
        org_id: Organization ID
        base_path: Base path for customer folders
        
    Returns:
        Customer folder path (e.g., '/opt/wildfly/teiidfiles/customers/5')
    """
    import os
    return os.path.join(base_path, str(org_id))


def get_vdb_file_path(org_id, vdb_id, base_path='/opt/wildfly/teiidfiles/customers'):
    """
    Get the VDB file path for an organization.
    
    Args:
        org_id: Organization ID
        vdb_id: VDB identifier (7-digit number)
        base_path: Base path for customer folders
        
    Returns:
        VDB file path (e.g., '/opt/wildfly/teiidfiles/customers/5/1234567-vdb.xml')
    """
    import os
    customer_folder = get_customer_folder_path(org_id, base_path)
    return os.path.join(customer_folder, '{}-vdb.xml'.format(vdb_id))


def get_vdb_archive_path(org_id, vdb_id, base_path='/opt/wildfly/teiidfiles/customers'):
    """
    Get the VDB archive path for an organization.
    
    Args:
        org_id: Organization ID
        vdb_id: VDB identifier (7-digit number)
        base_path: Base path for customer folders
        
    Returns:
        VDB archive path (e.g., '/opt/wildfly/teiidfiles/customers/5/vdb/archive/1234567-vdb.xml')
    """
    import os
    customer_folder = get_customer_folder_path(org_id, base_path)
    return os.path.join(customer_folder, 'vdb', 'archive', '{}-vdb.xml'.format(vdb_id))


def get_uploads_folder_path(org_id, base_path='/opt/wildfly/teiidfiles/customers'):
    """
    Get the uploads folder path for an organization.
    
    Args:
        org_id: Organization ID
        base_path: Base path for customer folders
        
    Returns:
        Uploads folder path (e.g., '/opt/wildfly/teiidfiles/customers/5/uploads')
    """
    import os
    customer_folder = get_customer_folder_path(org_id, base_path)
    return os.path.join(customer_folder, 'uploads')


def get_vdb_template_path():
    """
    Get the hardcoded VDB template path.
    
    Returns:
        VDB template path: '/opt/wildfly/teiidfiles/vdb_template/vdb_ template.xml'
    """
    return '/opt/wildfly/teiidfiles/vdb_template/vdb_ template.xml'
