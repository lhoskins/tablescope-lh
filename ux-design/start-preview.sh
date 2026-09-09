#!/usr/bin/env bash
# One command to resume local UI preview work.
# Run from anywhere: ./ux-design/start-preview.sh
set -e
cd "$(dirname "$0")/../web-ui"
echo "→ starting Next.js dev server in $(pwd)"
echo "→ open http://localhost:3000/projects once it says 'Ready'"
npm run dev
