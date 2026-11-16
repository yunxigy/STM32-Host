#!/usr/bin/env bash
set -Eeuo pipefail

# New standalone Linux installation. Re-run after git pull to update.
# Only the entrypoint invokes main, so helpers can be checked safely.

fail() {
    printf '错误：%s\n' "$*" >&2
    exit 1
}

validate_host() {
    [[ "$1" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*[a-zA-Z0-9]$ ]] &&
        [[ "$1" != *..* ]] && [[ "$1" != *.-* ]] && [[ "$1" != *-.* ]]
}

node_is_usable() {
    "$1" -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit((major === 22 && minor >= 13) || major >= 24 ? 0 : 1)' >/dev/null 2>&1
}

install_packages() {
    if command -v apt-get >/dev/null 2>&1; then
        DEBIAN_FRONTEND=noninteractive apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y \
            git curl ca-certificates python3 python3-venv python3-pip \
            nginx xz-utils tar coreutils iproute2 util-linux logrotate
    else
        local manager
        manager="$(command -v dnf || command -v yum)"
        "$manager" install -y git curl ca-certificates python3 python3-pip \
            nginx xz tar coreutils iproute util-linux logrotate policycoreutils-python-utils
    fi
}

choose_python() {
    local candidate
    for candidate in python3.11 python3.12 python3.13 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1 &&
            "$candidate" -c 'import sys, venv; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            python_bin="$(command -v "$candidate")"
            return
        fi
    done

    # RHEL-family repositories may offer 3.11 alongside an older system Python.
    if command -v dnf >/dev/null 2>&1; then
        dnf install -y python3.11 python3.11-pip
        if python3.11 -c 'import venv' 2>/dev/null; then
            python_bin="$(command -v python3.11)"
            return
        fi
    fi
    fail "需要 Python 3.10+ 和 venv/pip。请安装 Python 3.11 后重新执行；系统 Python 未被替换。"
}

check_device_ports() {
    local main_pid port listeners pid
    main_pid="$(systemctl show stm32-4g.service --property=MainPID --value 2>/dev/null || true)"
    for port in 8007 8008 8017 8018; do
        listeners="$(ss -H -ltnp "sport = :$port")"
        if [[ -z "$listeners" ]]; then
            continue
        fi
        while IFS= read -r pid; do
            if [[ -z "$main_pid" || "$main_pid" == 0 || "$pid" != "$main_pid" ]]; then
                printf '%s\n' "$listeners" >&2
                fail "端口 $port 已被其他进程占用。请确认旧服务后再重试。"
            fi
        done < <(printf '%s\n' "$listeners" | grep -oE 'pid=[0-9]+' | cut -d= -f2)
        if ! printf '%s\n' "$listeners" | grep -q 'pid='; then
            fail "无法识别端口 $port 的占用者：$listeners"
        fi
    done
}

prepare_node() {
    local candidate download_dir archive node_dir node_version
    if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 &&
        node_is_usable "$(command -v node)" &&
        runuser -u stm32 -- env "PATH=$PATH" npm --version >/dev/null 2>&1; then
        return
    fi
    for candidate in "$app_root"/.runtime/node-v22.*-linux-"$node_arch"/bin; do
        if [[ -x "$candidate/npm" ]] && node_is_usable "$candidate/node"; then
            export PATH="$candidate:$PATH"
            return
        fi
    done

    install -d -m 0755 "$app_root/.runtime"
    download_dir="$(mktemp -d /tmp/stm32-node.XXXXXXXX)"
    curl --fail --location --retry 2 --connect-timeout 15 --max-time 120 \
        https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt -o "$download_dir/SHASUMS256.txt"
    archive="$(awk -v arch="$node_arch" '$2 ~ "^node-v22\\.[0-9]+\\.[0-9]+-linux-" arch "\\.tar\\.xz$" {print $2; exit}' "$download_dir/SHASUMS256.txt")"
    [[ "$archive" =~ ^node-v22\.[0-9]+\.[0-9]+-linux-(x64|arm64)\.tar\.xz$ ]] ||
        fail "Node.js 官方清单中未找到当前架构。临时文件：$download_dir"
    node_dir="$(basename "$archive" .tar.xz)"
    node_version="${node_dir#node-}"
    node_version="${node_version%-linux-*}"
    curl --fail --location --retry 2 --connect-timeout 15 --max-time 600 \
        "https://nodejs.org/dist/$node_version/$archive" -o "$download_dir/$archive"
    awk -v file="$archive" '$2 == file {print}' "$download_dir/SHASUMS256.txt" > "$download_dir/node.sha256"
    (cd "$download_dir" && sha256sum --check node.sha256)
    tar -xJf "$download_dir/$archive" -C "$app_root/.runtime"
    export PATH="$app_root/.runtime/$node_dir/bin:$PATH"
    node_is_usable "$(command -v node)" ||
        fail "下载的 Node.js 无法运行，请检查系统 GLIBC 版本。"
    rm -- "$download_dir/$archive" "$download_dir/SHASUMS256.txt" "$download_dir/node.sha256"
    rmdir -- "$download_dir"
}

