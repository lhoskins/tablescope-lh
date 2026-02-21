"""
VDB Migration Service

Service for migrating VDB configurations (foreign tables and views) between
private and shared VDBs during project sharing operations.

This service now delegates VDB manipulation to the Java VDBMigrationServlet
which properly handles:
- CDATA sections in VDB XML
- Both Excel (FOREIGN TABLE) and CSV/TXT (VIEW) file types
- Automatic VDB redeployment to Teiid
- Proper path updates in DDL statements
"""

import os
import logging
try:
    import requests
except ImportError:
    requests = None
try:
    import urllib2
    import json as json_lib
except ImportError:
    urllib2 = None
    json_lib = None

from redash.services.exceptions import VDBMigrationError, VDBNotFoundError

logger = logging.getLogger(__name__)

# Servlet configuration
DEFAULT_SERVLET_URL = "http://localhost:8080/TeiidExcelImporterTest/migrate-vdb"
SERVLET_TIMEOUT = 120  # seconds


class VDBMigrationService:
    """
    Handles VDB configuration migration via the Java VDBMigrationServlet.
    
    This service delegates VDB manipulation to the servlet which handles:
    - Foreign table DDL migration (Excel files)
    - View DDL migration (CSV/TXT files)
    - File path updates in DDL statements
    - VDB redeployment to Teiid
    """
    
    def __init__(self, servlet_url=None, base_path=None):
        """
        Initialize VDB Migration Service.
        
        Args:
            servlet_url: URL of the VDBMigrationServlet (optional)
            base_path: Base path for customer folders (optional, for path resolution)
        """
        self.servlet_url = servlet_url or self._get_servlet_url_from_config()
        self.base_path = base_path or self._get_base_path_from_db()

    def _get_servlet_url_from_config(self):
        """Get servlet URL from database configuration or use default.
        
        The servlet URL is stored in the teiid_config table in the 'servlet_url' column.
        This URL points to the VDBManagementServlet (e.g., .../vdb-management).
        We need to replace the endpoint with '/migrate-vdb' for the migration servlet.
        """
        try:
            from redash import models
            import os
            
            # First try environment variable (most reliable)
            env_url = os.environ.get('TEIID_SERVLET_URL')
            if env_url:
                logger.debug("Using TEIID_SERVLET_URL from environment: {}".format(env_url))
                if '/migrate-vdb' not in env_url:
                    return env_url + "/migrate-vdb"
                return env_url
            
            # Query the servlet_url from teiid_config table (same as VDBManagementService)
            try:
                result = models.db.session.execute(
                    "SELECT servlet_url FROM teiid_config WHERE id = 1"
                ).fetchone()
                
                if result and result[0]:
                    url = result[0]
                    logger.info("Using servlet_url from teiid_config: {}".format(url))
                    
                    # The servlet_url points to vdb-management endpoint
                    # We need to replace it with migrate-vdb endpoint
                    # e.g., http://64.52.108.62:8095/TeiidExcelImporterTest/vdb-management
                    #    -> http://64.52.108.62:8095/TeiidExcelImporterTest/migrate-vdb
                    if '/vdb-management' in url:
                        migration_url = url.replace('/vdb-management', '/migrate-vdb')
                        logger.info("Converted to migration URL: {}".format(migration_url))
                        return migration_url
                    elif '/migrate-vdb' in url:
                        return url
                    else:
                        # Just append /migrate-vdb if no known endpoint found
                        return url + "/migrate-vdb"
                else:
                    logger.debug("No servlet_url found in teiid_config table")
            except Exception as e:
                logger.debug("Could not query servlet_url: {}".format(str(e)))
                # Rollback to clear any failed transaction state
                try:
                    models.db.session.rollback()
                except:
                    pass
        except Exception as e:
            logger.debug("Could not get servlet URL from config: {}".format(str(e)))
        return DEFAULT_SERVLET_URL
    
    def _get_base_path_from_db(self):
        """Get customer base path from database configuration."""
        try:
            from redash import models
            import os
            
            # First try environment variable (most reliable)
            env_path = os.environ.get('TEIID_CUSTOMER_BASE_PATH')
            if env_path:
                logger.debug("Using TEIID_CUSTOMER_BASE_PATH from environment: {}".format(env_path))
                return env_path
            
            result = models.db.session.execute(
                "SELECT customer_base_path FROM teiid_config WHERE id = 1"
            ).fetchone()
            if result and result[0]:
                return result[0]
        except Exception as e:
            logger.debug("Could not get base path from config: {}".format(str(e)))
            # Rollback to clear any failed transaction state
            try:
                from redash import models
                models.db.session.rollback()
            except:
                pass
        return '/opt/wildfly/teiidfiles/customers'
    
    def _detect_file_type(self, file_path):
        """Detect file type from file path extension."""
        if not file_path:
            return 'excel'
        lower_path = file_path.lower()
        if lower_path.endswith('.csv') or lower_path.endswith('.txt'):
            return 'csv_txt'
        return 'excel'
    
    def _call_servlet(self, payload):
        """
        Call the VDBMigrationServlet via HTTP POST.
        
        Args:
            payload: Dictionary to send as JSON
            
        Returns:
            Response dictionary from servlet
            
        Raises:
            VDBMigrationError: If servlet call fails
        """
        logger.info("Calling VDB migration servlet: {}".format(self.servlet_url))
        logger.debug("Payload: {}".format(payload))
        
        try:
            if requests:
                # Use requests library (preferred)
                response = requests.post(
                    self.servlet_url,
                    json=payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=SERVLET_TIMEOUT
                )
                response_data = response.json()
                
                if response.status_code != 200:
                    error_msg = response_data.get('message', 'Unknown error')
                    raise VDBMigrationError("Servlet returned error: {}".format(error_msg))
                
                return response_data
                
            elif urllib2:
                # Fallback for Python 2 without requests
                import json
                data = json.dumps(payload).encode('utf-8')
                req = urllib2.Request(
                    self.servlet_url,
                    data=data,
                    headers={'Content-Type': 'application/json'}
                )
                response = urllib2.urlopen(req, timeout=SERVLET_TIMEOUT)
                response_data = json.loads(response.read().decode('utf-8'))
                
                if response_data.get('status') != 'success':
                    error_msg = response_data.get('message', 'Unknown error')
                    raise VDBMigrationError("Servlet returned error: {}".format(error_msg))
                
                return response_data
            else:
                raise VDBMigrationError("No HTTP library available (requests or urllib2)")
                
        except VDBMigrationError:
            raise
        except Exception as e:
            logger.error("Failed to call VDB migration servlet: {}".format(str(e)))
            raise VDBMigrationError("Failed to call VDB migration servlet: {}".format(str(e)))

    def migrate_to_shared_vdb(self, org_id, user_id, datasources, queries=None, migration_logger=None):
        """
        Migrate foreign tables and views from private VDB to shared VDB.
        
        This method calls the VDBMigrationServlet which handles:
        1. Extract DDL from private VDB (FOREIGN TABLE or VIEW)
        2. Update file paths in DDL (private -> shared)
        3. Add DDL to shared VDB
        4. Remove DDL from private VDB
        5. Redeploy both VDBs to Teiid
        
        Args:
            org_id: Organization ID
            user_id: User ID (VDB owner)
            datasources: List of DataSource objects to migrate
            queries: List of Query objects to migrate (optional, for logging)
            migration_logger: MigrationLogger instance (optional)
            
        Raises:
            VDBNotFoundError: If VDB files cannot be found
            VDBMigrationError: If migration fails
        """
        log = migration_logger.log_info if migration_logger else logger.info
        log_warn = migration_logger.log_warning if migration_logger else logger.warning
        
        log("Starting VDB migration to shared for user {} in org {}".format(user_id, org_id))
        
        # Build datasource list for servlet
        ds_list = []
        for ds in datasources:
            if not ds.private_file_path or not ds.shared_file_path:
                log_warn("Skipping datasource {} - missing file paths".format(ds.name))
                continue
            
            # Get the foreign table name (may differ from datasource name)
            foreign_table_name = self._get_foreign_table_name(ds)
            file_type = self._detect_file_type(ds.private_file_path)
            
            ds_list.append({
                'foreign_table_name': foreign_table_name,
                'private_file_path': self._extract_relative_path(ds.private_file_path),
                'shared_file_path': self._extract_relative_path(ds.shared_file_path),
                'file_type': file_type
            })
            
            if migration_logger:
                migration_logger.log_vdb_operation('prepare', 'private', foreign_table_name, success=True)
        
        if not ds_list:
            log_warn("No datasources to migrate")
            return
        
        log("Migrating {} datasources via servlet".format(len(ds_list)))
        
        # Call servlet
        payload = {
            'org_id': org_id,
            'user_id': user_id,
            'migration_type': 'to_shared',
            'datasources': ds_list
        }
        
        try:
            result = self._call_servlet(payload)
            
            tables_migrated = result.get('data', {}).get('tables_migrated', 0)
            views_migrated = result.get('data', {}).get('views_migrated', 0)
            
            log("VDB migration complete: {} tables, {} views migrated".format(
                tables_migrated, views_migrated
            ))
            
            # Log individual operations
            if migration_logger:
                for ds_info in ds_list:
                    migration_logger.log_vdb_operation('migrate', 'shared', ds_info['foreign_table_name'], success=True)
            
        except VDBMigrationError as e:
            if migration_logger:
                migration_logger.log_error(e, context="servlet_migration")
            raise

    def migrate_to_private_vdb(self, org_id, user_id, datasources, queries=None, migration_logger=None):
        """
        Migrate foreign tables and views from shared VDB back to private VDB.
        
        This is the reverse of migrate_to_shared_vdb.
        
        Args:
            org_id: Organization ID
            user_id: User ID (VDB owner)
            datasources: List of DataSource objects to migrate
            queries: List of Query objects to migrate (optional, for logging)
            migration_logger: MigrationLogger instance (optional)
            
        Raises:
            VDBNotFoundError: If VDB files cannot be found
            VDBMigrationError: If migration fails
        """
        log = migration_logger.log_info if migration_logger else logger.info
        log_warn = migration_logger.log_warning if migration_logger else logger.warning
        
        log("Starting VDB migration to private for user {} in org {}".format(user_id, org_id))
        
        # Build datasource list for servlet
        ds_list = []
        for ds in datasources:
            if not ds.private_file_path or not ds.shared_file_path:
                log_warn("Skipping datasource {} - missing file paths (private: {}, shared: {})".format(
                    ds.name, ds.private_file_path, ds.shared_file_path
                ))
                continue
            
            foreign_table_name = self._get_foreign_table_name(ds)
            file_type = self._detect_file_type(ds.shared_file_path)
            
            ds_list.append({
                'foreign_table_name': foreign_table_name,
                'private_file_path': self._extract_relative_path(ds.private_file_path),
                'shared_file_path': self._extract_relative_path(ds.shared_file_path),
                'file_type': file_type
            })
        
        if not ds_list:
            log_warn("No datasources to migrate")
            return
        
        log("Migrating {} datasources back to private via servlet".format(len(ds_list)))
        
        # Call servlet
        payload = {
            'org_id': org_id,
            'user_id': user_id,
            'migration_type': 'to_private',
            'datasources': ds_list
        }
        
        try:
            result = self._call_servlet(payload)
            
            tables_migrated = result.get('data', {}).get('tables_migrated', 0)
            views_migrated = result.get('data', {}).get('views_migrated', 0)
            
            log("VDB migration complete: {} tables, {} views migrated back to private".format(
                tables_migrated, views_migrated
            ))
            
        except VDBMigrationError as e:
            if migration_logger:
                migration_logger.log_error(e, context="servlet_migration")
            raise
    
    def _get_foreign_table_name(self, datasource):
        """
        Get the foreign table name for a datasource.
        
        The foreign table name may differ from the datasource name.
        For Excel files: filename without extension (e.g., "YTDFringeCost")
        For CSV/TXT files: filename_EXT (e.g., "sales_CSV")
        
        Args:
            datasource: DataSource object
            
        Returns:
            Foreign table name string
        """
        # Check if datasource has a foreign_table_name attribute
        if hasattr(datasource, 'foreign_table_name') and datasource.foreign_table_name:
            return datasource.foreign_table_name
        
        # Derive from file path
        file_path = datasource.private_file_path or datasource.shared_file_path
        if file_path:
            filename = os.path.basename(file_path)
            name, ext = os.path.splitext(filename)
            name = name.replace(' ', '_')
            
            # CSV/TXT files use VIEW with name_EXT format
            if ext.lower() in ['.csv', '.txt']:
                return "{}_{}".format(name, ext[1:].upper())
            else:
                # Excel files use FOREIGN TABLE with just the name
                return name
        
        # Fallback to datasource name
        return datasource.name.replace(' ', '_')

    def _extract_relative_path(self, full_path):
        """
        Extract relative path from full path for servlet.
        
        Converts: /opt/wildfly/teiidfiles/customers/33/77/uploads/file.xlsx
        To: 33/77/uploads/file.xlsx
        
        Args:
            full_path: Full file path
            
        Returns:
            Relative path from customers directory
        """
        if not full_path:
            return full_path
        
        # Look for "customers/" and extract everything after it
        customers_marker = "customers/"
        idx = full_path.find(customers_marker)
        if idx != -1:
            return full_path[idx + len(customers_marker):]
        
        # If no customers marker, return as-is (might already be relative)
        return full_path
    
    # =========================================================================
    # Legacy methods for backward compatibility
    # These methods are kept for any code that still uses the old API
    # =========================================================================
    
    def _get_private_vdb_path(self, org_id, user_id):
        """
        Get path to user's private VDB file.
        
        Note: This method is kept for backward compatibility.
        The servlet handles VDB path resolution internally.
        """
        try:
            from redash import models
            result = models.db.session.execute(
                """
                SELECT vdb_id FROM user_vdbs 
                WHERE user_id = :user_id AND organization_id = :org_id
                """,
                {'user_id': user_id, 'org_id': org_id}
            ).fetchone()
            
            if not result:
                raise VDBNotFoundError("No private VDB found for user {}".format(user_id))
            
            vdb_id = result[0]
            vdb_path = os.path.join(
                self.base_path, str(org_id), str(user_id), 'vdb',
                '{}-vdb.xml'.format(vdb_id)
            )
            
            if not os.path.exists(vdb_path):
                raise VDBNotFoundError("Private VDB file not found: {}".format(vdb_path))
            
            return vdb_path
            
        except VDBNotFoundError:
            raise
        except Exception as e:
            raise VDBNotFoundError("Failed to get private VDB path: {}".format(str(e)))
    
    def _get_shared_vdb_path(self, org_id):
        """
        Get path to organization's shared VDB file.
        
        Searches in two locations (in order):
        1. {base_path}/{org_id}/shared/vdb/ (new structure for shared projects)
        2. {base_path}/{org_id}/vdb/ (legacy structure)
        
        Note: This method is kept for backward compatibility.
        The servlet handles VDB path resolution internally.
        """
        try:
            import os
            
            # First try the shared VDB directory (new structure)
            shared_vdb_dir = os.path.join(self.base_path, str(org_id), 'shared', 'vdb')
            if os.path.exists(shared_vdb_dir) and os.path.isdir(shared_vdb_dir):
                vdb_files = [f for f in os.listdir(shared_vdb_dir) if f.endswith('-vdb.xml')]
                if vdb_files:
                    vdb_path = os.path.join(shared_vdb_dir, vdb_files[0])
                    logger.info("Found shared VDB in shared/vdb directory: {}".format(vdb_path))
                    return vdb_path
            
            # Fallback to organization VDB directory (legacy structure)
            from redash import models
            result = models.db.session.execute(
                """
                SELECT vdb_id FROM organization_vdbs 
                WHERE organization_id = :org_id
                """,
                {'org_id': org_id}
            ).fetchone()
            
            if not result:
                raise VDBNotFoundError("No shared VDB found for organization {}".format(org_id))
            
            vdb_id = result[0]
            vdb_path = os.path.join(
                self.base_path, str(org_id), 'vdb',
                '{}-vdb.xml'.format(vdb_id)
            )
            
            if not os.path.exists(vdb_path):
                raise VDBNotFoundError("Shared VDB file not found: {}".format(vdb_path))
            
            logger.info("Found shared VDB in org vdb directory (legacy): {}".format(vdb_path))
            return vdb_path
            
        except VDBNotFoundError:
            raise
        except Exception as e:
            raise VDBNotFoundError("Failed to get shared VDB path: {}".format(str(e)))
