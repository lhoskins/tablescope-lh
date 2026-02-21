#!/usr/bin/env python
"""
Test script to verify VDB multi-tenancy connection logic.

This script tests the VDB connection parameter generation without
actually connecting to the database.
"""

import os
import sys

# Add redash to path
sys.path.insert(0, os.path.dirname(__file__))

def test_vdb_connection_params():
    """Test VDB connection parameter generation."""
    print("=" * 70)
    print("VDB Multi-Tenancy Connection Logic Test")
    print("=" * 70)
    
    # Import after path is set
    from redash.services.vdb_context import VDBContextService, VDBNotConfiguredError
    from redash.models.organization_vdb import OrganizationVDB
    
    # Test 1: Check if VDB exists for organization 1
    print("\n[Test 1] Checking VDB configuration for organization 1...")
    try:
        vdb_config = VDBContextService.get_vdb_for_organization(1)
        if vdb_config:
            print("✓ VDB found:")
            print("  - VDB ID: {}".format(vdb_config.vdb_id))
            print("  - Host: {}".format(vdb_config.vdb_host))
            print("  - Port: {}".format(vdb_config.vdb_port))
            print("  - Username: {}".format(vdb_config.vdb_username))
            print("  - Active: {}".format(vdb_config.is_active))
        else:
            print("✗ No VDB configured for organization 1")
            print("\nAvailable VDBs in database:")
            all_vdbs = OrganizationVDB.query.all()
            for vdb in all_vdbs:
                print("  - Org {}: {}".format(vdb.organization_id, vdb.vdb_id))
    except Exception as e:
        print("✗ Error: {}".format(e))
    
    # Test 2: Generate connection parameters
    print("\n[Test 2] Generating connection parameters...")
    try:
        params = VDBContextService.get_vdb_connection_params(1)
        print("✓ Connection parameters generated:")
        print("  - DSN: {}".format(params['dsn']))
        print("  - User: {}".format(params['user']))
        print("  - Password: {}".format('*' * len(params['password'])))
        print("  - VDB ID: {}".format(params['vdb_id']))
        print("  - Host: {}".format(params['host']))
        print("  - Port: {}".format(params['port']))
        
        # Verify format
        if params['dsn'].startswith('postgresql://'):
            print("\n✓ DSN format is correct (PostgreSQL format)")
        else:
            print("\n✗ DSN format is WRONG (should start with 'postgresql://')")
            
    except VDBNotConfiguredError as e:
        print("✗ VDB not configured: {}".format(e))
    except Exception as e:
        print("✗ Error: {}".format(e))
        import traceback
        traceback.print_exc()
    
    # Test 3: Check VDB_MULTI_TENANCY_ENABLED setting
    print("\n[Test 3] Checking VDB multi-tenancy settings...")
    try:
        from redash import settings
        vdb_enabled = getattr(settings, 'VDB_MULTI_TENANCY_ENABLED', False)
        print("  - VDB_MULTI_TENANCY_ENABLED: {}".format(vdb_enabled))
        
        if vdb_enabled:
            print("✓ VDB multi-tenancy is ENABLED")
        else:
            print("✗ VDB multi-tenancy is DISABLED")
            print("  Set VDB_MULTI_TENANCY_ENABLED=true in .env file")
    except Exception as e:
        print("✗ Error checking settings: {}".format(e))
    
    print("\n" + "=" * 70)
    print("Test complete")
    print("=" * 70)

if __name__ == '__main__':
    test_vdb_connection_params()
