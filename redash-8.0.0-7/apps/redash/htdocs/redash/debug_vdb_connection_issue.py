#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Debug VDB Connection Issue

This script tests the exact code path that Redash uses to get VDB connection.
"""

import os
import sys

# Add redash to path
sys.path.insert(0, os.path.dirname(__file__))

def debug_vdb_connection():
    print("=" * 70)
    print("VDB Connection Debug Tool")
    print("=" * 70)
    print("")
    
    # Test 1: Check settings
    print("[1] Checking VDB_MULTI_TENANCY_ENABLED setting...")
    try:
        from redash import settings
        vdb_enabled = getattr(settings, 'VDB_MULTI_TENANCY_ENABLED', False)
        print("  VDB_MULTI_TENANCY_ENABLED: {}".format(vdb_enabled))
        
        if not vdb_enabled:
            print("  WARNING: VDB multi-tenancy is DISABLED")
            print("  This means the system will use REDASH_VIRTUALDATABASE_URL")
            print("")
    except Exception as e:
        print("  ERROR: {}".format(e))
        print("")
    
    # Test 2: Check if table exists
    print("[2] Checking organization_vdbs table...")
    try:
        from redash.models.organization_vdb import OrganizationVDB
        count = OrganizationVDB.query.count()
        print("  Table exists: YES")
        print("  Total VDB records: {}".format(count))
        print("")
    except Exception as e:
        print("  ERROR: {}".format(e))
        print("  Table may not exist or model not loaded")
        print("")
    
    # Test 3: Get VDB for org 1
    print("[3] Getting VDB for organization 1...")
    try:
        from redash.services.vdb_context import VDBContextService
        from redash.models.organization_vdb import OrganizationVDB
        
        print("  Calling: OrganizationVDB.get_by_organization(1)")
        vdb_config = OrganizationVDB.get_by_organization(1)
        
        if vdb_config:
            print("  SUCCESS: VDB found!")
            print("    - ID: {}".format(vdb_config.id))
            print("    - VDB ID: {}".format(vdb_config.vdb_id))
            print("    - Host: {}".format(vdb_config.vdb_host))
            print("    - Port: {}".format(vdb_config.vdb_port))
            print("    - Username: {}".format(vdb_config.vdb_username))
            print("    - Active: {}".format(vdb_config.is_active))
            print("")
        else:
            print("  FAILED: No VDB found for organization 1")
            print("")
            print("  Checking all VDBs in database...")
            all_vdbs = OrganizationVDB.query.all()
            print("  Total VDBs: {}".format(len(all_vdbs)))
            for vdb in all_vdbs:
                print("    - Org {}: {} (active: {})".format(
                    vdb.organization_id, vdb.vdb_id, vdb.is_active
                ))
            print("")
            return
            
    except Exception as e:
        print("  ERROR: {}".format(e))
        import traceback
        traceback.print_exc()
        print("")
        return
    
    # Test 4: Get connection parameters
    print("[4] Getting connection parameters...")
    try:
        from redash.services.vdb_context import VDBContextService
        
        print("  Calling: VDBContextService.get_vdb_connection_params(1)")
        params = VDBContextService.get_vdb_connection_params(1)
        
        print("  SUCCESS: Connection parameters generated!")
        print("    - DSN: {}".format(params['dsn']))
        print("    - User: {}".format(params['user']))
        print("    - Password: {}".format('*' * len(params['password'])))
        print("    - VDB ID: {}".format(params['vdb_id']))
        print("    - Host: {}".format(params['host']))
        print("    - Port: {}".format(params['port']))
        print("")
        
        # Verify DSN format
        if params['dsn'].startswith('postgresql://'):
            print("  [OK] DSN format is correct (PostgreSQL)")
        else:
            print("  [ERROR] DSN format is WRONG: {}".format(params['dsn']))
        print("")
        
    except Exception as e:
        print("  ERROR: {}".format(e))
        import traceback
        traceback.print_exc()
        print("")
        return
    
    # Test 5: Test query runner connection logic
    print("[5] Testing query runner connection logic...")
    try:
        from redash.query_runner.external import ExternalDataSource
        
        # Create a query runner instance
        runner = ExternalDataSource({})
        
        print("  Checking _get_default_connection() method...")
        database_url = os.getenv("REDASH_VIRTUALDATABASE_URL")
        if database_url:
            print("    REDASH_VIRTUALDATABASE_URL: {}".format(database_url))
            
            if database_url.startswith('postgresql://'):
                print("    [OK] Format is correct (PostgreSQL)")
            elif database_url.startswith('jdbc:teiid:'):
                print("    [ERROR] Format is WRONG (JDBC) - this will cause errors!")
            else:
                print("    [UNKNOWN] Unknown format")
        else:
            print("    REDASH_VIRTUALDATABASE_URL: NOT SET")
            print("    This is OK if VDB multi-tenancy is enabled")
        print("")
        
    except Exception as e:
        print("  ERROR: {}".format(e))
        import traceback
        traceback.print_exc()
        print("")
    
    # Summary
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print("")
    
    if vdb_config and params:
        print("[SUCCESS] VDB configuration looks correct!")
        print("")
        print("If you're still getting 'Database connection string is missing':")
        print("")
        print("1. Check which user/organization you're logged in as")
        print("2. Verify the organization ID matches (currently testing org 1)")
        print("3. Check Redash logs for more details:")
        print("   tail -f /var/log/redash/redash.log")
        print("")
        print("4. Try disabling VDB multi-tenancy temporarily:")
        print("   VDB_MULTI_TENANCY_ENABLED=false")
        print("   Then restart: supervisorctl restart redash_server")
    else:
        print("[FAILED] VDB configuration has issues - see errors above")
    
    print("")
    print("=" * 70)

if __name__ == '__main__':
    debug_vdb_connection()
