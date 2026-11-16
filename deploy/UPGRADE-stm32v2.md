# 把 STM32 页面换到 https://zhumenggy.top/stm32v2/

改动只有三块：**页面路径**、**后端端口复用 8007**、**Nginx 换一段配置**。工具箱、股票、守岸人都不动。

## 0. 先弄清楚原来是什么

服务器上 `/stm32/` 并不是独立页面，它的 Nginx 配置是：

```nginx
location ^~ /stm32/ {
    alias /www/wwwroot/110.40.174.239/工具箱/SD/dist/;
    try_files $uri $uri/ /index.html;
}
```

也就是**指向工具箱的 dist**，靠前端路由显示。所以「换新界面」等于：新做一份独立 dist，挂到 `/stm32v2/`，再把老地址 301 过去。

## 1. 本地构建

```bash
cd frontend
npm ci
npm run build      # base 已是 /stm32v2/，产物里的资源路径自动带前缀
```

产物在 `frontend/dist/`。这一步在本地做，服务器就不用装 Node。

## 2. 上传页面

```bash
ssh root@110.40.174.239
mkdir -p /www/wwwroot/110.40.174.239/STM32v2/dist

# 本地执行
scp -r frontend/dist/. root@110.40.174.239:/www/wwwroot/110.40.174.239/STM32v2/dist/

chown -R www:www /www/wwwroot/110.40.174.239/STM32v2
```

## 3. 停旧服务、换后端

```bash
# 1) 停掉占用 8007 的旧 4G
systemctl stop stm32-4g 2>/dev/null || true
ss -ltnp | grep ':8007'     # 应无输出；还有就先 kill 掉

# 2) 上传新代码（含 4G/rtcm_relay.py），覆盖原目录即可
#    假设沿用 /opt/stm32-host
cd /opt/stm32-host && git pull      # 或 rsync 覆盖
./4G/.venv/bin/pip install -r 4G/requirements.txt

# 3) 补 RTCM 端口（老 env 文件里没有）
grep -q STM32_RTCM_PORT_IN /etc/stm32-host/4G.env || cat >> /etc/stm32-host/4G.env <<'EOF'
STM32_RTCM_ENABLED=1
STM32_RTCM_PORT_IN=8017
STM32_RTCM_PORT_OUT=8018
EOF

# 4) 起服务
systemctl start stm32-4g
systemctl status stm32-4g --no-pager
journalctl -u stm32-4g -n 30
```

日志里应能看到 `RTCM source 端口已监听: 0.0.0.0:8017` 和 `8018`。

> 8009/8010 已经被工具箱的研报服务和文档转换占用，RTCM 必须用 8017/8018，不要改回去。

## 4. 改 Nginx（宝塔）

宝塔 → 网站 → zhumenggy.top → 设置 → 配置文件，在 `server { }` 里：

1. 删掉这三段旧的：`location ^~ /stm32/api/`、`location = /stm32`、`location ^~ /stm32/`
2. 粘贴 `backend/deploy/zhumenggy-stm32v2.nginx.conf` 的全部内容
3. 保存（宝塔自动 reload；不放心就手动 `nginx -t && nginx -s reload`）

改完的访问路径：

| 地址 | 行为 |
| --- | --- |
| `https://zhumenggy.top/stm32v2/` | 新页面 |
| `https://zhumenggy.top/stm32v2/api/data` | 转发到 8007 的 `/data` |
| `https://zhumenggy.top/stm32/` | 301 到 `/stm32v2/` |
| 设备 → `:8008` / `:8017` / `:8018` | 直连后端，不经 Nginx |

## 5. 验证

```bash
curl -I https://zhumenggy.top/stm32v2/            # 200
curl -s https://zhumenggy.top/stm32v2/api/data    # {"devices":{...}}
curl -I https://zhumenggy.top/stm32/              # 301 -> /stm32v2/
```

浏览器打开页面，F12 → Network → WS，应看到 `wss://zhumenggy.top/stm32v2/api/ws` 已连接（101）。再确认实时数据在跳动、差分中继卡片有基准站状态。

云安全组记得放行 **TCP 8008、8017、8018**（80/443 本来就有）。

## 6. 回滚

```bash
# Nginx：宝塔里恢复改之前的配置，或
cp /www/server/panel/vhost/nginx/110.40.174.239.conf.bak /www/server/panel/vhost/nginx/110.40.174.239.conf
nginx -t && nginx -s reload

# 后端：换回旧代码并重启
systemctl restart stm32-4g
```

## 常见问题

| 现象 | 原因 |
| --- | --- |
| 页面白屏，控制台 404 `/assets/...` | 上传的是旧的 dist（base 还是 `/stm32/`），重新 `npm run build` |
| 打开是工具箱首页 | 新 location 没生效，检查 `alias` 目录和结尾斜杠 |
| 数据不刷新、WS 报 400 | `location ^~ /stm32v2/api/` 少了 `Upgrade`/`Connection` 头 |
| 页面 403 | 目录属主不是 `www`，或 dist 没读到 |
| 8017/8018 连不上 | 安全组没放行；或旧进程还占着 8007 导致服务没起来 |
