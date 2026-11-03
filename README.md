# STM32-Host · STM32 上位机

STM32 上位机提供浏览器监测界面、4G 设备 TCP 接入、HTTP/WebSocket 数据分发、GNSS 滤波、告警设置和设备指令。前端和后端在本仓库独立启动，不依赖工具箱源码。

仓库根目录直接展示 `frontend/`、`4G/` 和 `wangye/`，当前监测链路为 `frontend + 4G`。

## 功能

- 设备在线状态、选择、传感器和环境数据展示。
- 地图设备标记、轨迹、坐标转换和轨迹导出。
- NMEA/GNSS 数据、RTK 状态、滤波与位移展示。
- 云端告警阈值读取、保存与版本同步。
- WebSocket 实时更新、断线重连及 HTTP 数据读取。
- 设备指令与运行通知。

## 目录结构

```text
STM32-Host/
├── frontend/
│   ├── main.tsx                # 独立页面入口
│   ├── pages/Stm32Window.tsx    # 监测主界面
│   ├── pages/stm32/            # 地图、设备、告警等组件
│   ├── lib/                    # 坐标与位移算法
│   └── vite.config.ts          # /stm32/ 基路径和开发代理
├── 4G/
│   ├── 4G.py                   # 当前监测服务
│   ├── gnss_filter.py          # GNSS 滤波与状态持久化
│   └── tests/
├── wangye/                     # 保留的历史提取包及测试
└── .env.local.example          # 地图配置模板
```

## 通信架构与端口

```text
STM32 / 4G 设备 ─TCP :8008→ 4G.py
                               ├─ HTTP / WebSocket :8007
浏览器 :8016/stm32/ ─开发代理───┘
```

| 端口 | 用途 | 启动位置 |
| --- | --- | --- |
| 8007 | 当前监测 HTTP/WebSocket | `4G/` |
| 8008 | 当前监测设备 TCP | `4G/` |
| 8016 | 独立前端开发服务器 | `frontend/` |

设备连接监测服务时使用 8008；浏览器通过 8007 访问 HTTP/WebSocket 服务。

## 环境要求

- Python 3.11 和 pip，用于监测后端。
- Node.js 22.12+ 和 npm，用于前端开发与构建。
- 高德地图 Web Key 和安全码，用于地图显示；未配置时界面会提示地图未配置。
- 真实设备需自行配置 4G 模块的服务器地址、TCP 端口和透传模式。

## 克隆与启动后端

```powershell
git clone https://github.com/yunxigy/STM32-Host.git
cd STM32-Host/4G
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
$env:STM32_HTTP_PORT='8007'
$env:STM32_TCP_PORT='8008'
./.venv/Scripts/python.exe 4G.py
```

保持此窗口运行。另开窗口检查 HTTP：

```powershell
Invoke-RestMethod http://127.0.0.1:8007/data
```

没有设备连接时，页面不会产生真实遥测数据；需要设备接入后再确认协议、在线状态和传感器值。

## 配置与启动前端

从仓库根目录复制模板，已有配置请直接编辑，避免覆盖：

```powershell
Copy-Item ./.env.local.example ./.env.local
cd frontend
npm ci
npm run dev
```

访问 `http://127.0.0.1:8016/stm32/`。Vite 从仓库根目录读取 `.env.local`，将 `/stm32/api/` 的 HTTP 和 WebSocket 请求转发到 8007。

| 配置项 | 默认或位置 | 说明 |
| --- | --- | --- |
| `VITE_AMAP_KEY` | `.env.local` | 高德 Web Key |
| `VITE_AMAP_SECURITY_CODE` | `.env.local` | 高德 JS API 安全码 |
| `STM32_HTTP_PORT` | 8007 | 后端 HTTP/WebSocket 监听端口 |
| `STM32_TCP_PORT` | 8008 | 设备 TCP 监听端口 |
| `STM32_ALLOWED_ORIGINS` | 后端进程环境 | 逗号分隔的浏览器来源白名单 |
| `STM32_GNSS_STATE_DIR` | `4G/gnss_runtime/` | GNSS 持久化状态目录 |
| `STM32_ALARM_SETTINGS_PATH` | `4G/alarm_settings.json` | 告警阈值文件 |

`VITE_*` 值会进入前端产物，需在地图平台限制允许域名。Python 后端使用进程环境变量，不自动读取前端的 `.env.local`。更改 8007 时需同步修改 Vite/Nginx 代理。

## 设备数据与接口

当前服务处理数字设备编号，以及 `ACC`、`GYRO`、`ANGLE`、温湿度、GGA/NMEA 和告警等文本消息；具体消息格式以 [4G.py](./4G/4G.py) 中的解析规则和 [测试](./4G/tests/) 为准。

| 接口 | 作用 |
| --- | --- |
| `GET /data` | 当前设备状态与遥测快照 |
| `WS /ws` | 实时数据流 |
| `GET /alarm-settings` | 读取云端告警阈值 |
| `PUT /alarm-settings` | 保存阈值并更新版本 |
| `GET /send_cmd` | 设备指令接口，参数见服务实现 |

浏览器通过 `/stm32/api/` 访问以上路径，开发代理会移除该前缀。

GNSS 滤波使用校验有效的 RTK 固定解（GGA quality=4），累计满足条件的 20 个有效历元建立参考。运行状态持久化到 `gnss_runtime/`，重启与升级时应保留；自动化测试不能替代对实际天线、接收机和现场噪声的验证。

## 测试与构建

在 `4G/` 执行：

```powershell
./.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'
```

在 `frontend/` 执行：

```powershell
npm run lint
npm test
npm run build
```

前端产物位于 `frontend/dist/`。`wangye/` 保留历史提取包，当前功能维护入口以 `frontend/` 和 `4G/` 为准。

## 部署监测页面

先构建前端，再用进程管理器守护监测后端。Nginx 需分别处理 API/WebSocket 和静态页面，例如在已有站点 server 块中配置：

```nginx
location ^~ /stm32/api/ {
    proxy_pass http://127.0.0.1:8007/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 86400;
}
location = /stm32 { return 301 /stm32/; }
location ^~ /stm32/ {
    alias /www/wwwroot/STM32-Host/frontend/dist/;
    try_files $uri $uri/ /stm32/index.html;
}
```

按实际主机修改目录、域名和 TLS 配置，先运行 `nginx -t`。设备 TCP 8008 需要单独配置网络连通与访问控制；HTTP 页面能打开并不证明设备端口可达。

## 数据、升级和排障

`gnss_runtime/`、`alarm_settings.json`、真实环境配置和依赖目录不上传 GitHub。更新前停止服务、备份这些数据，再更新源码和依赖。

| 现象 | 排查 |
| --- | --- |
| 页面空数据 | 检查 8007 后端、8008 设备连接与设备编号/消息格式 |
| 地图不显示 | 检查 Key、安全码、域名限制与地图网络请求 |
| WebSocket 不断重连 | 检查 Nginx Upgrade、代理路径和后端监听端口 |
| 有 GGA 但没有滤波参考 | 检查校验和、RTK 固定解质量、连续有效采样与状态目录 |
| 告警重启后丢失 | 检查告警文件路径、持久化磁盘和写入权限 |

相关项目：[工具箱](https://github.com/yunxigy/Star-Dominion)、[守岸人](https://github.com/yunxigy/ShouAnRen)、[股票研究](https://github.com/yunxigy/Stock-Research)。本仓库不包含登录模块和 OpenWrite。
