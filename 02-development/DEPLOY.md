# DEPLOY — kb-management 部署与运行手册

**维护**：章北海（开发部署）　**最后更新**：2026-10-11（A4：9100 常驻 + 前端引用功能重建）
**分支**：`feat/kb-citations`（A1-A4 未统一 commit，A5 负责）
**台账**：服务器/端口/资源占用唯一事实源见 `~/hermes-workspace/shared/infrastructure/SERVER_REGISTRY.md`

---

## 1. 服务总览

| 服务 | 机制 | 端口 | 启动命令 |
|---|---|---|---|
| kb 后端 API | host 进程（nohup，无 systemd） | 9012 | `nohup bash scripts/start_backend.sh > 05-temp/backend_9012.log 2>&1 &` |
| kb MCP Server | host 进程（nohup，无 systemd） | 9100 | `bash scripts/start_mcp.sh`（内部 exec uvicorn） |
| kb Celery | host 进程 | -（broker 6390/3） | `scripts/start_worker.sh` |
| kb 前端 | nginx-test 容器 bind-mount 静态 | 公网 https://agent.carefold.ai/kb-management/ | 构建后拷入 `02-development/deploy/dist/` |
| 基础设施 | docker 容器 | kb-pg 9011 / kb-es 9200 / kb-minio 9002 / redis 6390 / kb-embed 8100 | 见 SERVER_REGISTRY.md |

> ⚠️ **本机无 systemd 服务**：9012 / 9100 / Celery 都是 `harry.zhang` 用户 nohup 起的 host 进程。
> **宿主机重启后不会自动拉起，必须手动重跑上表启动命令**（见 §5）。

## 2. 9100 MCP Server（A4 常驻化）

### 2.1 启动方式

```bash
cd /home/harry.zhang/kb-management
nohup bash scripts/start_mcp.sh > 05-temp/mcp_9100.log 2>&1 &
# 就绪检查
ss -tln | grep ':9100 '          # 应显示 LISTEN 0.0.0.0:9100
tail -f 05-temp/mcp_9100.log     # "Uvicorn running on http://0.0.0.0:9100"
```

`scripts/start_mcp.sh` 做的事（与 9012 的 `start_backend.sh` 同机制：host 用户 + nohup + venv）：
1. `MCP_STAGE`（默认 `05-temp/mcpstage`）挂到 PYTHONPATH 头部 —— mcp 2.3.0 与主 venv pydantic 2.9.2 冲突，必须隔离（见 §2.4）；目录缺失时**报错退出**，不静默降级。
2. `source backend/.venv/bin/activate` —— 主 venv 提供 uvicorn / FastAPI / app.*。
3. 校验 `infra/.env` 存在 + `KB_MCP_API_KEY` 是否配置（只检查、不打印值）。**env 值由 `app.core.config` 的 pydantic `env_file` 直接加载，与 9012 同源；脚本不 source .env**（.env 里有含空格未加引号的值，shell source 会炸）。
4. `exec uvicorn mcp_server:streamable_app --host 0.0.0.0 --port 9100 --log-level info --proxy-headers`。

### 2.2 鉴权（V2 §6.2）

- 请求必须带 `Authorization: Bearer <KB_MCP_API_KEY>`（三段式 JWT 形态也放行，B 块真实对话验证后再收紧）。
- key 未配置时中间件**放行**（本地开发）——生产必须注入 `.env`，启动日志会显示 `auth: on/OFF`，`OFF` 不允许上线。
- key 只进 `infra/.env`（gitignore 覆盖），不进 git、不打印。

### 2.3 安全边界（0.0.0.0 绑定的风险与兜底）

9100 绑 `0.0.0.0`（同 9012 现状，agent 容器需要跨容器网访问）。风险与兜底：

