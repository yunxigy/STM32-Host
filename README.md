# STM32 上位机

独立仓库：<https://github.com/yunxigy/STM32-Host>。

| 目录 | 内容 |
| --- | --- |
| `frontend/` | 独立 React/Vite 监测前端、地图、设备、告警、指令与轨迹 |
| `4G/` | 当前 Flask/WebSocket/设备 TCP 服务及 GNSS 滤波 |
| `wangye/` | 历史可移植提取包及测试 |
| `backend/` | 原有独立称重售水柜 Node 后端，HTTP 38080/TCP 9001 |

## 启动监测服务

```powershell
cd 4G
python -m pip install -r requirements.txt
python 4G.py
```

HTTP/WebSocket 使用 8007，设备 TCP 使用 8008。后端测试：`python -m unittest discover -s tests -p "test_*.py"`。

## 启动前端

将根目录 `.env.local.example` 复制为 `.env.local`，配置高德地图 Key 和安全码；未配置时仍可运行监测界面，地图显示配置提示。

```powershell
cd frontend
npm ci
npm run dev
```

访问 `http://127.0.0.1:8016/stm32/`。前端将 `/stm32/api/` HTTP/WebSocket 请求代理到 8007。验证执行 `npm run lint`、`npm test`、`npm run build`。生产部署静态目录为 `frontend/dist`，需相同路径的 API/WebSocket 代理。

GNSS 状态、告警配置和售水柜运行数据留在本地并被忽略。`backend/` 与监测服务分别运行，详细说明见其 README；旧文档引用的固件和小程序不在本仓库。其 `npm test` 会运行后端测试并明确跳过缺少外部小程序源码的联调测试。自动化检查不代表硬件联调。
