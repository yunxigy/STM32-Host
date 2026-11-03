#!/usr/bin/env bash
set -u

# Read-only inventory. It does not install packages, change firewall rules,
# stop processes, or modify the application.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT=""
if [ "$#" -ge 1 ]; then
    APP_ROOT="$1"
fi
if [ -z "$APP_ROOT" ]; then
    APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

echo "=== STM32 Host environment check ==="
echo "time: $(date -Is 2>/dev/null || date)"
echo "user: $(id 2>/dev/null || true)"
echo "app root: $APP_ROOT"
echo

if [ -r /etc/os-release ]; then
    OS_NAME="$(grep '^PRETTY_NAME=' /etc/os-release | cut -d= -f2- | sed 's/^"//; s/"$//' || true)"
    echo "os: $OS_NAME"
fi
echo "kernel: $(uname -a 2>/dev/null || true)"
echo "arch: $(uname -m 2>/dev/null || true)"
echo

echo "--- resource summary ---"
if command -v nproc >/dev/null 2>&1; then
    echo "cpu cores: $(nproc)"
fi
if command -v free >/dev/null 2>&1; then
    free -h
else
    echo "free: command not found"
fi
if command -v df >/dev/null 2>&1; then
    df -h "$APP_ROOT" 2>/dev/null || true
fi
echo

echo "--- important commands ---"
for name in git python3 python python3.11 pip3 node npm nginx systemctl ss curl firewall-cmd ufw; do
    if command -v "$name" >/dev/null 2>&1; then
        printf '%-14s %s\n' "$name" "$(command -v "$name")"
        case "$name" in
            nginx) "$name" -v 2>&1 || true ;;
            systemctl) "$name" --version 2>/dev/null | head -n 1 || true ;;
            ss) "$name" --version 2>&1 | head -n 1 || true ;;
            *) "$name" --version 2>&1 | head -n 1 || true ;;
        esac
    else
        printf '%-14s not found\n' "$name"
    fi
done
echo

echo "--- network addresses ---"
if command -v ip >/dev/null 2>&1; then
    ip -brief address 2>/dev/null || true
else
    echo "ip: command not found"
fi
echo

echo "--- listeners: 8007 HTTP/WebSocket, 8008 device TCP, 8016 dev only ---"
if command -v ss >/dev/null 2>&1; then
    for port in 8007 8008 8016; do
        matches="$(ss -ltnp 2>/dev/null | grep -E ":$port([[:space:]]|$)" || true)"
        if [ -n "$matches" ]; then
            echo "port $port:"
            echo "$matches"
        else
            echo "port $port: not listening"
        fi
    done
else
    echo "Install iproute/ss or inspect these ports with the server provider console."
fi
echo

echo "--- systemd ---"
if command -v systemctl >/dev/null 2>&1; then
    systemctl is-system-running 2>&1 || true
    systemctl list-unit-files 'stm32-4g.service' 2>/dev/null || true
else
    echo "systemd not detected"
fi
echo

echo "--- application paths ---"
for path in "$APP_ROOT" "$APP_ROOT/4G/4G.py" "$APP_ROOT/4G/requirements.txt" "$APP_ROOT/frontend" "$APP_ROOT/frontend/dist"; do
    if [ -e "$path" ]; then
        ls -ld "$path"
    else
        echo "missing: $path"
    fi
done
echo

echo "Next: save this output, then follow DEPLOYMENT.md. Do not install or expose"
echo "ports until the OS, public IP/domain, firewall, and device port are known."
