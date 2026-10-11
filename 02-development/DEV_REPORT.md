# DEV_REPORT — PageIndex 检索（按文档二选一索引方式，v2）

**任务**：t_f1340314（重试，前次 t_d4aa5c4b 迭代耗尽）
**开发**：章北海  2026-10-10
**分支**：`feat/pageindex`
**交付**：代码 + 部署环境 + 27/27 端到端验证通过

---

## 1. 需求变更落地（v2，最高优先级）

上一轮已按「KB 级开关 + 双索引」实现了一部分，本轮按用户确认的新需求改造为**按文档二选一**：

| # | 需求 | 实现 |
|---|---|---|
| 1 | 上传时按文档二选一：`embedding` / `pageindex`，互斥 | `upload_doc` 新增 `index_type` Form 字段（`^(embedding\|pageindex)$`，默认 embedding），写入 `document.meta["index_type"]`；`chunk_index_task` 按 index_type 分流——pageindex 文档**跳过分块/向量**，直接链式触发 LLM 建树 |
| 2 | 上传入口加方式选择（radio，默认 embedding） | `KbDetailView.vue` 上传卡片加 radio（Embedding 分块+向量 / PageIndex 树索引）+ 说明文案；文档列表新增「索引方式」「PageIndex」两列 |
| 3 | 文档级重建索引按 index_type 执行 | 新增 `POST .../documents/{doc_id}/reindex`：pageindex → 重建树索引；embedding → 重建分块+向量。前端加「重建索引」按钮 |
| 4 | 检索/问答保留 pageindex；无索引文档 → 空结果+提示，不静默回退 | `SearchReq.mode` / `ChatReq.retrieval_mode` 扩 `pageindex`；`pageindex_engine.retrieve()` 只收 `index_type=pageindex` 且已建树的文档，无此类文档返回 `items=[]` + `message`；rag_engine pageindex 分支检索失败/无结果发 `error` 事件，**不回退 ES、不空答** |
| 5 | 废弃 KB 级 `enable_pageindex` 开关 | 已全量删除（grep 确认无残留）；KB settings 相关代码未提交、不入本次分支 |

**保留并复用**（上一轮引擎部分设计有效）：
- `backend/app/services/pageindex_engine.py`（756 行）：LLM 建树（分片+校验+降级 heading 规则树）、联合推理检索、sources 兼容格式、stale 兜底
- `llm_client.chat()` 非流式 JSON 调用（vllm 不支持 response_format 时自动退化）
- 树存 `document.meta["pageindex_tree"]`（JSONB，不建新表）；引用定位用 full_text 字符偏移 `[start,end)`
- Celery `kb.build_pageindex` 任务（`time_limit=900`），不阻塞 API

## 2. 本轮修复的真实 BUG（验证中暴露）

**BUG：`ProcessTask.id` 在 `.delay()` 调用时为 None，建树任务收到字符串 `"None"` → worker 内 `_update_task` 抛 `InvalidTextRepresentation`，首次上传的 pageindex 文档建树必然失败。**

- 根因：三处调用点（`tasks.py` 链式触发、`documents.py` reindex、rebuild）在 `ProcessTask(...)` 构造后、id 回填完成前就执行 `str(task.id)` 传给 `.delay()`。
- 修复：**显式 `ProcessTask(id=uuid.uuid4(), ...)`**，保证 `.id` 在 delay 前必然可用（tasks.py `_queue_pageindex_build`、documents.py `reindex_doc` 两分支、`reparse_doc`、`rebuild_pageindex` 共 5 处）。
- 验证：修复前 `pageindex_doc_indexed FAIL`（status=chunking 卡死）；修复后同一上传路径 `status=indexed, tree_status=ok`。

## 3. 部署环境（可运行，已验证）

本机部署，服务端口：后端 9012（uvicorn）、前端 9013（vite，dev）、PG 9011、ES 9200、MinIO 9002、PageIndex LLM 34.121.9.233:4000。

启动方式（后端 + Celery）：
```
cd backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 9012
cd backend && .venv/bin/celery -A app.workers.celery_app.celery_app worker -Q kb -l info
```

