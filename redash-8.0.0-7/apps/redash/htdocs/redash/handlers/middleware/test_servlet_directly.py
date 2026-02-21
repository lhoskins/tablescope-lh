#!/usr/bin/env python
"""
Test the Teiid servlet directly to diagnose VDB provisioning issues
"""
import sys
import os
import requests
import json

# Add the current directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from redash import create_app
from redash.models import db

def test_servlet():
    """Test the Teiid servlet directly"""
    app = create_app()
    
    with app.app_context():
        print("=" * 80)
        print("TEIID SERVLET DIAGNOSTIC TEST")
        print("=" * 80)
        
        # Get Teiid config from database
        print("\n1. LOADING TEIID CONFIGURATION:")
        result = db.session.execute(
            """
            SELECT servlet_url, servlet_api_key, teiid_host, teiid_port, 
                   customer_base_path, template_vdb_name, vdb_enabled
            FROM teiid_config 
            WHERE id = 1
            """
        ).fetchone()
        
        if not result:
            print("   ❌ No Teiid configuration found in database!")
            print("   Run: python run_teiid_config_migration.sql")
            return
        
        servlet_url, api_key, teiid_host, teiid_port, base_path, template_name, enabled = result
        
        print("   ✅ Configuration loaded:")
        print("      Servlet URL: {}".format(servlet_url))
        print("      Teiid Host: {}".format(teiid_host))
        print("      Teiid Port: {}".format(teiid_port))
        print("      Base Path: {}".format(base_path))
        print("      Template VDB: {}".format(template_name))
        print("      Enabled: {}".format(enabled))
        
        if not enabled:
            print("   ⚠️  VDB provisioning is DISABLED in config!")
        
        # Test servlet connectivity
        print("\n2. TESTING SERVLET CONNECTIVITY:")
        try:
            response = requests.get(servlet_url.replace('/vdb-management', '/health'), timeout=5)
            print("   ✅ Servlet is reachable (status: {})".format(response.status_code))
        except requests.exceptions.Timeout:
            print("   ❌ Servlet connection timed out")
            return
        except requests.exceptions.RequestException as e:
            print("   ❌ Cannot reach servlet: {}".format(str(e)))
            return
        
        # Test VDB creation with test data
        print("\n3. TESTING VDB CREATION:")
        
        test_payload = {
            'template_vdb': template_name,
            'new_vdb_id': 'test_vdb_diagnostic',
            'username': 'test_user',
            'password': 'test_password_123',
            'vdb_folder': '{}/customers/999/vdb'.format(base_path),
            'uploads_folder': '{}/customers/999/uploads'.format(base_path)
        }
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        if api_key:
            headers['X-API-Key'] = api_key
        
        print("   Sending test request to: {}/createVDB".format(servlet_url))
        print("   Payload:")
        print("      template_vdb: {}".format(test_payload['template_vdb']))
        print("      new_vdb_id: {}".format(test_payload['new_vdb_id']))
        print("      vdb_folder: {}".format(test_payload['vdb_folder']))
        print("      uploads_folder: {}".format(test_payload['uploads_folder']))
        
        try:
            response = requests.post(
                '{}/createVDB'.format(servlet_url),
                json=test_payload,
                headers=headers,
                timeout=30
            )
            
            print("\n   Response Status: {}".format(response.status_code))
            print("   Response Body: {}".format(response.text))
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    print("   ✅ VDB creation SUCCESSFUL!")
                else:
                    print("   ❌ VDB creation FAILED: {}".format(result.get('error')))
            else:
                print("   ❌ Servlet returned error status: {}".format(response.status_code))
                
                # Try to parse error details
                try:
                    error_data = response.json()
                    print("   Error details: {}".format(json.dumps(error_data, indent=2)))
                except:
                    print("   Raw error: {}".format(response.text))
                    
        except requests.exceptions.Timeout:
            print("   ❌ Request timed out after 30 seconds")
        except requests.exceptions.RequestException as e:
            print("   ❌ Request failed: {}".format(str(e)))
        
        # Check template VDB file
        print("\n4. CHECKING TEMPLATE VDB FILE:")
        template_path = '{}/{}'.format(base_path, template_name)
        print("   Expected path: {}".format(template_path))
        print("   ⚠️  Cannot check file existence from Python (need SSH access)")
        print("   Run this on WildFly server:")
        print("      ls -la {}".format(template_path))
        
        # Provide troubleshooting steps
        print("\n" + "=" * 80)
        print("TROUBLESHOOTING STEPS")
        print("=" * 80)
        
        if response.status_code == 500:
            print("\n❌ Servlet returned 500 error. Common causes:")
            print("\n1. Template VDB file not found:")
            print("   SSH to WildFly server and check:")
            print("      ls -la {}/{}".format(base_path, template_name))
            print("   If missing, copy it:")
            print("      scp MyVDBTest-vdb.xml user@wildfly:{}".format(base_path))
            
            print("\n2. Template VDB file has wrong format:")
            print("   Check the XML file is valid VDB format")
            print("   Check file permissions (should be readable by WildFly user)")
            
            print("\n3. WildFly/Teiid server issue:")
            print("   Check WildFly logs:")
            print("      tail -f /opt/wildfly/standalone/log/server.log")
            
            print("\n4. Servlet code issue:")
            print("   Check servlet logs for detailed error")
            print("   The 'null' error suggests a NullPointerException in servlet")
            
            print("\n5. Customer folder doesn't exist:")
            print("   Check if base path exists:")
            print("      ls -la {}".format(base_path))
            print("      ls -la {}/customers".format(base_path))
        
        print("\n" + "=" * 80)

if __name__ == '__main__':
    test_servlet()