configure_runtime() {
    local nologin
    chmod 0755 "$app_root" "$app_root/4G"
    chmod 0644 "$app_root/4G/4G.py" "$app_root/4G/gnss_filter.py" "$app_root/4G/requirements.txt"
    nologin="$(command -v nologin || true)"
    [[ -n "$nologin" ]] || nologin=/bin/false
    if ! id stm32 >/dev/null 2>&1; then
        useradd --system --home-dir /var/lib/stm32-host --shell "$nologin" stm32
    fi
    install -d -m 0750 -o stm32 -g stm32 /var/lib/stm32-host \
        /var/lib/stm32-host/gnss_runtime /var/cache/stm32-host
    install -d -m 0750 -o root -g stm32 /etc/stm32-host
    install -d -m 0755 -o stm32 -g stm32 "$app_root/4G/.venv"
    if [[ ! -f /etc/stm32-host/4G.env ]]; then
        sed "s|http://your-domain.example|http://$site_host|" \
            "$app_root/deploy/stm32-host.env.example" > /etc/stm32-host/4G.env
        chown root:stm32 /etc/stm32-host/4G.env
        chmod 0640 /etc/stm32-host/4G.env
    fi
    runuser -u stm32 -- "$python_bin" -m venv "$app_root/4G/.venv"
    runuser -u stm32 -- "$app_root/4G/.venv/bin/python" -m pip install \
        -r "$app_root/4G/requirements.txt"
    runuser -u stm32 -- "$app_root/4G/.venv/bin/python" -c \
        'import eventlet, flask, flask_cors, flask_sock; print("Python dependencies: OK")'
}

publish_frontend() {
    local npm_registry
    if [[ ! -f "$app_root/.env.local" ]]; then
        install -m 0640 -o root -g stm32 "$app_root/.env.local.example" "$app_root/.env.local"
    else
        chgrp stm32 "$app_root/.env.local"
        chmod g+r "$app_root/.env.local"
    fi
    chown -R stm32:stm32 "$app_root/frontend"
    npm_registry="${STM32_NPM_REGISTRY:-https://registry.npmjs.org}"
    (
        cd "$app_root/frontend"
        runuser -u stm32 -- env "PATH=$PATH" \
            npm_config_cache=/var/cache/stm32-host/npm \
            "npm_config_registry=$npm_registry" npm ci
        runuser -u stm32 -- env "PATH=$PATH" npm run build
    )
    install -d -m 0755 /var/www/stm32-host/stm32v2
    cp -R "$app_root/frontend/dist/." /var/www/stm32-host/stm32v2/
    find /var/www/stm32-host -type d -exec chmod 0755 {} +
    find /var/www/stm32-host -type f -exec chmod 0644 {} +
}

configure_services() {
    local backup_dir
    backup_dir="/var/backups/stm32-host/config-$(date +%Y%m%d-%H%M%S)"
    install -d -m 0700 "$backup_dir"
    if [[ -f /etc/nginx/conf.d/stm32-host.conf ]]; then
        cp -p /etc/nginx/conf.d/stm32-host.conf "$backup_dir/nginx-stm32-host.conf"
    fi
    if [[ -f /etc/systemd/system/stm32-4g.service ]]; then
        cp -p /etc/systemd/system/stm32-4g.service "$backup_dir/stm32-4g.service"
    fi
    sed "s|your-domain.example|$site_host|g" \
        "$app_root/deploy/nginx-stm32-host.conf" > /etc/nginx/conf.d/stm32-host.conf
    install -m 0644 "$app_root/deploy/stm32-4g.service" /etc/systemd/system/stm32-4g.service
    install -m 0644 "$app_root/deploy/stm32-host.logrotate" /etc/logrotate.d/stm32-host

    if command -v getenforce >/dev/null 2>&1 && [[ "$(getenforce)" != Disabled ]]; then
        command -v setsebool >/dev/null 2>&1 && command -v semanage >/dev/null 2>&1 ||
            fail "SELinux 启用但缺少管理工具，请安装 policycoreutils-python-utils 后重跑。"
        setsebool -P httpd_can_network_connect 1
        semanage fcontext -a -t httpd_log_t '/var/log/stm32-host(/.*)?' 2>/dev/null ||
            semanage fcontext -m -t httpd_log_t '/var/log/stm32-host(/.*)?'
        restorecon -RF /var/www/stm32-host /var/log/stm32-host
    fi

    nginx -t
    systemctl daemon-reload
    systemctl enable stm32-4g.service nginx.service
    systemctl restart stm32-4g.service
    if systemctl is-active --quiet nginx.service; then
        systemctl reload nginx.service
    else
        systemctl start nginx.service
    fi
}

