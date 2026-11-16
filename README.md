# STM32 上位机监测平台

用于 STM32/4G 设备的实时监测：传感器数据、在线状态、地图、GNSS 滤波与位移、云端告警阈值和设备指令。前端和后端在本仓库独立启动。

## 在新服务器上部署

完整操作请按 [新服务器部署手册](./DEPLOYMENT.md) 执行。你可以直接从这个独立 Git 仓库拉取。

安装 Git 后，在 Linux 服务器使用 root 执行，将示例 IP 换成自己的公网 IP：

~~~bash
git clone --branch main https://github.com/yunxigy/STM32-Host.git /opt/stm32-host
cd /opt/stm32-host
bash deploy/install-linux.sh 203.0.113.10
~~~

脚本安装依赖、构建页面，配置 Nginx 和后台开机启动。浏览器访问 `http://你的公网IP/stm32v2/`，测点设备连接 `你的公网IP:8008`，基准站连接 `8017`，流动站连接 `8018`。

如果这台服务器还要跑工具箱、股票等模块，不要用上面的独立安装脚本（它会占用 80 端口）。改用 `bash deploy/install-linux-shared.sh`，只装后台服务和页面，页面入口并入站点统一 Nginx，详见 [部署手册](../部署/README.md)。

地图配置、云安全组、更新、日志和排障均写在 [DEPLOYMENT.md](./DEPLOYMENT.md) 中。

## 目录

| 目录 | 用途 |
| --- | --- |
| `frontend/` | 当前监测前端 |
| `4G/` | 设备 TCP、HTTP/WebSocket、云端告警与 GNSS 服务 |
| `deploy/` | 平台安装、启动和检查程序 |
| `wangye/` | 历史提取包和兼容测试，部署入口使用 frontend + 4G |

## 本地开发

开发机使用 Python 3.11，以及 Node.js 22.13+ 或 24+。先在仓库根目录准备地图配置：

~~~powershell
Copy-Item .env.local.example .env.local
~~~

填写 `VITE_AMAP_KEY` 和 `VITE_AMAP_SECURITY_CODE`。启动后台：

~~~powershell
Set-Location 4G
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe 4G.py
~~~

另开终端，从仓库根目录启动前端：

~~~powershell
Set-Location frontend
npm ci
npm run dev
~~~

浏览器打开 `http://127.0.0.1:8016/stm32v2/`。开发代理将 `/stm32v2/api/` 的 HTTP 和 WebSocket 转发到 8007，设备连接 TCP 8008，基准站连接 8017，流动站连接 8018。

后端使用进程环境变量 `STM32_HTTP_PORT`、`STM32_TCP_PORT`、`STM32_RTCM_PORT_IN`、`STM32_RTCM_PORT_OUT`、`STM32_RTCM_ENABLED`、`STM32_ALLOWED_ORIGINS`、`STM32_GNSS_STATE_DIR` 和 `STM32_ALARM_SETTINGS_PATH`；默认在 `4G/gnss_runtime/` 和 `4G/alarm_settings.json` 保存状态。生产安装程序将状态放在 `/var/lib/stm32-host/`。

## 测试和构建

在 `4G/` 目录：

~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'
~~~

在 `frontend/` 目录：

~~~powershell
npm run lint
npm test
npm run build
~~~

前端产物为 `frontend/dist/`。数据接口为 `GET /data`、`WS /ws`、`GET/PUT /alarm-settings` 和 `GET /send_cmd`。GNSS 算法说明见 [4G/GNSS_ALGORITHM.md](./4G/GNSS_ALGORITHM.md)。

## RTCM 差分中继

基准站把 RTCM3 差分数据发到 8017，后台解码切帧后转发给连在 8018 的流动站：

| 端口 | 方向 | 说明 |
| --- | --- | --- |
| 8017 | 基准站 → 服务器 | 收十六进制文本或原始二进制，同时只保留一个基准站 |
| 8018 | 服务器 → 流动站 | 多台流动站被动接收原始二进制，互不影响 |

- 十六进制文本支持 `D3 00 79 ...`、`D30079...`、`d3,00,79` 等写法，也可以直接发原始二进制，后台自动识别。
- 也可以连接后先发一行 `BASE`（或 `BASE,基准站01`）作为握手；若按 `1,D3 00 79 ...` 一帧一行的写法发送，前缀会被自动剥离。
- 收到的数据按 RTCM3 结构（`0xD3` + 10bit 长度 + CRC24Q）切帧，保证流动站不会从帧中间开始接收。
- 新流动站接入时会先补发上一个完整历元，缩短首次 RTK 固定的时间。
- 每台流动站独立队列，慢连接或掉线只丢自己的帧，不会拖累基准站。
- 若长时间解析不出合法 RTCM3 帧，自动降级为原始字节透传，并在页面提示。
- 中继状态见 `GET /rtcm-status`，也包含在 `GET /data` 的 `rtcm` 字段里。
