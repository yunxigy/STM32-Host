#!/usr/bin/env bash
set -Eeuo pipefail

# 共享服务器部署：这台机器上还跑着工具箱、股票等模块，80 端口和站点
# Nginx 由站点统一入口管理。本脚本只负责 STM32 上位机自己那一份：
#
#   1. 运行账号、Python 虚拟环境、/etc/stm32-host/4G.env
#   2. 构建前端并发布到 /var/www/stm32-host/stm32
#   3. 注册 stm32-4g.service（8007/8008/8017/8018）
#   4. 安装 /etc/nginx/snippets/stm32-host.conf（不生成 server 块、不重载 Nginx）
#
# 用法：bash deploy/install-linux-shared.sh <站点域名或IP> [http|https]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=install-linux.sh
source "$SCRIPT_DIR/install-linux.sh"

STATIC_ROOT=/var/www/stm32-host
SNIPPET=/etc/nginx/snippets/stm32-host.conf
ENV_FILE=/etc/stm32-host/4G.env

ensure_env_default() {
    local file key value
    file="$1"
    key="$2"
    value="$3"
    grep -q "^${key}=" "$file" || printf '%s=%s\n' "$key" "$value" >>"$file"
}

configure_env() {
    install -d -m 0750 -o root -g stm32 /etc/stm32-host
    # configure_runtime 已按模板生成过，这里只校正与站点相关的两项。
    if grep -q '^STM32_ALLOWED_ORIGINS=' "$ENV_FILE"; then
        sed -i "s|^STM32_ALLOWED_ORIGINS=.*|STM32_ALLOWED_ORIGINS=${site_scheme}://${site_host}|" \
            "$ENV_FILE"
    else
        printf 'STM32_ALLOWED_ORIGINS=%s://%s\n' "$site_scheme" "$site_host" >>"$ENV_FILE"
    fi
    # 老版本安装文件里没有 RTCM 段，补齐而不是覆盖。
    ensure_env_default "$ENV_FILE" STM32_RTCM_ENABLED 1
    ensure_env_default "$ENV_FILE" STM32_RTCM_PORT_IN 8017
    ensure_env_default "$ENV_FILE" STM32_RTCM_PORT_OUT 8018
    chown root:stm32 "$ENV_FILE"
    chmod 0640 "$ENV_FILE"
}

install_unit() {
    install -m 0644 "$SCRIPT_DIR/stm32-4g.service" /etc/systemd/system/stm32-4g.service
    install -m 0644 "$SCRIPT_DIR/stm32-host.logrotate" /etc/logrotate.d/stm32-host
    systemctl daemon-reload
    systemctl enable stm32-4g.service >/dev/null 2>&1 || true
    systemctl restart stm32-4g.service
}

install_snippet() {
    install -d -m 0755 /etc/nginx/snippets
    install -m 0644 "$SCRIPT_DIR/snippets/stm32-host.conf" "$SNIPPET"
    printf 'Nginx 片段已写入 %s\n请在站点 server 块内加一行：include %s;\n' "$SNIPPET" "$SNIPPET"
    printf '然后执行 nginx -t && systemctl reload nginx（片段本身不会自动生效）。\n'
}

allow_shared_firewall() {
    # 80/443 由站点统一管理，这里只放行设备直连的 TCP 端口。
    if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
        firewall-cmd --permanent --add-port=8008/tcp
        firewall-cmd --permanent --add-port=8017/tcp
        firewall-cmd --permanent --add-port=8018/tcp
        firewall-cmd --reload
    elif command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
        ufw allow 8008/tcp
        ufw allow 8017/tcp
        ufw allow 8018/tcp
    fi
}

verify_local() {
    local attempt
    for attempt in {1..20}; do
        if curl --fail --silent --show-error --max-time 2 http://127.0.0.1:8007/data >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8007/data >/dev/null ||
        fail "后台未就绪，请执行 journalctl -u stm32-4g -n 100。"
    [[ -f "$STATIC_ROOT/stm32v2/index.html" ]] ||
        fail "页面未发布到 $STATIC_ROOT/stm32，请检查前端构建输出。"
    bash "$SCRIPT_DIR/verify-local.sh"
}

main() {
    local app_root node_arch python_bin step
    if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
        echo "用法：bash deploy/install-linux-shared.sh <站点域名或IP> [http|https]"
        echo "只安装 STM32 模块，不改动站点 80 端口与 server 块。"
        return
    fi
    [[ "$#" -ge 1 && "$#" -le 2 ]] ||
        fail "参数：<站点域名或IP> [http|https]，例如 example.com https"
    site_host="$1"
    site_scheme="${2:-https}"
    validate_host "$site_host" || fail "只填写域名或 IPv4，不加协议、端口或路径。"
    [[ "$site_scheme" == http || "$site_scheme" == https ]] || fail "协议只能是 http 或 https。"

    [[ "$(uname -s)" == Linux ]] || fail "此安装程序用于 Linux 服务器。"
    [[ "$(id -u)" == 0 ]] || fail "请使用 root 账号运行。"
    [[ -d /run/systemd/system ]] || fail "当前环境没有运行 systemd，无法注册开机服务。"
    app_root="$(cd "$SCRIPT_DIR/.." && pwd -P)"
    [[ "$app_root" == /opt/stm32-host ]] || fail "请将仓库克隆到 /opt/stm32-host 后运行。"
    case "$(uname -m)" in
        x86_64) node_arch=x64 ;;
        aarch64|arm64) node_arch=arm64 ;;
        *) fail "当前架构不在自动安装范围内：$(uname -m)" ;;
    esac

    install -d -m 0755 /var/log/stm32-host
    exec > >(tee -a /var/log/stm32-host/install-shared.log) 2>&1
    step="检查 Python 与设备端口"
    trap 'printf "\n部署在“%s”失败（第 %s 行）。日志：/var/log/stm32-host/install-shared.log（此时站点 Nginx 未被改动）\n" "$step" "$LINENO" >&2' ERR

    printf '\n=== STM32 模块（共享服务器模式）：%s，站点 %s://%s ===\n' \
        "$(date -Is)" "$site_scheme" "$site_host"

    choose_python
    if command -v ss >/dev/null 2>&1; then
        check_device_ports
    else
        echo "未安装 iproute2（ss），跳过端口占用检查。"
    fi
    command -v curl >/dev/null 2>&1 || fail "需要 curl 做自检：apt-get install -y curl"

    step="创建运行账号与 Python 环境"
    configure_runtime
    configure_env

    step="准备 Node.js"
    prepare_node
    printf '前端构建使用 Node.js %s\n' "$(node --version)"

    step="构建并发布监测页面"
    publish_frontend

    step="注册后台服务"
    install_unit

    step="安装 Nginx 片段"
    install_snippet

    step="放行设备端口"
    allow_shared_firewall

    step="本地自检"
    verify_local

    printf '\n模块部署完成（站点 Nginx 尚未改动）\n'
    printf '页面：%s://%s/stm32v2/（需先 include 片段并 reload）\n' "$site_scheme" "$site_host"
    printf '设备：%s:8008 基准站：%s:8017 流动站：%s:8018\n' "$site_host" "$site_host" "$site_host"
    echo "云安全组需放行 TCP 8008、8017、8018（80/443 由站点统一入口负责）。"
    echo "后台日志：journalctl -u stm32-4g -f"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
