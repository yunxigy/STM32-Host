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

脚本安装依赖、构建页面，配置 Nginx 和后台开机启动。浏览器访问 `http://你的公网IP/stm32/`，4G 设备连接 `你的公网IP:8008`。

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

浏览器打开 `http://127.0.0.1:8016/stm32/`。开发代理将 `/stm32/api/` 的 HTTP 和 WebSocket 转发到 8007，设备连接 TCP 8008。

后端使用进程环境变量 `STM32_HTTP_PORT`、`STM32_TCP_PORT`、`STM32_ALLOWED_ORIGINS`、`STM32_GNSS_STATE_DIR` 和 `STM32_ALARM_SETTINGS_PATH`；默认在 `4G/gnss_runtime/` 和 `4G/alarm_settings.json` 保存状态。生产安装程序将状态放在 `/var/lib/stm32-host/`。

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
