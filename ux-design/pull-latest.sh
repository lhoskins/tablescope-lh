#!/usr/bin/env bash
# Run this from the tablescope/ folder (or anywhere in the repo) whenever
# you want to bring down Devin's latest pushed changes before reviewing.
# Usage: ./ux-design/pull-latest.sh [branch-name]
# If no branch is given, pulls whatever branch you currently have checked out.
set -e
cd "$(git rev-parse --show-toplevel)"
if [ -n "$1" ]; then
  git fetch origin "$1"
  git checkout "$1"
  git pull origin "$1"
else
  git pull
fi
echo "✓ pulled — prototype-ux.html is up to date, check your browser (live-server should auto-refresh)"