| 风险 | 兜底 |
|---|---|
| 公网可达？ | 公网不可达靠**宿主机防火墙 + nginx 不代理 9100** 兜底：nginx-test 只反代 `/kb-management/api/` → 9012 和静态目录，**没有** 9100 的 location。切勿在 nginx 加 9100 反代。**A4 实测**（2026-10-11）：从公网出口 IP 34.64.61.208:9100 / 34.121.9.233:9100 分别 TCP 探测均 **timeout 不可达** ✅（脚本 `05-temp/a4_pub_probe.py`）。 |
| 同网段内任意机器扫到 9100 | ① Bearer key 门禁（无/错 key → 401）；② mcp 2.3.0 TransportSecurity 的 Host 白名单（`mcp_server.py` 中 `allowed_hosts` 仅 `127.0.0.1:9100` / `localhost:9100` / `172.19.0.1:9100`，其他 Host 头 → 421）。两层都在，但**真正门禁是 Bearer key**——key 泄露 = 全库可检索。 |
| agent 容器访问路径 | carefold-agent 容器（172.19.0.7，carefold-agent 桥网）经**网桥网关 `172.19.0.1:9100`** 访问 host 上的 9100。A4 实测验通（见 DEV_REPORT A4）。 |

> 若未来要更强隔离：把 9100 收成 `127.0.0.1` + nginx 反代（同 9012 公网路径），或 MCP 服务容器化进 carefold-agent 桥网。当前 Bearer + Host 白名单 + 防火墙三层满足 §6.3 要求。

### 2.4 依赖隔离（mcp vs 主 venv）

- 主 venv：pydantic 2.9.2（FastAPI 9012 依赖）→ **禁止** `pip install mcp` 进主 venv（mcp 2.3.0 要求 pydantic≥2.12，升级会破坏 9012）。
- `05-temp/mcpstage`：mcp 2.3.0 + 独立 pydantic 2.14 等依赖的解包目录，经 PYTHONPATH 前缀加载。**该目录不进 git（05-temp 在 .gitignore）**——宿主机重装/换机后需重建（A2 脚本 `05-temp/a2_stage_wheels.py` 可参考；或 `pip install --target 05-temp/mcpstage mcp==2.3.0` 重建）。
- `start_mcp.sh` 对目录缺失是硬失败，不会出现"无 mcp 也能起"的假启动。

## 3. 前端部署（引用功能 A3 后重建）

部署链路：`vite build` → `frontend/dist` → 拷入 **`02-development/deploy/dist/`**（nginx-test 容器 bind-mount 到 `/usr/share/nginx/kb-management`，ro）→ `docker exec nginx-test nginx -s reload` → 公网 `https://agent.carefold.ai/kb-management/`。

```bash
cd /home/harry.zhang/kb-management/frontend && npm run build
# 换装（旧 assets 改名留档 assets.prev_*，不 rm -rf）
mv 02-development/deploy/dist/assets 02-development/deploy/dist/assets.prev_$(date +%H%M%S)
cp -r frontend/dist/assets 02-development/deploy/dist/assets
cp frontend/dist/index.html 02-development/deploy/dist/index.html
sed -i 's/crossorigin //g' 02-development/deploy/dist/index.html
docker exec nginx-test nginx -s reload
# 验证
curl -s -o /dev/null -w '%{http_code}\n' https://agent.carefold.ai/kb-management/   # 200
curl -s https://agent.carefold.ai/kb-management/ | grep -oE 'assets/index-[^"]+\.js'  # 应为本次 build 的 hash
```

> 说明：`scripts/deploy_frontend.sh` 写的是旧 NPM 容器（`nginx-proxy-manager-app-1` + `/srv/kb-management`），**已失效**，以本节为准。`assets.prev_*` 目录是历史产物，A5 统一提交前可清理。

## 4. .env 新增变量（引用功能，A1-A4）

`infra/.env`（不进 git）新增三键，`.env.example` 已带占位：

