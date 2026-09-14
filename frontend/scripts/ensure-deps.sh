#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ ! -d "/tmp/omnigent_repo/node_modules" ]; then
  echo "Setting up Omnigent dependencies in /tmp/omnigent_repo..."
  if [ ! -d "/tmp/omnigent_repo" ]; then
    git clone --depth 1 https://github.com/omnigent-ai/omnigent /tmp/omnigent_repo
  fi
  if ! command -v pnpm &>/dev/null; then
    npm install -g pnpm
  fi
  (cd /tmp/omnigent_repo && pnpm install --shamefully-hoist)
fi

# Ensure frontend/node_modules symlink points to /tmp/omnigent_repo/node_modules
cd "$FRONTEND_DIR"
if [ ! -L "node_modules" ] || [ ! -e "node_modules" ]; then
  rm -rf node_modules
  ln -s /tmp/omnigent_repo/node_modules node_modules
fi
