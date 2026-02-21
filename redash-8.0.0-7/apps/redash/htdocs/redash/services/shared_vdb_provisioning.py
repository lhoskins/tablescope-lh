"""
Shared VDB Auto-Provisioning Service

Automatically provisions shared VDB database records when VDB files exist on disk
but corresponding database records are missing. This ensures the migration system
can find and use shared VDBs without manual intervention.

Requirements: 26.1-26.10
"""

import logging
import os
import re
from redash.models.shared_vdb import SharedVDB
from redash.models.organization_vdb import OrganizationVDB
from redash.models import db

logger = logging.getLogger(__name__)


class SharedVDBProvisioningError(Exception):
    """Raised when shared VDB provisioning fails."""
    pass


class SharedVDBProvisioningService(object):
    """
    Service for auto-provisioning shared VDB database records.
    
    This service ensures that when a shared VDB file exists on disk,
    a corresponding database record exists in the shared_vdbs table.
    It extracts connection parameters from the organization_vdbs table
    and creates the shared VDB record automatically.
    """
    
    def __init__(self):
        """Initialize Shared VDB Provisioning Service."""
        self.base_path = "/opt/wildfly/teiidfiles/customers"
    
    def auto_provision_shared_vdb(self, org_id):
        """
        Automatically provision a shared VDB database record for an organization.
        
        This method:
        1. Finds the shared VDB file on disk
        2. Extracts the VDB ID from the filename
        3. Retrieves connection parameters from organization_vdbs table
        4. Creates a shared_vdbs database record
        
        Requirements: 26.1, 26.2, 26.3, 26.4, 26.5, 26.6, 26.7, 26.8, 26.9, 26.10
        
        Args:
            org_id (int): Organization ID
            
        Returns:
            SharedVDB: The newly created shared VDB record
            
        Raises:
            SharedVDBProvisioningError: If provisioning fails
        """
        logger.info("Auto-provisioning shared VDB for organization {}".format(org_id))
        
        # Check if shared VDB record already exists (Requirement 26.7)
        existing_vdb = SharedVDB.get_by_organization(org_id)
        if existing_vdb:
            logger.info("Shared VDB record already exists for organization {}: {}".format(
                org_id, existing_vdb.vdb_id
            ))
            return existing_vdb
        
        # Find shared VDB file on disk (Requirement 26.1)
        vdb_file_path = self._find_shared_vdb_file(org_id)
        if not vdb_file_path:
            raise SharedVDBProvisioningError(
                "No shared VDB file found for organization {}".format(org_id)
            )
        
        logger.info("Found shared VDB file: {}".format(vdb_file_path))
        
        # Validate VDB file is readable and properly formatted (Requirement 26.10)
        if not self._validate_vdb_file(vdb_file_path):
            raise SharedVDBProvisioningError(
                "Shared VDB file is not readable or properly formatted: {}".format(vdb_file_path)
            )
        
        # Extract VDB ID from filename (Requirement 26.4)
        vdb_id = self._extract_vdb_id_from_file(vdb_file_path)
        if not vdb_id:
            raise SharedVDBProvisioningError(
                "Could not extract VDB ID from file path: {}".format(vdb_file_path)
            )
        
        logger.info("Extracted VDB ID: {}".format(vdb_id))
        
        # Get connection parameters from organization_vdbs table (Requirement 26.3)
        connection_params = self._get_org_vdb_connection_params(org_id)
        if not connection_params:
            raise SharedVDBProvisioningError(
                "No organization VDB configuration found for organization {}".format(org_id)
            )
        
        logger.info("Retrieved connection parameters from organization_vdbs")
        
        # Create shared VDB database record (Requirement 26.5, 26.6)
        shared_vdb = self._create_shared_vdb_record(
            org_id=org_id,
            vdb_id=vdb_id,
            connection_params=connection_params
        )
        
        logger.info("Successfully auto-provisioned shared VDB {} for organization {}".format(
            vdb_id, org_id
        ))
        
        return shared_vdb
    
    def check_and_provision_if_needed(self, org_id):
        """
        Check if shared VDB record exists, and auto-provision if needed.
        
        This method is called before attempting to use a shared VDB to ensure
        the database record exists. If the VDB file exists but the record doesn't,
        it will be automatically provisioned.
        
        Requirements: 26.1, 26.2, 26.3, 26.6
        
        Args:
            org_id (int): Organization ID
            
        Returns:
            SharedVDB: The shared VDB record (existing or newly created)
            None: If no VDB file exists and provisioning is not possible
            
        Raises:
            SharedVDBProvisioningError: If provisioning fails
        """
        # Check if shared VDB record exists (Requirement 26.2)
        shared_vdb = SharedVDB.get_by_organization(org_id)
        
        if shared_vdb:
            logger.debug("Shared VDB record exists for organization {}".format(org_id))
            return shared_vdb
        
        # Check if VDB file exists on disk (Requirement 26.1)
        vdb_file_path = self._find_shared_vdb_file(org_id)
        
        if not vdb_file_path:
            logger.warning("No shared VDB file found for organization {}".format(org_id))
            return None
        
        # VDB file exists but record doesn't - auto-provision (Requirement 26.3)
        logger.info("Shared VDB file exists but record missing for organization {}. Auto-provisioning...".format(org_id))
        
        try:
            shared_vdb = self.auto_provision_shared_vdb(org_id)
            logger.info("Auto-provisioned shared VDB {} for organization {}".format(
                shared_vdb.vdb_id, org_id
            ))
            return shared_vdb
        except Exception as e:
            logger.error("Failed to auto-provision shared VDB for organization {}: {}".format(
                org_id, str(e)
            ))
            raise SharedVDBProvisioningError(
                "Failed to auto-provision shared VDB: {}".format(str(e))
            )
    
    def _find_shared_vdb_file(self, org_id):
        """
        Find the shared VDB file on disk for an organization.
        
        Searches in two locations (in order):
        1. /opt/wildfly/teiidfiles/customers/{org_id}/shared/vdb/ (new structure)
        2. /opt/wildfly/teiidfiles/customers/{org_id}/vdb/ (legacy structure)
        
        Looks for files matching pattern: *-vdb.xml
        
        Requirement: 26.1
        
        Args:
            org_id (int): Organization ID
            
        Returns:
            str: Full path to VDB file, or None if not found
        """
        # First try the shared VDB directory (new structure for shared projects)
        shared_vdb_dir = os.path.join(self.base_path, str(org_id), "shared", "vdb")
        
        vdb_file_path = self._search_vdb_in_directory(shared_vdb_dir)
        if vdb_file_path:
            logger.debug("Found shared VDB file in shared/vdb directory: {}".format(vdb_file_path))
            return vdb_file_path
        
        # Fallback to organization VDB directory (legacy structure)
        org_vdb_dir = os.path.join(self.base_path, str(org_id), "vdb")
        
        vdb_file_path = self._search_vdb_in_directory(org_vdb_dir)
        if vdb_file_path:
            logger.debug("Found shared VDB file in org vdb directory (legacy): {}".format(vdb_file_path))
            return vdb_file_path
        
        logger.debug("No shared VDB file found for organization {}".format(org_id))
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
        Example: 9162153-vdb.xml -> 9162153
        
        Requirement: 26.4
        
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
        should be used for the shared VDB.
        
        Requirement: 26.3
        
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
    
    def _create_shared_vdb_record(self, org_id, vdb_id, connection_params):
        """
        Create a shared VDB database record.
        
        Creates a new record in the shared_vdbs table with the provided
        VDB ID and connection parameters. The VDB ID MUST match the filename
        to ensure routing works correctly.
        
        Requirements: 26.5, 26.6, 26.7
        
        Args:
            org_id (int): Organization ID
            vdb_id (str): VDB identifier (extracted from filename)
            connection_params (dict): Connection parameters from organization_vdbs
            
        Returns:
            SharedVDB: The newly created shared VDB record
            
        Raises:
            SharedVDBProvisioningError: If record creation fails
        """
        try:
            # Check if record already exists (Requirement 26.7)
            existing_vdb = SharedVDB.get_by_organization(org_id)
            if existing_vdb:
                # If VDB ID doesn't match filename, update it to match
                if existing_vdb.vdb_id != vdb_id:
                    logger.warning(
                        "Shared VDB record exists for organization {} but VDB ID mismatch: "
                        "database={}, filename={}. Updating database to match filename.".format(
                            org_id, existing_vdb.vdb_id, vdb_id
                        )
                    )
                    existing_vdb.vdb_id = vdb_id
                    db.session.add(existing_vdb)
                    db.session.commit()
                    logger.info("Updated shared VDB record to match filename: vdb_id={}".format(vdb_id))
                else:
                    logger.info("Shared VDB record already exists for organization {}: {}".format(
                        org_id, existing_vdb.vdb_id
                    ))
                return existing_vdb
            
            # Create new shared VDB record
            shared_vdb = SharedVDB(
                organization_id=org_id,
                vdb_id=vdb_id,
                vdb_username=connection_params['vdb_username'],
                vdb_host=connection_params['vdb_host'],
                vdb_port=connection_params['vdb_port'],
                is_active=True,  # Requirement 26.5
                health_status='active'  # Requirement 26.5
            )
            
            # Set password
            shared_vdb.set_encrypted_password(connection_params['vdb_password'])
            
            # Add to database session
            db.session.add(shared_vdb)
            db.session.commit()
            
            # Log the operation (Requirement 26.6)
            logger.info("Created shared VDB record: org_id={}, vdb_id={}, host={}, port={}".format(
                org_id, vdb_id, connection_params['vdb_host'], connection_params['vdb_port']
            ))
            logger.info("IMPORTANT: VDB ID {} matches filename to ensure correct routing".format(vdb_id))
            
            return shared_vdb
            
        except Exception as e:
            db.session.rollback()
            logger.error("Failed to create shared VDB record for organization {}: {}".format(
                org_id, str(e)
            ))
            raise SharedVDBProvisioningError(
                "Failed to create shared VDB record: {}".format(str(e))
            )
    
    def _validate_vdb_file(self, vdb_file_path):
        """
        Validate that VDB file is readable and properly formatted.
        
        Checks:
        - File exists
        - File is readable
        - File contains valid XML
        - File contains VDB root element
        
        Requirement: 26.10
        
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
