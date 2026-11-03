#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if ! command -v npm >/dev/null 2>&1; then
    echo "npm is required to build frontend/dist." >&2
    exit 1
fi

cd "$APP_ROOT/frontend"
echo "Installing locked frontend dependencies..."
npm ci
echo "Running TypeScript check..."
npm run lint
echo "Running frontend tests..."
npm test
echo "Building frontend/dist..."
npm run build
echo "Build complete: $APP_ROOT/frontend/dist"
