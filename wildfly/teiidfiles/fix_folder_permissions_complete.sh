#!/bin/bash

echo "=========================================="
echo "COMPLETE FOLDER PERMISSIONS FIX"
echo "=========================================="

echo ""
echo "This script will:"
echo "  1. Set permissions to 2777 (rwxrwsrwx) with setgid bit"
echo "  2. Ensure new files/folders inherit group ownership"
echo "  3. Allow both redash and wildfly users to access files"
echo ""

echo "Step 1: Fix existing folder permissions..."
echo ""

# Set permissions on customers folder and all subfolders
sudo find /opt/wildfly/teiidfiles/customers -type d -exec chmod 2777 {} \;
echo "✓ Set all directories to 2777 (with setgid bit)"

# Set permissions on existing files
sudo find /opt/wildfly/teiidfiles/customers -type f -exec chmod 666 {} \;
echo "✓ Set all files to 666 (rw-rw-rw-)"

echo ""
echo "Step 2: Verify permissions..."
echo ""

echo "Customers folder:"
ls -la /opt/wildfly/teiidfiles/customers/

echo ""
echo "Organization 1 folder:"
ls -la /opt/wildfly/teiidfiles/customers/1/

echo ""
echo "Uploads folder:"
ls -la /opt/wildfly/teiidfiles/customers/1/uploads/ 2>/dev/null || echo "  (not created yet)"

echo ""
echo "VDB folder:"
ls -la /opt/wildfly/teiidfiles/customers/1/vdb/ 2>/dev/null || echo "  (not created yet)"

echo ""
echo "Step 3: Check setgid bit..."
echo ""

# Check if setgid bit is set (should show 's' in group execute position)
stat -c "%A %n" /opt/wildfly/teiidfiles/customers/1/ 2>/dev/null || stat -f "%Sp %N" /opt/wildfly/teiidfiles/customers/1/

echo ""
echo "Expected: drwxrwsrwx (note the 's' in group position)"
echo ""

echo "=========================================="
echo "PERMISSIONS FIX COMPLETE"
echo "=========================================="

echo ""
echo "What the setgid bit (2777) does:"
echo "  - The 's' in 'rwxrwsrwx' is the setgid bit"
echo "  - New files/folders created in this directory will inherit the group"
echo "  - Both redash and wildfly users can read/write if they share the group"
echo ""

echo "Next steps:"
echo "  1. Deploy updated Python code: bash DEPLOY_PERMISSION_FIX_NOW.sh"
echo "  2. Deploy updated Java servlet: bash deploy_all_6_fixes.sh"
echo "  3. Test file upload"
echo "  4. Test VDB provisioning"
echo ""
