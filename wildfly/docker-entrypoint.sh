#!/bin/bash
# Entrypoint for the Teiid/WildFly container.
#
# User VDBs live in the mounted volume (teiidfiles/customers/**/vdb/*.xml) and
# are deployed at runtime by the servlet.  They are intentionally NOT baked into
# standalone-teiid.xml (the content blobs are not in the image, so baking the
# <deployments> refs causes a fatal boot loop on every rebuild).  To keep
# existing tenants working across image rebuilds, this entrypoint re-deploys all
# VDBs found in the volume once the server is up.
#
# VDBManagementServlet's deleteVDB archives a deleted VDB's XML by moving it to
# <vdb-folder>/archive/<vdbId>-vdb.xml rather than removing it, so it is still
# under CUSTOMERS_DIR and still matches *-vdb.xml. Every `find` below that walks
# CUSTOMERS_DIR for VDB files MUST exclude */archive/* -- otherwise both the
# startup redeploy pass and the periodic reconcile loop treat every archived
# (intentionally deleted) VDB as "missing from deployments" and silently
# redeploy it forever, permanently resurrecting deleted VDBs and leaking
# deployed-VDB state on the shared Teiid instance across restarts.
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

    find "$CUSTOMERS_DIR" -name "*-vdb.xml" -not -path '*/archive/*' 2>/dev/null | while read -r f; do
        deploy_vdb_file "$f"
    done

    # Once the initial VDB redeploy pass is done, start the health watchdog
    # so it does not race with this first-pass deployment.
    pool_health_loop &
}

test_pool() {
    local ra="$1" cdef="$2"
    /opt/wildfly/bin/jboss-cli.sh --connect --user="$WF_USER" --password="$WF_PASS" \
        --command="/subsystem=resource-adapters/resource-adapter=$ra/connection-definitions=$cdef:test-connection-in-pool" 2>/dev/null \
        | grep -q '"result" => \[true\]'
}

flush_pool() {
    local ra="$1" cdef="$2"
    echo "[entrypoint] flushing pool $cdef"
    /opt/wildfly/bin/jboss-cli.sh --connect --user="$WF_USER" --password="$WF_PASS" \
        --command="/subsystem=resource-adapters/resource-adapter=$ra/connection-definitions=$cdef:flush-all-connection-in-pool" >/dev/null 2>&1 || true
}

list_deployed_vdbs() {
    /opt/wildfly/bin/jboss-cli.sh --connect --user="$WF_USER" --password="$WF_PASS" \
        --output-json --command="/deployment=*:read-attribute(name=runtime-name)" 2>/dev/null \
        | grep -oE '"[^"]+-vdb\.xml"' \
        | sed 's/"//g' \
        | sort -u
}

deploy_vdb_file() {
    local f="$1" n
    n=$(basename "$f")
    echo "[entrypoint] deploying VDB $n"
    /opt/wildfly/bin/jboss-cli.sh --connect --user="$WF_USER" --password="$WF_PASS" \
        --command="deploy $f --name=$n --force" 2>&1 | tail -1 || true
}

reconcile_missing_vdbs() {
    local deployed_file missing_file
    deployed_file=$(mktemp)
    list_deployed_vdbs > "$deployed_file" || true

    while IFS= read -r f; do
        n=$(basename "$f")
        if ! grep -qx "$n" "$deployed_file"; then
            echo "[entrypoint] VDB $n missing from deployments; redeploying"
            deploy_vdb_file "$f"
        fi
    done < <(find "$CUSTOMERS_DIR" -name "*-vdb.xml" -not -path '*/archive/*' 2>/dev/null)

    rm -f "$deployed_file"
}

pool_health_loop() {
    # Wait until the management interface reports the server is running.
    for _ in $(seq 1 60); do
        if /opt/wildfly/bin/jboss-cli.sh --connect --user="$WF_USER" --password="$WF_PASS" \
                --command=":read-attribute(name=server-state)" 2>/dev/null | grep -q '"running"'; then
            break
        fi
        sleep 5
    done

    local interval="${TEIID_POOL_HEALTH_INTERVAL:-60}"
    local vdb_reconcile_interval="${TEIID_VDB_RECONCILE_INTERVAL:-300}"
    local max_fail=3
    local file_fail=0 excel_fail=0 remote_fail=0
    local next_vdb_reconcile=0

    while true; do
        local now
        now=$(date +%s)
        if [ "$now" -ge "$next_vdb_reconcile" ]; then
            reconcile_missing_vdbs
            next_vdb_reconcile=$(( now + vdb_reconcile_interval ))
        fi

        if ! test_pool "file" "fileDS"; then
            echo "[entrypoint] fileDS connection test failed"
            flush_pool "file" "fileDS"
            if ! test_pool "file" "fileDS"; then
                file_fail=$((file_fail + 1))
                echo "[entrypoint] fileDS still failing after flush ($file_fail/$max_fail)"
                if [ "$file_fail" -ge "$max_fail" ]; then
                    echo "[entrypoint] restarting WildFly due to persistent fileDS failures"
                    kill -TERM "$WF_PID" 2>/dev/null || true
                    return
                fi
            else
                file_fail=0
                echo "[entrypoint] fileDS recovered after flush"
            fi
        else
            file_fail=0
        fi

        if ! test_pool "file" "excelDS"; then
            echo "[entrypoint] excelDS connection test failed"
            flush_pool "file" "excelDS"
            if ! test_pool "file" "excelDS"; then
                excel_fail=$((excel_fail + 1))
                if [ "$excel_fail" -ge "$max_fail" ]; then
                    echo "[entrypoint] restarting WildFly due to persistent excelDS failures"
                    kill -TERM "$WF_PID" 2>/dev/null || true
                    return
                fi
            else
                excel_fail=0
            fi
        else
            excel_fail=0
        fi

        if ! test_pool "remote-file" "remote-file-ds"; then
            echo "[entrypoint] remote-file-ds connection test failed"
            flush_pool "remote-file" "remote-file-ds"
            if ! test_pool "remote-file" "remote-file-ds"; then
                remote_fail=$((remote_fail + 1))
                if [ "$remote_fail" -ge "$max_fail" ]; then
                    echo "[entrypoint] restarting WildFly due to persistent remote-file-ds failures"
                    kill -TERM "$WF_PID" 2>/dev/null || true
                    return
                fi
            else
                remote_fail=0
            fi
        else
            remote_fail=0
        fi

        sleep "$interval"
    done
}

redeploy_vdbs &

wait "$WF_PID"
