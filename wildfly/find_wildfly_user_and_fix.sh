#!/bin/bash
# Find WildFly user and fix file permissions

echo "=== Finding WildFly User and Fixing Permissions ==="
echo ""

echo "1. Check what user WildFly is running as:"
ps aux | grep wildfly | grep -v grep | head -1
WILDFLY_USER=$(ps aux | grep wildfly | grep -v grep | head -1 | awk '{print $1}')
echo "WildFly is running as user: $WILDFLY_USER"
echo ""

echo "2. Current file ownership:"
ls -lah /opt/wildfly/teiidfiles/customers/1/uploads/SalesJournalYTD3.xlsx
echo ""

if [ -n "$WILDFLY_USER" ]; then
    echo "3. Changing file ownership to $WILDFLY_USER..."
    chown $WILDFLY_USER /opt/wildfly/teiidfiles/customers/1/uploads/SalesJournalYTD3.xlsx
    chmod 644 /opt/wildfly/teiidfiles/customers/1/uploads/SalesJournalYTD3.xlsx
    
    echo "4. New file ownership:"
    ls -lah /opt/wildfly/teiidfiles/customers/1/uploads/SalesJournalYTD3.xlsx
    echo ""
    
    echo "5. Also fix folder permissions:"
    chown -R $WILDFLY_USER /opt/wildfly/teiidfiles/customers/1/uploads/
    chmod 755 /opt/wildfly/teiidfiles/customers/1/uploads/
    echo ""
    
    echo "6. Verify folder permissions:"
    ls -ld /opt/wildfly/teiidfiles/customers/1/uploads/
    echo ""
else
    echo "ERROR: Could not determine WildFly user"
    echo "Making file world-readable as fallback..."
    chmod 644 /opt/wildfly/teiidfiles/customers/1/uploads/SalesJournalYTD3.xlsx
fi

echo "=== Testing VDB Query ==="
/opt/wildfly/bin/jboss-cli.sh --connect --controller=64.52.108.62:10000 \
  --command="/subsystem=teiid:execute-query(vdb-name=vdb_production, vdb-version=1, sql-query=\"SELECT * FROM MyCompany.SalesJournalYTD3_XLSX LIMIT 5\", timeout-in-milli=30000)"

echo ""
echo "=== Fix Complete ==="