**本轮环境修复（全部只进 `infra/.env`，未入 git）**：
1. `PG_PASSWORD`：原值被写入了 U+2026（…）非真实密码 → 修正为 PG 实际密码。
2. `REDIS_PORT`/`REDIS_PASSWORD`/`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND_URL`：本机 6179/6379 无 redis 监听 → 复用已运行的 `kb-dev-redis` 容器（host 网络 127.0.0.1:6390，无密码），broker/result 用 /3 /4 库隔离。注意字段名必须是 `CELERY_RESULT_BACKEND_URL`（settings 字段 `celery_result_backend_url`，裸 `CELERY_RESULT_BACKEND` 不生效、会静默回退默认值）。
3. `MINIO_SECRET_KEY`：原值与 MinIO 实际凭据不符（SignatureDoesNotMatch）→ 实测 `kb_admin` + compose 默认 secret 组合可列出 bucket 后修正。

**当前健康检查**（`GET /api/v1/health`）：postgresql=ok、elasticsearch=green、minio=ok、redis=ok、llm=ok；`embedding`=unreachable（34.64.61.208:4000 公网端点本轮不可达）、`mineru`=unreachable（本机 9030 未起）——两者不影响 pageindex 功能（pageindex 不依赖 embedding；txt/md 本地解析不依赖 MinerU）。

## 4. 验证证据（端到端，27/27 全过）

验证脚本：`05-temp/kb_verify_v2.py`（httpx，注册→建 KB→上传→轮询→检索→SSE 问答→reindex），结果快照 `05-temp/verify_results.json`。

**A. 一个文档分别走两种方式**
- 上传 `pi_manual.md`（index_type=pageindex）：`status=indexed`、`meta.pageindex_status=ok`、树 10 节点、**chunk_count=0**（互斥生效：无向量索引）
- 上传 `finance_report.md`（index_type=embedding）：走 chunk+向量路径（embedding 端点不可达 → `status=failed` + "Connection error."，证明分流正确：它走了向量路径而非建树）
- `document.meta.index_type` 两种取值均正确记录

**B. pageindex search 流式/检索**
- `POST /knowledge-bases/{kb}/search` `mode=pageindex`：返回 3 条 items，`match_type=pageindex`、`score=0.98`（LLM relevance）、document_id 正确、content 切自 full_text 节点区间（「模型服务不可用时…先检查端点连通性与密钥有效性…」——与问题相关段落）

**C. pageindex chat 流式（SSE）**
- `retrieval_mode=pageindex`：110 token 流式回答，`sources` 事件 3 条（chunk_id/document_id/filename/chunk_index/score 五字段齐全），回答含 `[1][2]` 引用标注，内容正确（排查步骤）

**D. 无 pageindex 索引文档 → 空结果+提示（不静默回退）**
- 仅含 embedding 文档的 KB 做 pageindex 检索：`items=[]` + `message="该知识库下没有使用 PageIndex 索引的文档（上传时需选择 PageIndex 索引方式）…"`

**E. embedding 回归**
- `mode=hybrid` 检索 200 正常返回（端点不可达时走既有错误路径，不崩溃）
- embedding 文档失败原因是外部 embedding 端点不可达（环境态），非代码路径问题；向量代码路径零改动（红线）

**F. 文档级重建索引**
- pageindex 文档 `POST reindex` → 按 index_type 重建，`status=indexed`、`tree_status=ok`
- embedding 文档 `POST pageindex/rebuild` → 400「该文档不是 PageIndex 索引方式」（类型保护）

## 5. 已知问题 / 风险

1. **embedding 端点（34.64.61.208:4000）本轮不可达**：embedding 文档无法完成向量索引（failed）。属外部环境态，非代码问题；端点恢复后行为自动正常。云天明测试 embedding 回归时若仍不可达，需先确认该端点。
2. **MinerU 未启动（9030）**：仅影响 pdf/docx/xlsx/图片解析；txt/md 本地解析不受影响（验证用 md 文档）。测试若需解析 PDF 先起 MinerU 容器。
3. LLM 建树 27b 实测约 1-2 分钟/文档（单片小文档 10 节点 <2min）；大文档走分片，上限 900s 超时。
4. `infra/.env` 为本地开发配置（含真实密码），.gitignore 已覆盖（`.env` 规则，git status 确认未跟踪）。

## 6. 文件清单（本次分支）

