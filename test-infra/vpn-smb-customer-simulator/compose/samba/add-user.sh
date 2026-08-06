#!/usr/bin/env sh
set -eu

# The password is injected at runtime and is never committed.
PASS="${SAMBA_PASSWORD:?SAMBA_PASSWORD is required}"

echo -e "${PASS}\n${PASS}" | smbpasswd -a -s tablescope_ro

exec smbd -F --no-process-group
