#!/bin/bash
# Entrypoint for the Teiid/WildFly container.
#
# User VDBs live in the mounted volume (teiidfiles/customers/**/vdb/*.xml) and
# are deployed at runtime by the servlet.  They are intentionally NOT baked into
# standalone-teiid.xml (the content blobs are not in the image, so baking the
# <deployments> refs causes a fatal boot loop on every rebuild).  To keep
# existing tenants working across image rebuilds, this entrypoint re-deploys all
# VDBs found in the volume once the server is up.
set -e

WF_USER="${TEIID_ADMIN_USER:-admin}"
WF_PASS="${TEIID_ADMIN_PASSWORD:-admin}"
CUSTOMERS_DIR=/opt/wildfly/teiidfiles/customers

/opt/wildfly/bin/standalone.sh \
    -c standalone-teiid.xml \
    -b 0.0.0.0 \
    -bmanagement 0.0.0.0 &
WF_PID=$!

redeploy_vdbs() {
    # Wait until the management interface reports the server is running.
    for _ in $(seq 1 60); do
        if /opt/wildfly/bin/jboss-cli.sh --connect --user="$WF_USER" --password="$WF_PASS" \
                --command=":read-attribute(name=server-state)" 2>/dev/null | grep -q '"running"'; then
            break
        fi
        sleep 5
    done

    find "$CUSTOMERS_DIR" -name "*-vdb.xml" 2>/dev/null | while read -r f; do
        n=$(basename "$f")
        echo "[entrypoint] deploying VDB $n"
        /opt/wildfly/bin/jboss-cli.sh --connect --user="$WF_USER" --password="$WF_PASS" \
            --command="deploy $f --name=$n --force" 2>&1 | tail -1 || true
    done
}

redeploy_vdbs &

wait "$WF_PID"
