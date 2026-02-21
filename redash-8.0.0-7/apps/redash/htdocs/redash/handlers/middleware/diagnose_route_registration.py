#!/usr/bin/env python
"""
Diagnostic script to check if VDB routes are being registered.

Run this on the Redash server to check route registration.
"""

import sys
sys.path.insert(0, '/opt/redash/current')  # Adjust path as needed

print("=" * 80)
print("DIAGNOSING VDB ROUTE REGISTRATION")
print("=" * 80)
print()

# Step 1: Check if organization_vdb module can be imported
print("Step 1: Importing organization_vdb module...")
try:
    from redash.handlers import organization_vdb
    print("SUCCESS: organization_vdb module imported")
    print("   - OrganizationVDBResource:", hasattr(organization_vdb, 'OrganizationVDBResource'))
    print("   - VDBCredentialRotationResource:", hasattr(organization_vdb, 'VDBCredentialRotationResource'))
    print("   - VDBHealthCheckResource:", hasattr(organization_vdb, 'VDBHealthCheckResource'))
except Exception as e:
    print("FAILED: Could not import organization_vdb")
    print("   Error:", str(e))
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# Step 2: Check if api module can be imported
print("Step 2: Importing api module...")
try:
    from redash.handlers import api as api_module
    print("SUCCESS: api module imported")
    print("   - api object:", hasattr(api_module, 'api'))
except Exception as e:
    print("FAILED: Could not import api module")
    print("   Error:", str(e))
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# Step 3: Check if routes are registered on the api object
print("Step 3: Checking routes on api object...")
try:
    from redash.handlers.api import api
    
    # Flask-RESTful stores resources internally
    print("   API object type:", type(api))
    print("   API resources:", len(api.resources) if hasattr(api, 'resources') else 'N/A')
    
    # Check if our endpoints are registered
    if hasattr(api, 'resources'):
        vdb_endpoints = [r for r in api.resources if 'vdb' in str(r).lower()]
        print("   VDB-related resources:", len(vdb_endpoints))
        for resource in vdb_endpoints:
            print("     -", resource)
    
except Exception as e:
    print("FAILED: Could not check api routes")
    print("   Error:", str(e))
    import traceback
    traceback.print_exc()

print()

# Step 4: Create a test Flask app and check routes
print("Step 4: Creating test Flask app...")
try:
    from redash import create_app
    app = create_app()
    
    print("SUCCESS: Flask app created")
    print()
    print("Registered routes:")
    print("-" * 80)
    
    vdb_routes_found = False
    for rule in app.url_map.iter_rules():
        rule_str = str(rule)
        if 'vdb' in rule_str.lower():
            methods = ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
            print("*** VDB ROUTE: {} -> {} [{}]".format(rule.rule, rule.endpoint, methods))
            vdb_routes_found = True
    
    if not vdb_routes_found:
        print("NO VDB ROUTES FOUND!")
        print()
        print("All routes:")
        for rule in app.url_map.iter_rules():
            methods = ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
            print("  {} -> {} [{}]".format(rule.rule, rule.endpoint, methods))
    
except Exception as e:
    print("FAILED: Could not create Flask app")
    print("   Error:", str(e))
    import traceback
    traceback.print_exc()

print()
print("=" * 80)
print("DIAGNOSIS COMPLETE")
print("=" * 80)
