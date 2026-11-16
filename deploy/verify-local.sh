#!/usr/bin/env bash
set -Eeuo pipefail

API_URL="$(printenv STM32_API_URL 2>/dev/null || true)"
if [ -z "$API_URL" ]; then
    API_URL="http://127.0.0.1:8007"
fi

PUBLIC_URL=""
if [ "$#" -ge 1 ]; then
    PUBLIC_URL="$1"
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required." >&2
    exit 1
fi

echo "Checking API: $API_URL/data"
DATA="$(curl --fail --silent --show-error --max-time 10 "$API_URL/data")"
if [ -x /opt/stm32-host/4G/.venv/bin/python ]; then
    PYTHON_BIN=/opt/stm32-host/4G/.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    echo "Python is required for JSON and device TCP checks." >&2
    exit 1
fi
printf '%s\n' "$DATA" | "$PYTHON_BIN" -c 'import json, sys; value=json.load(sys.stdin); assert isinstance(value.get("devices"), dict), "missing devices"; print("JSON ok; devices:", len(value["devices"]))'

TCP_PORT="$(printenv STM32_TCP_PORT 2>/dev/null || true)"
if [ -z "$TCP_PORT" ]; then TCP_PORT=8008; fi
"$PYTHON_BIN" -c 'import socket, sys; connection=socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=3); connection.close(); print("Device TCP: OK")' "$TCP_PORT"

echo "Checking alarm settings: $API_URL/alarm-settings"
curl --fail --silent --show-error --max-time 10 "$API_URL/alarm-settings" >/dev/null
echo "Alarm settings endpoint: OK"

if command -v ss >/dev/null 2>&1; then
    echo "Current listeners:"
    ss -ltnp 2>/dev/null | grep -E ':(8007|8008)([[:space:]]|$)' || true
fi

if [ -n "$PUBLIC_URL" ]; then
    echo "Checking public page: $PUBLIC_URL/stm32v2/"
    curl --fail --silent --show-error --head "$PUBLIC_URL/stm32v2/" | sed -n '1,8p'
fi

echo "Local checks passed. A response with zero devices is normal until a device connects."
