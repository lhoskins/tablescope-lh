"""
User VDB Auto-Provisioning Service

Automatically provisions user VDB database records when VDB files exist on disk
but corresponding database records are missing. This ensures the routing system
can find and use user VDBs without manual intervention.

Requirements: Similar to shared VDB auto-provisioning (26.1-26.10)
"""

import logging
import os
import re
from redash.models.user_vdb import UserVDB
from redash.models.organization_vdb import OrganizationVDB
from redash.models import db

logger = logging.getLogger(__name__)


class UserVDBProvisioningError(Exception):
    """Raised when user VDB provisioning fails."""
    pass


class UserVDBProvisioningService(object):
    """
    Service for auto-provisioning user VDB database records.
    
    This service ensures that when a user VDB file exists on disk,
    a corresponding database record exists in the user_vdbs table.
    It extracts connection parameters from the organization_vdbs table
    and creates the user VDB record automatically.
    """
    
    def __init__(self):
        """Initialize User VDB Provisioning Service."""
        self.base_path = "/opt/wildfly/teiidfiles/customers"
    
    def auto_provision_user_vdb(self, user_id, org_id):
        """
        Automatically provision a user VDB database record.
        
        This method:
        1. Finds the user VDB file on disk
        2. Extracts the VDB ID from the filename
        3. Retrieves connection parameters from organization_vdbs table
        4. Creates a user_vdbs database record
        
        Args:
            user_id (int): User ID
            org_id (int): Organization ID
            
        Returns:
            UserVDB: The newly created user VDB record
            
        Raises:
            UserVDBProvisioningError: If provisioning fails
        """
        logger.info("Auto-provisioning user VDB for user {} in organization {}".format(user_id, org_id))
        
        # Check if user VDB record already exists
        existing_vdb = UserVDB.get_by_user(user_id)
        if existing_vdb:
            logger.info("User VDB record already exists for user {}: {}".format(
                user_id, existing_vdb.vdb_id
            ))
            return existing_vdb
        
        # Find user VDB file on disk
        vdb_file_path = self._find_user_vdb_file(org_id, user_id)
        if not vdb_file_path:
            raise UserVDBProvisioningError(
                "No user VDB file found for user {} in organization {}".format(user_id, org_id)
            )
        
        logger.info("Found user VDB file: {}".format(vdb_file_path))
        
        # Validate VDB file is readable and properly formatted
        if not self._validate_vdb_file(vdb_file_path):
            raise UserVDBProvisioningError(
                "User VDB file is not readable or properly formatted: {}".format(vdb_file_path)
            )
        
        # Extract VDB ID from filename
        vdb_id = self._extract_vdb_id_from_file(vdb_file_path)
        if not vdb_id:
            raise UserVDBProvisioningError(
                "Could not extract VDB ID from file path: {}".format(vdb_file_path)
            )
        
        logger.info("Extracted VDB ID: {}".format(vdb_id))
        
        # Get connection parameters from organization_vdbs table
        connection_params = self._get_org_vdb_connection_params(org_id)
        if not connection_params:
            raise UserVDBProvisioningError(
                "No organization VDB configuration found for organization {}".format(org_id)
            )
        
        logger.info("Retrieved connection parameters from organization_vdbs")
        
        # Create user VDB database record
        user_vdb = self._create_user_vdb_record(
            user_id=user_id,
            org_id=org_id,
            vdb_id=vdb_id,
            connection_params=connection_params
        )
        
        logger.info("Successfully auto-provisioned user VDB {} for user {} in organization {}".format(
            vdb_id, user_id, org_id
        ))
        
        return user_vdb
    
    def check_and_provision_if_needed(self, user_id, org_id):
        """
        Check if user VDB record exists, and auto-provision if needed.
        
        This method is called before attempting to use a user VDB to ensure
        the database record exists. If the VDB file exists but the record doesn't,
        it will be automatically provisioned.
        
        Args:
            user_id (int): User ID
            org_id (int): Organization ID
            
        Returns:
            UserVDB: The user VDB record (existing or newly created)
            None: If no VDB file exists and provisioning is not possible
            
        Raises:
            UserVDBProvisioningError: If provisioning fails
        """
        # Check if user VDB record exists
        user_vdb = UserVDB.get_by_user(user_id)
        
        if user_vdb:
            logger.debug("User VDB record exists for user {}".format(user_id))
            return user_vdb
        
        # Check if VDB file exists on disk
        vdb_file_path = self._find_user_vdb_file(org_id, user_id)
        
        if not vdb_file_path:
            logger.warning("No user VDB file found for user {} in organization {}".format(user_id, org_id))
            return None
        
        # VDB file exists but record doesn't - auto-provision
        logger.info("User VDB file exists but record missing for user {}. Auto-provisioning...".format(user_id))
        
        try:
            user_vdb = self.auto_provision_user_vdb(user_id, org_id)
            logger.info("Auto-provisioned user VDB {} for user {}".format(
                user_vdb.vdb_id, user_id
            ))
            return user_vdb
        except Exception as e:
            logger.error("Failed to auto-provision user VDB for user {}: {}".format(
                user_id, str(e)
            ))
            raise UserVDBProvisioningError(
                "Failed to auto-provision user VDB: {}".format(str(e))
            )
    
    def _find_user_vdb_file(self, org_id, user_id):
        """
        Find the user VDB file on disk.
        
        Searches in: /opt/wildfly/teiidfiles/customers/{org_id}/{user_id}/vdb/
        
        Looks for files matching pattern: *-vdb.xml
        
        Args:
            org_id (int): Organization ID
            user_id (int): User ID
            
        Returns:
            str: Full path to VDB file, or None if not found
        """
        user_vdb_dir = os.path.join(self.base_path, str(org_id), str(user_id), "vdb")
        
        vdb_file_path = self._search_vdb_in_directory(user_vdb_dir)
        if vdb_file_path:
            logger.debug("Found user VDB file: {}".format(vdb_file_path))
            return vdb_file_path
        
        logger.debug("No user VDB file found for user {} in organization {}".format(user_id, org_id))
        return None
    
    def _search_vdb_in_directory(self, vdb_dir):
        """
        Search for VDB files in a directory.
        
        Args:
            vdb_dir (str): Directory path to search
            
        Returns:
            str: Full path to VDB file, or None if not found
        """
        if not os.path.exists(vdb_dir):
            logger.debug("VDB directory does not exist: {}".format(vdb_dir))
            return None
        
        if not os.path.isdir(vdb_dir):
            logger.warning("VDB path exists but is not a directory: {}".format(vdb_dir))
            return None
        
        # Look for VDB files matching pattern *-vdb.xml
        try:
            files = os.listdir(vdb_dir)
            vdb_files = [f for f in files if f.endswith('-vdb.xml')]
            
            if not vdb_files:
                logger.debug("No VDB files found in {}".format(vdb_dir))
                return None
            
            if len(vdb_files) > 1:
                logger.warning("Multiple VDB files found in {}: {}. Using first one.".format(
                    vdb_dir, vdb_files
                ))
            
            # Return full path to first VDB file found
            vdb_file = vdb_files[0]
            vdb_file_path = os.path.join(vdb_dir, vdb_file)
            
            return vdb_file_path
            
        except OSError as e:
            logger.error("Error reading VDB directory {}: {}".format(vdb_dir, str(e)))
            return None
    
    def _extract_vdb_id_from_file(self, vdb_file_path):
        """
        Extract VDB ID from VDB filename.
        
        Expected filename format: {vdb_id}-vdb.xml
        Example: 3399680-vdb.xml -> 3399680
        
        Args:
            vdb_file_path (str): Full path to VDB file
            
        Returns:
            str: VDB ID, or None if extraction fails
        """
        try:
            # Get filename from path
            filename = os.path.basename(vdb_file_path)
            
            # Extract VDB ID using regex pattern: {vdb_id}-vdb.xml
            match = re.match(r'^(.+)-vdb\.xml$', filename)
            
            if match:
                vdb_id = match.group(1)
                logger.debug("Extracted VDB ID '{}' from filename '{}'".format(vdb_id, filename))
                return vdb_id
            else:
                logger.warning("Filename '{}' does not match expected pattern '*-vdb.xml'".format(filename))
                return None
                
        except Exception as e:
            logger.error("Error extracting VDB ID from path {}: {}".format(vdb_file_path, str(e)))
            return None
    
    def _get_org_vdb_connection_params(self, org_id):
        """
        Retrieve VDB connection parameters from organization_vdbs table.
        
        Gets the connection settings (host, port, username, password) that
        should be used for the user VDB.
        
        Args:
            org_id (int): Organization ID
            
        Returns:
            dict: Connection parameters containing:
                - vdb_host: VDB host
                - vdb_port: VDB port
                - vdb_username: VDB username
                - vdb_password: VDB password
            None: If no organization VDB configuration found
        """
        try:
            # Get organization VDB configuration
            org_vdb = OrganizationVDB.get_by_organization(org_id)
            
            if not org_vdb:
                logger.warning("No organization VDB configuration found for organization {}".format(org_id))
                return None
            
            # Extract connection parameters
            connection_params = {
                'vdb_host': org_vdb.vdb_host,
                'vdb_port': org_vdb.vdb_port,
                'vdb_username': org_vdb.vdb_username,
                'vdb_password': org_vdb.get_decrypted_password()
            }
            
            logger.debug("Retrieved connection parameters for organization {}: host={}, port={}".format(
                org_id, connection_params['vdb_host'], connection_params['vdb_port']
            ))
            
            return connection_params
            
        except Exception as e:
            logger.error("Error retrieving connection parameters for organization {}: {}".format(
                org_id, str(e)
            ))
            return None
    
    def _create_user_vdb_record(self, user_id, org_id, vdb_id, connection_params):
        """
        Create a user VDB database record.
        
        Creates a new record in the user_vdbs table with the provided
        VDB ID and connection parameters. The VDB ID MUST match the filename
        to ensure routing works correctly.
        
        Args:
            user_id (int): User ID
            org_id (int): Organization ID
            vdb_id (str): VDB identifier (extracted from filename)
            connection_params (dict): Connection parameters from organization_vdbs
            
        Returns:
            UserVDB: The newly created user VDB record
            
        Raises:
            UserVDBProvisioningError: If record creation fails
        """
        try:
            # Check if record already exists
            existing_vdb = UserVDB.get_by_user(user_id)
            if existing_vdb:
                # If VDB ID doesn't match filename, update it to match
                if existing_vdb.vdb_id != vdb_id:
                    logger.warning(
                        "User VDB record exists for user {} but VDB ID mismatch: "
                        "database={}, filename={}. Updating database to match filename.".format(
                            user_id, existing_vdb.vdb_id, vdb_id
                        )
                    )
                    existing_vdb.vdb_id = vdb_id
                    db.session.add(existing_vdb)
                    db.session.commit()
                    logger.info("Updated user VDB record to match filename: vdb_id={}".format(vdb_id))
                else:
                    logger.info("User VDB record already exists for user {}: {}".format(
                        user_id, existing_vdb.vdb_id
                    ))
                return existing_vdb
            
            # Create new user VDB record
            user_vdb = UserVDB(
                user_id=user_id,
                organization_id=org_id,
                vdb_id=vdb_id,
                vdb_username=connection_params['vdb_username'],
                vdb_host=connection_params['vdb_host'],
                vdb_port=connection_params['vdb_port'],
                is_active=True,
                health_status='active'
            )
            
            # Set password
            user_vdb.set_encrypted_password(connection_params['vdb_password'])
            
            # Add to database session
            db.session.add(user_vdb)
            db.session.commit()
            
            # Log the operation
            logger.info("Created user VDB record: user_id={}, org_id={}, vdb_id={}, host={}, port={}".format(
                user_id, org_id, vdb_id, connection_params['vdb_host'], connection_params['vdb_port']
            ))
            logger.info("IMPORTANT: VDB ID {} matches filename to ensure correct routing".format(vdb_id))
            
            return user_vdb
            
        except Exception as e:
            db.session.rollback()
            logger.error("Failed to create user VDB record for user {}: {}".format(
                user_id, str(e)
            ))
            raise UserVDBProvisioningError(
                "Failed to create user VDB record: {}".format(str(e))
            )
    
    def _validate_vdb_file(self, vdb_file_path):
        """
        Validate that VDB file is readable and properly formatted.
        
        Checks:
        - File exists
        - File is readable
        - File contains valid XML
        - File contains VDB root element
        
        Args:
            vdb_file_path (str): Full path to VDB file
            
        Returns:
            bool: True if file is valid, False otherwise
        """
        try:
            # Check file exists
            if not os.path.exists(vdb_file_path):
                logger.warning("VDB file does not exist: {}".format(vdb_file_path))
                return False
            
            # Check file is readable
            if not os.access(vdb_file_path, os.R_OK):
                logger.warning("VDB file is not readable: {}".format(vdb_file_path))
                return False
            
            # Try to parse as XML
            import xml.etree.ElementTree as ET
            
            try:
                tree = ET.parse(vdb_file_path)
                root = tree.getroot()
                
                # Check for VDB root element
                if 'vdb' not in root.tag.lower():
                    logger.warning("VDB file does not contain vdb root element: {}".format(vdb_file_path))
                    return False
                
                logger.debug("VDB file is valid: {}".format(vdb_file_path))
                return True
                
            except ET.ParseError as e:
                logger.warning("VDB file is not valid XML: {}, error: {}".format(vdb_file_path, str(e)))
                return False
                
        except Exception as e:
            logger.error("Error validating VDB file {}: {}".format(vdb_file_path, str(e)))
            return False