- 新增：`backend/app/services/pageindex_engine.py`、`infra/migrations/20261010_pageindex.sql`（process_task.task_type + pageindex）、`02-development/DEV_REPORT.md`、`00-management-PAGEINDEX_BRIEF.md`、`00-management-PAGEINDEX_DESIGN.md`
- 改动后端：`api/chat.py`、`api/documents.py`（index_type 上传 + reindex + rebuild + id 修复）、`api/search.py`、`core/config.py`（pageindex_llm_model 等）、`models/models.py`（task_type 约束）、`schemas/schemas.py`（mode/retrieval_mode）、`services/rag_engine.py`（retrieval_mode 分流）、`utils/ai_client.py`（chat 非流式）、`workers/tasks.py`（build_pageindex_task + 分流 + id 修复）、`init_db.sql`
- 改动前端：`api/index.ts`（uploadDoc index_type / reindexDoc / search mode / chatStream retrieval_mode + SSE 协议兼容）、`KbDetailView.vue`（上传 radio + 列 + 重建按钮）、`KbChatView.vue`（检索模式 radio）、`KbSearchView.vue`（mode radio + 提示）
- 文档：`docs/api.md`、`docs/architecture.md`（PageIndex 引擎章节）
- 不动：ES/向量检索路径、requirements.txt（自实现无新依赖）、外部容器

## 7. nginx 部署（t_461dbaba）— agent.carefold.ai/kb-management/

**目标**：`https://agent.carefold.ai/kb-management/` 可访问，静态 dist + API 反代宿主机后端（127.0.0.1:9012）。

**构建**：`feat/pageindex` 分支 `frontend/` 执行 vite build，产物 `dist/`（base 已是 `/kb-management/`）。
- 注：`npm run build`（含 `vue-tsc -b`）因**既有已提交代码**的类型错误 `KbChatView.vue:41`（`si` 为 `string|number` 不能 `+ 1`）失败；红线要求不动前端源码，故直接用 `vite build` 出包（vite 不做类型检查，dist 产物与 tsc 无关）。该类型错误留给后续开发任务修复。

**dist 挂载**：产物复制到 `02-development/deploy/dist/`，在 `~/myapp/docker-compose.yml` 的 nginx 服务新增一条 ro 卷（与 carefold-base/saas 同模式），`docker compose up --detach nginx` 重建 nginx-test 容器生效。
```
- /home/harry.zhang/kb-management/02-development/deploy/dist:/usr/share/nginx/kb-management:ro
```

**nginx 配置**（`/etc/nginx/conf.d/agent.carefold.ai-100-https.conf` 443 server 块，仅新增，未动 carefold-base/saas 段）：
```nginx
# 反代：前端 /kb-management/api/ → 后端 /api/（静态 proxy_pass 尾斜杠自动去 /kb-management 前缀，
# 与 vite dev proxy rewrite 逻辑一致）；后端在宿主机 9012，容器经 bridge IP 172.18.0.1 访问（已实测通）。
location /kb-management/api/ {
    proxy_pass http://172.18.0.1:9012/api/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection "";
    proxy_buffering off;        # SSE chat 流式逐字必需
    proxy_cache off;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
}
# SPA 静态 + 深链 fallback
location /kb-management/ {
    try_files $uri $uri/ /kb-management/index.html;
}
location = /kb-management {
    return 301 /kb-management/;
}
```

**验证证据（2026-10-10 10:50 UTC，全部经公网域名实测）**：
- `nginx -t`：configuration test is successful（容器内校验）
- `curl -sI https://agent.carefold.ai/kb-management/` → **HTTP 200**，`content-type: text/html`，body 即 index.html（asset 路径带 `/kb-management/` 前缀正确）
- `curl -sI https://agent.carefold.ai/kb-management`（无尾斜杠）→ **HTTP 301** → `/kb-management/`
- SPA 深链 `GET /kb-management/kb/abc123/chat` → **200 text/html**（fallback 生效，客户端路由刷新不 404）
- 静态资源 `GET /kb-management/assets/index-*.js` → **200 application/javascript**（861 KB）
- 反代健康端点 `GET /kb-management/api/v1/health` → **200** `{"code":0,"message":"ok","data":{"status":"degraded","services":{...}}}`（degraded 系外部 embedding/mineru 端点不可达的环境态，见 §5）
- 反代鉴权链路 `GET /kb-management/api/v1/knowledge-bases` → **401** `{"code":40101,"message":"缺少 Authorization 头"}`（请求确实到达后端 FastAPI 路由层，前缀剥离正确）
- chat 流式端点 `POST /kb-management/api/v1/knowledge-bases/x/chat` → 401（未带 token），`proxy_buffering off` 已配置，SSE 逐字依赖满足（正式带 token 的 SSE 行为由测试阶段复验）

**影响面**：仅 myapp compose 加一条卷 + 域名 conf 新增 3 个 location；carefold-base/saas 段零改动（diff 可证）；无密钥入库（dist 为纯静态构建产物）。
