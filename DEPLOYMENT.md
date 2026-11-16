# 新服务器部署 STM32 上位机监测平台

按本页顺序操作，你可以从 Git 拉取源码，在新服务器运行完整的监测平台。

独立仓库：[yunxigy/STM32-Host](https://github.com/yunxigy/STM32-Host)。安装程序负责 Python 环境、前端构建、Nginx 和后台开机启动。你只需要准备服务器公网 IP，以及显示地图所需的高德 Web Key 和安全码。

## 两种部署模式

| 模式 | 适用 | 命令 | 占用 80 端口 |
| --- | --- | --- | --- |
| 独立部署 | 这台服务器只跑 STM32 上位机 | `bash deploy/install-linux.sh 你的IP` | 是 |
| 共享部署 | 同一台服务器还跑工具箱、股票等模块 | `bash deploy/install-linux-shared.sh 域名 https` | 否 |

共享部署只安装 `stm32-4g` 服务、发布页面到 `/var/www/stm32-host/stm32v2`、写 `/etc/stm32-host/4G.env`、装 Nginx 片段 `/etc/nginx/snippets/stm32-host.conf`，**不改动站点 server 块、不 reload Nginx**。页面入口由站点统一 Nginx 提供 `location /stm32v2/`，完整步骤见仓库外的 `部署/README.md`。

两种模式的端口分配一致：8007（HTTP/WS）、8008（设备）、8017（RTCM 基准站）、8018（RTCM 流动站）。

## 第一步：进入服务器，安装 Git

以下命令在服务器的 Linux 终端执行，使用 root 账号。普通账号先执行 `sudo -i`；已经显示 `root@...` 时直接继续。

安装程序支持使用 apt、dnf 或 yum，且运行 systemd 的 Linux 服务器；自动识别 x86_64 和 ARM64。可以先查看系统：

~~~bash
cat /etc/os-release
uname -m
~~~

复制执行下面一整段，已安装 Git 时会直接跳过：

~~~bash
if ! command -v git >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update && apt-get install -y git
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y git
    elif command -v yum >/dev/null 2>&1; then
        yum install -y git
    else
        echo "未识别软件包管理器，请保留 /etc/os-release 的输出。"
    fi
fi
~~~

## 第二步：从 Git 拉取平台

~~~bash
git clone --branch main https://github.com/yunxigy/STM32-Host.git /opt/stm32-host
cd /opt/stm32-host
~~~

后续命令都以这个目录为准。如果 clone 提示目标已存在，先用 `git -C /opt/stm32-host status` 检查；首次部署请使用空目录。

需要显示地图时，在安装前填写配置：

~~~bash
cp -n .env.local.example .env.local
vi .env.local
~~~

填写两项：

~~~dotenv
VITE_AMAP_KEY=你的高德WebKey
VITE_AMAP_SECURITY_CODE=你的高德安全码
~~~

vi 操作：按 `i` 编辑，完成后按 `Esc`，输入 `:wq`，再回车。高德平台需允许当前访问域名。

地图配置可以稍后再填；留空时平台可以启动，地图区域会提示未配置。补填后重新执行第三步即可。

## 第三步：运行安装程序

把 `203.0.113.10` 替换成你的服务器公网 IP：

~~~bash
cd /opt/stm32-host
bash deploy/install-linux.sh 203.0.113.10
~~~

也可以填写已解析到这台服务器的域名，例如 `monitor.example.com`。只填 IP 或域名，不加 `http://`、端口或路径。

程序依次安装系统依赖、准备 Python 和 Node.js、构建页面、配置 Nginx、注册后台开机启动，并检查 HTTP、设备 TCP 和页面。首次安装需要联网下载依赖。

最后出现“部署完成”和访问地址，表示本机检查通过。安装日志位于 `/var/log/stm32-host/install.log`。

## 第四步：放行端口，打开平台

在云服务器控制台的安全组中添加：

| 协议/端口 | 用途 |
| --- | --- |
| TCP 80 | 浏览器访问平台 |
| TCP 8008 | STM32/4G 设备接入（遥测、告警、指令） |
| TCP 8017 | 基准站上传 RTCM3 差分数据 |
| TCP 8018 | 流动站下载 RTCM3 差分数据 |

如果主机已启用 firewalld 或 UFW，安装程序也会添加这些规则；云安全组仍需你设置。

浏览器打开：

~~~text
http://你的服务器公网IP/stm32v2/
~~~

首次部署使用 HTTP，端口为 80。配置域名证书后再使用 HTTPS。

4G 模块设置：

| 角色 | 服务器地址 | 连接方式 | 服务器端口 |
| --- | --- | --- | --- |
| 测点设备（上报 IMU/GNSS） | 你的服务器公网IP | TCP | 8008 |
| 基准站（上传差分） | 你的服务器公网IP | TCP | 8017 |
| 流动站（接收差分） | 你的服务器公网IP | TCP | 8018 |

基准站从串口收到什么就往 8017 转发什么，十六进制文本（如 `D3 00 79 ...`）和原始二进制都可以，后台会自动识别。流动站连上 8018 后不需要发任何数据，服务器会持续把差分流推给它，并且在新连上时先补发一个完整历元。

设备未接入时数据为空是正常现象。后台 HTTP/WebSocket 的 8007 由 Nginx 转发，云安全组无需开放 8007；8017 和 8018 是纯 TCP 端口，不经过 Nginx，必须由安全组直接放行。

这两个端口是**全站统一分配**的：8009、8010 已被工具箱的研报服务和文档转换服务占用，不要改回去。

平台上「差分中继 RTCM3」面板会显示基准站是否在线、当前码率、电文类型（1006/1033/1074/1124 等）和每台流动站的转发量。出现「基准站无差分数据」通常是 4G 已连通但串口没有数据上送。

## 以后怎样启动、停止、更新

服务器重启后自动启动平台。平时使用：

~~~bash
systemctl status stm32-4g --no-pager
systemctl restart stm32-4g
systemctl stop stm32-4g
systemctl start stm32-4g
~~~

以后更新，仍使用同一个目录，把 IP 换成部署时使用的地址：

~~~bash
cd /opt/stm32-host
git pull --ff-only origin main
bash deploy/install-linux.sh 203.0.113.10
~~~

程序重新构建和启动服务，保留地图配置、告警阈值和 GNSS 状态。更新前备份：

~~~bash
mkdir -p /var/backups/stm32-host
tar -czf /var/backups/stm32-host/data-$(date +%Y%m%d-%H%M%S).tgz \
    /var/lib/stm32-host /etc/stm32-host /opt/stm32-host/.env.local
~~~

## 日志和数据在哪里

后台实时日志：

~~~bash
journalctl -u stm32-4g -f
~~~

最近 100 条日志：

~~~bash
journalctl -u stm32-4g -n 100 --no-pager
tail -n 100 /var/log/stm32-host/nginx-error.log
~~~

| 路径 | 内容 |
| --- | --- |
| `/opt/stm32-host` | Git 拉取的源码 |
| `/opt/stm32-host/.env.local` | 地图配置 |
| `/var/www/stm32-host/stm32v2` | 发布的页面 |
| `/etc/stm32-host/4G.env` | 后台端口和状态路径 |
| `/var/lib/stm32-host/alarm_settings.json` | 全体访问者共用的告警阈值 |
| `/var/lib/stm32-host/gnss_runtime/` | 各设备 GNSS 参考、滤波状态和观测记录 |
| `/var/log/stm32-host/install.log` | 安装和更新日志 |
| `journalctl -u stm32-4g` | 设备接入、解析和后台异常日志 |

告警文件首次保存设置后生成；GNSS 文件在收到相应观测数据后生成。后台日志保留期由系统 journal 配置决定；GNSS 观测文件持续追加，需要按磁盘容量定期归档。

## 遇到问题按这里排查

| 现象 | 检查或处理 |
| --- | --- |
| Git 拉取失败 | 确认服务器能访问 GitHub；私有仓库需先配置 Git 凭据 |
| Python 版本过低或 venv 缺失 | 安装 Python 3.11 及其 venv/pip 后重跑；程序不会替换系统 Python |
| Node.js 报 GLIBC 错误 | 使用较新的 Linux 系统，参见 [Node 22 系统要求](https://github.com/nodejs/node/blob/v22.x/BUILDING.md#platform-list) |
| 下载依赖超时 | 查看安装日志中的失败地址，检查 DNS、出站网络和系统时间后重跑 |
| 安装中断 | 重新执行第三步，已有配置和状态会保留 |
| 端口被占用 | 执行 `ss -ltnp`，先确认占用 8007/8008 的程序 |
| 本机检查正常，外网打不开 | 检查云安全组是否放行 80、公网 IP 是否正确 |
| 打开后是 Nginx 欢迎页 | 安装参数应与浏览器实际使用的 IP/域名一致，改正后重跑第三步 |
| 页面显示 502 | 查看 `systemctl status stm32-4g --no-pager` 和后台日志 |
| 页面有了，但没有设备 | 确认设备主动连接公网 IP 的 TCP 8008，检查安全组和设备连接日志 |
| 设备 2 不显示 | 使用数字编号 2，每条数据以换行结尾；支持 `device_id=2:ACC: ...` 前缀 |
| 地图空白 | 填写根目录 .env.local，确认高德域名配置，再重跑安装程序 |
| 告警设置无法保存 | 检查 `curl -f http://127.0.0.1:8007/alarm-settings`、状态目录权限及后台日志 |
| 有 GNGGA，但没有位移 | 滤波要求有效校验和、RTK 固定解 quality=4 和连续 20 个有效历元；quality=0 不推进参考建立 |

一次收集诊断信息：

~~~bash
cd /opt/stm32-host
bash deploy/check-environment.sh
systemctl status stm32-4g nginx --no-pager
journalctl -u stm32-4g -n 100 --no-pager
tail -n 100 /var/log/stm32-host/install.log
~~~

检测到宝塔 Nginx、非 systemd 环境或不支持的系统时，安装程序会说明原因并退出。保留环境检测和安装日志，再按实际环境调整。