| 变量 | 含义 | 占位示例 |
|---|---|---|
| `KB_MCP_API_KEY` | 9100 MCP Bearer 密钥（48 hex，`secrets.token_hex(24)` 生成） | `change-me-48-hex-key` |
| `KB_PUBLIC_BASE_URL` | doc_url 绝对 URL 基址（公网前端路径） | `https://agent.carefold.ai/kb-management` |
| `KB_VIEW_TOKEN_MINUTES` | view_token 有效期（分钟） | `15` |

## 5. 重启恢复手册（9012 自 t_f4aac859 起为 systemd user 常驻；其余手动）

宿主机重启 / 进程挂掉后，按序手动恢复：

```bash
cd /home/harry.zhang/kb-management
# 1. 基础设施容器（docker 容器若未 --restart，重启后需拉起；当前 kb-* 容器按需）
docker ps   # 检查 kb-pg/kb-es/kb-minio/kb-dev-redis/kb-embed 是否 running
# 2. 后端 API —— systemd user 单元 kb-backend-9012.service（Restart=always，2026-10-12 t_f4aac859 起）
systemctl --user status kb-backend-9012 --no-pager        # 应 active (running)
# 改代码后加载新代码：单元内是 uvicorn 无 --reload，必须重启单元
systemctl --user restart kb-backend-9012
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9012/api/v1/health   # 200
#   日志：05-temp/backend_9012.log（单元 StandardOutput/Error append 到该文件）
#         journalctl --user -u kb-backend-9012 -n 100
#   若单元不存在（宿主重启后 systemd --user 未拉起）→ 先确认端口没被占：
#     ss -ltnp | grep ':9012'
#   然后二选一：重建单元
#     systemd-run --user --unit=kb-backend-9012 --collect --property=Restart=always \
#       --property=WorkingDirectory=/home/harry.zhang/kb-management \
#       --property=StandardOutput=append:/home/harry.zhang/kb-management/05-temp/backend_9012.log \
#       --property=StandardError=append:/home/harry.zhang/kb-management/05-temp/backend_9012.log \
#       /home/harry.zhang/kb-management/scripts/start_backend.sh
#   或退回旧方式（注意：寄生在当前 shell 的 systemd scope 内，会话结束会被回收）
#     nohup bash scripts/start_backend.sh > 05-temp/backend_9012.log 2>&1 &
# 3. MCP 9100
nohup bash scripts/start_mcp.sh > 05-temp/mcp_9100.log 2>&1 &
ss -tln | grep ':9100 '
# 4. Celery（异步解析/索引需要时）
bash scripts/start_worker.sh
# 5. 前端：静态文件在 bind mount，重启后自动生效，无需操作（仅 nginx-test 容器需 running）
```

进程快速检查：`ps aux | grep -E 'uvicorn.*9012|uvicorn.*9100' | grep -v grep`；
单元方式：`systemctl --user list-units 'kb-backend-*'`。

> 注（未解决）：Celery 仍以 `nohup`/`bash scripts/start_worker.sh` 方式寄生在启动它的 shell 所属 systemd scope 内，会话结束会被回收（t_f4aac859 登记，未改）。建议后续照 9012 的做法做 `kb-celery.service` 常驻单元。

## 6. 自测复现（给云天明）

- 本机 MCP 冒烟：`backend/.venv/bin/python 05-temp/a4_mcp_smoke.py`（无 key 401 / 错 key 401 / 正确 key 200 initialize）。
- agent 容器可达性：`docker exec carefold-agent python3 < 05-temp/a4_agent_tcp.py`（TCP OPEN）；HTTP 冒烟 `backend/.venv/bin/python 05-temp/a4_agent_http_smoke.py`（172.19.0.1:9100 + Bearer → 200 initialize）。
- 公网前端：`curl -s https://agent.carefold.ai/kb-management/` 200 + index hash 与本次 build 一致。
- 9012 健康：`curl -s http://127.0.0.1:9012/api/v1/health` 200。