allow_active_firewall() {
    if command -v firewall-cmd >/dev/null 2>&1 &&
        firewall-cmd --state >/dev/null 2>&1; then
        firewall-cmd --permanent --add-port=80/tcp
        firewall-cmd --permanent --add-port=8008/tcp
        firewall-cmd --permanent --add-port=8017/tcp
        firewall-cmd --permanent --add-port=8018/tcp
        firewall-cmd --reload
    elif command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
        ufw allow 80/tcp
        ufw allow 8008/tcp
        ufw allow 8017/tcp
        ufw allow 8018/tcp
    fi
}

verify_installation() {
    local attempt ready
    ready=0
    for attempt in {1..20}; do
        if curl --fail --silent --show-error --max-time 2 \
            http://127.0.0.1:8007/data >/dev/null 2>&1; then
            ready=1
            break
        fi
        sleep 1
    done
    [[ "$ready" == 1 ]] || fail "后台未就绪，请执行 journalctl -u stm32-4g -n 100。"
    bash "$app_root/deploy/verify-local.sh"
    curl --fail --silent --show-error --max-time 10 \
        -H "Host: $site_host" http://127.0.0.1/stm32v2/ >/dev/null
    curl --fail --silent --show-error --max-time 10 \
        -H "Host: $site_host" http://127.0.0.1/stm32v2/api/data >/dev/null
}

main() {
    local app_root site_host node_arch python_bin step
    if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
        echo "用法：bash deploy/install-linux.sh <服务器公网IPv4或域名>"
        echo "在 /opt/stm32-host 中以 root 运行；安装后访问 http://该地址/stm32v2/"
        return
    fi
    [[ "$#" == 1 ]] || fail "请填写服务器公网 IP 或域名，例如：bash deploy/install-linux.sh 203.0.113.10"
    site_host="$1"
    validate_host "$site_host" || fail "只填写公网 IPv4 或域名，不加 http://、端口或路径。"
    [[ "$(uname -s)" == Linux ]] || fail "此安装程序用于 Linux 服务器。"
    [[ "$(id -u)" == 0 ]] || fail "请使用 root 账号运行。"
    umask 0022
    app_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
    [[ "$app_root" == /opt/stm32-host ]] || fail "请将仓库克隆到 /opt/stm32-host 后运行。"
    [[ -d /run/systemd/system ]] || fail "当前环境没有运行 systemd，无法注册开机服务。"
    [[ ! -x /www/server/nginx/sbin/nginx ]] ||
        fail "检测到宝塔 Nginx，与系统 Nginx 的配置路径不同。请保留环境检测结果后调整部署。"
    command -v apt-get >/dev/null 2>&1 || command -v dnf >/dev/null 2>&1 ||
        command -v yum >/dev/null 2>&1 || fail "未找到 apt/dnf/yum。"
    case "$(uname -m)" in
        x86_64) node_arch=x64 ;;
        aarch64|arm64) node_arch=arm64 ;;
        *) fail "当前架构不在自动安装范围内：$(uname -m)" ;;
    esac

    install -d -m 0755 /var/log/stm32-host
    exec > >(tee -a /var/log/stm32-host/install.log) 2>&1
    step="安装系统依赖"
    trap 'printf "\n安装在“%s”失败（第 %s 行）。日志：/var/log/stm32-host/install.log\n" "$step" "$LINENO" >&2' ERR
    printf '\n=== STM32 监测平台：%s，访问主机：%s ===\n' "$(date -Is)" "$site_host"
    install_packages
    step="检查 Python 与设备端口"
    choose_python
    check_device_ports
    step="安装 Python 服务依赖"
    configure_runtime
    step="准备 Node.js"
    prepare_node
    printf '前端构建使用 Node.js %s\n' "$(node --version)"
    step="构建并发布监测页面"
    publish_frontend
    step="注册并启动后台与 Nginx"
    configure_services
    step="配置已启用的主机防火墙"
    allow_active_firewall
    step="检查服务与页面"
    verify_installation
    printf '\n部署完成\n页面：http://%s/stm32v2/\n设备：%s:8008（TCP）\n基准站：%s:8017（TCP）\n流动站：%s:8018（TCP）\n' \
        "$site_host" "$site_host" "$site_host" "$site_host"
    echo "请在云安全组放行 TCP 80、8008、8017 和 8018。"
    echo "后台日志：journalctl -u stm32-4g -f"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
