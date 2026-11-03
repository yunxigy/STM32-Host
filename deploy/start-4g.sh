#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="$(printenv STM32_HOST_ROOT 2>/dev/null || true)"
if [ -z "$APP_ROOT" ]; then
    APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

ENV_FILE="$(printenv STM32_ENV_FILE 2>/dev/null || true)"
if [ -n "$ENV_FILE" ]; then
    if [ ! -r "$ENV_FILE" ]; then
        echo "Environment file is not readable: $ENV_FILE" >&2
        exit 1
    fi
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
fi

PYTHON_BIN="$(printenv PYTHON_BIN 2>/dev/null || true)"
if [ -z "$PYTHON_BIN" ]; then
    PYTHON_BIN="$APP_ROOT/4G/.venv/bin/python"
fi
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3 2>/dev/null || true)"
fi
if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
    echo "No usable Python interpreter. Create 4G/.venv or set PYTHON_BIN." >&2
    exit 1
fi

if [ ! -f "$APP_ROOT/4G/4G.py" ] || [ ! -f "$APP_ROOT/4G/gnss_filter.py" ]; then
    echo "4G.py or gnss_filter.py is missing under: $APP_ROOT/4G" >&2
    exit 1
fi

if [ -z "$(printenv PYTHONUNBUFFERED 2>/dev/null || true)" ]; then
    export PYTHONUNBUFFERED=1
fi

cd "$APP_ROOT/4G"
echo "Starting STM32 Host from $APP_ROOT"
echo "Python: $PYTHON_BIN"
exec "$PYTHON_BIN" 4G.py
