# DEV_REPORT — PageIndex 检索（按文档二选一索引方式，v2）

**任务**：t_f1340314（重试，前次 t_d4aa5c4b 迭代耗尽）
**开发**：章北海  2026-10-10
**分支**：`feat/pageindex`
**交付**：代码 + 部署环境 + 27/27 端到端验证通过

---

## A2: MCP 结果加 doc_url+location + rag_engine metadata 透传 + Bearer 鉴权（t_0fdfa8d0）

**范围**：`backend/mcp_server.py`、`backend/app/services/rag_engine.py`（主改动）+ `backend/requirements.txt`、`scripts/start_mcp.sh`（mcp 依赖隔离，自测可运行的前提）。
**设计依据**：KB_CITATION_DESIGN_V2 §2.1（引用契约）+ §1 错误1（metadata 透传）+ §6.2（MCP Bearer 鉴权）。

### 改动文件
| 文件 | 改动 |
|---|---|
| `backend/mcp_server.py` | ① `_attach_citations(kb_id, items)` 集中辅助函数：拼 doc_url + 算 location + 按 (kb,doc) 批量签发 view_token（同批复用）；② `search_knowledge` / `rag_query` / `get_document_chunks` 三工具结果全部过它；③ Bearer 鉴权前置 ASGI 中间件（KB_MCP_API_KEY 精确匹配 或 合法三段式 JWT 形态"双接受"，未配置 key 时放行=本地开发）；④ 外层 Starlette 包 app 时透传内层 lifespan |
| `backend/app/services/rag_engine.py` | sources 构建处透传 `s.get("metadata", {})`（V2 §1 错误1；embedding 命中无该键 → 空 dict 无影响） |
| `backend/requirements.txt` | 追加 `mcp==2.3.0`（带冲突警告注释，见"部署风险"） |
| `scripts/start_mcp.sh` | 支持 `MCP_STAGE` 环境变量挂隔离依赖目录（mcp 与主 venv pydantic 冲突，不能直接装主 venv）；未设 `KB_MCP_API_KEY` 时打印放行警告 |

**引用契约实现（V2 §2.1）**：
- `doc_url` = `{KB_PUBLIC_BASE_URL}/kb/{doc_kb}/doc/{doc_id}?{chunk=N|node=X}&token=<view_token>`；view_token 用 `create_view_token(doc_id, kb_id, viewer="mcp")`，同 (kb,doc) 同批复用。
- `location`：`match_type=pageindex`（或文档 index_type=pageindex）且 metadata 有 `node_id` → `{type:"node", value:node_id}`（metadata 的 char_start/char_end 随 item.metadata 透出）；node_id 缺失或 embedding 文档 → `{type:"chunk", value:chunk_index}`。

### 前次实现修正（本 run 修复的 2 个真 bug）
1. **search_knowledge 的 doc_url/location 全丢**：前次实现在 items 字段白名单重组**之前**对原始 hits 调 `_attach_citations`（原地加键），随后白名单重组把新增键全丢掉。已移到 items 组装之后调用，`_attach_citations` 的 kb_id 改 Optional（跨库检索时以 DB 查到的文档归属 kb 为准）。
2. **"Task group not initialized" 崩溃**（前次 run crash 根因）：外层 `Starlette(routes=_mcp_app.routes, ...)` 只继承 routes，**丢了内层 lifespan**（`StreamableHTTPSessionManager.run`），session manager 的 task group 永不启动 → 任何 tools/call 500。已改为 `lifespan=_mcp_app.router.lifespan_context` 透传。

### 自测证据（2026-10-11，真实运行，mcp 2.3.0 经 05-temp/mcpstage 隔离加载）
命令：`cd kb-management && backend/.venv/bin/python 05-temp/a2_final_test.py`（端口 9199 测试实例，env 取 infra/.env + 注入测试 key，不碰 9012）：

| 用例 | 结果 |
|---|---|
| 无 Authorization 头 → | **401** `{"error":"unauthorized"}` ✅ |
| 错误 key（`Bearer wrong-key`）→ | **401** ✅ |
| 合法三段式 JWT 形态 → | **200**（双接受放行，a2_verify3.py）✅ |
| 正确 key + `tools/call search_knowledge` → | **200**，items 含 doc_url+location ✅ |
| `tools/call get_document_chunks`（真实文档 a1test_B.txt）→ | **200**，items 含 doc_url+location ✅ |
| `tools/call rag_query`（真实问答）→ | **200**，answer 132 字符，2 条 sources 均含 doc_url+location ✅ |

search_knowledge 真实响应样例（脱敏：token 截断）：
```json
{
  "query": "测试 知识库 文档 检索", "mode": "hybrid", "total": 5, "took_ms": 334,
  "items": [
    {
      "chunk_id": "6238b158-4afd-49bc-96cd-dfe804e20ad4",
      "document_id": "cb7a583d-738c-4856-99e9-2ab4c13df713",
      "filename": "r2_second.md", "chunk_index": 0,
      "content": "# Beta doc\n\nBeta document. Testing one two three four five. ...",
      "score": 0.016393, "match_type": "hybrid", "metadata": {},
      "location": {"type": "chunk", "value": 0},
      "doc_url": "https://agent.carefold.ai/kb-management/kb/f8f4d065-7436-4e54-9536-f67f916148c8/doc/cb7a583d-738c-4856-99e9-2ab4c13df713?chunk=0&token=eyJhbGciOi...Klg8"
    }
  ]
}
```
rag_query sources 样例（脱敏）：
```
source: a1test_B.txt   chunk: 0  location: {"type": "chunk", "value": 0}  doc_url: https://agent.carefold.ai/kb-management/kb/56c885ac-.../doc/bd758018-...?chunk=0&token=***
source: r2_second.md   chunk: 0  location: {"type": "chunk", "value": 0}  doc_url: https://agent.carefold.ai/kb-management/kb/f8f4d065-.../doc/cb7a583d-...?chunk=0&token=***
```
（本轮测试数据全为 embedding 文档，location 均为 chunk 型；pageindex→node 分支已在 `05-temp/a2_import_check.py` 单元验证：`{'type': 'node', 'value': 'n1.2'}`，node_id 缺失降级 `{'type': 'chunk', 'value': 0}`。）

### 部署风险（A4 处理常驻化时必读）
1. **9100 绑定 0.0.0.0**（mcp_server.py `__main__` 与 start_mcp.sh `--host 0.0.0.0`）：当前依赖 Bearer 鉴权兜底，但**不建议公网暴露**——Bearer key 泄露 = 全库可检索。A4 常驻化时应收为 127.0.0.1 + nginx 反代（同 9012 模式）或独立 docker 网络内网暴露。
2. **mcp 2.3.0 与主 venv pydantic 冲突**：mcp 2.3.0 要求 pydantic≥2.12，主 venv 是 2.9.2（FastAPI backend 依赖）。**不能 pip 装进主 venv**（升级 pydantic 会破坏 9012）。当前自测方案：`05-temp/mcpstage`（轮子解包目录）经 PYTHONPATH 隔离加载，`scripts/start_mcp.sh` 已支持 `MCP_STAGE` 挂载。**A4 推荐：独立 docker 容器（独立 venv/镜像装 mcp），或独立 venv**——二选一，勿装主 venv。
3. **JWT 双接受是兜底策略**：中间件对"合法三段式 JWT 形态"放行（仅格式校验不验签），为 agent forwardCallerAuthorization 可能用用户 JWT 覆盖 Authorization 头留的口子；B 块注册后跑真实对话确认 agent 实际发什么头，再决定是否收紧为仅 KB_MCP_API_KEY。

### 自测脚本（05-temp/，不进 git 交付物）
`a2_import_check.py`（_attach_citations 三分支单元）、`a2_final_test.py`（端到端 6 用例）、`a2_verify2.py`/`a2_verify3.py`（JWT 三段放行 + rag_query sources）、`a2_jwt_shape.py`（_is_jwt_shape 单元）。

---

## A1: 后端 view_token 签发 + 鉴权 + 只读端点（t_e969e38d）

**范围**：仅后端 4 文件 + `.env.example`（不动 MCP、不动前端）。
**设计依据**：KB_CITATION_DESIGN_V2 §4（view_token）+ §1 错误3（download MIME）。

### 改动文件

| 文件 | 改动 |
|---|---|
| `backend/app/core/security.py` | 新增 `create_view_token(doc_id, kb_id, viewer, minutes=None)`（HS256 + SECRET_KEY，claims: sub=doc_id, kb_id, type="view", scope="single_doc", viewer, exp）+ `decode_view_token(token)`（校验 type=="view" 且未过期，返回 payload，否则 None） |
| `backend/app/core/config.py` | 新增 `kb_view_token_minutes=15`（env `KB_VIEW_TOKEN_MINUTES`）、`kb_mcp_api_key=None`（env `KB_MCP_API_KEY`，A2 用）、`kb_public_base_url="https://agent.carefold.ai/kb-management"`（env `KB_PUBLIC_BASE_URL`，A2 用） |
| `backend/app/api/deps.py` | 新增 `ViewTokenContext`（view_only=True，无 User 行，携带 payload）；新增依赖 `get_current_user_or_view_token`：先走现有 Bearer JWT（行为不变，回归保护），失败回退 query `?token=` → decode_view_token 校验（过期/无效 → 401 "链接已过期"；越权 token.kb_id≠路径 kb_id 或 token.sub≠路径 doc_id → 403）；`require_kb_access` 遇 view_only 短路放行 |
| `backend/app/api/documents.py` | 4 个只读端点（GET 详情 / download / content / chunks）改用 `get_current_user_or_view_token`；download 修正为 `Content-Disposition: inline` + 按 file_type 映射 MIME（pdf→application/pdf，图片→image/*，txt→text/plain，md→text/markdown，其他→原 octet-stream）供 iframe 渲染；POST/DELETE 端点（reparse/reindex/delete/upload）一律未改，仍走 `get_current_user` → view_token 天然 401/403 |
| `infra/.env.example` | 加 `KB_VIEW_TOKEN_MINUTES` / `KB_MCP_API_KEY` / `KB_PUBLIC_BASE_URL` 占位（不含真实密钥）；另修正 `EMBEDDING_BASE_URL` 变量名注释（旧名 `EMBEDDING_API_BASE` 不被 pydantic 字段读取，见上传 bug 修复小节） |

### 附带修复（自测暴露的既有 bug）

- `/documents/{doc_id}/chunks` 500：`ChunkOut.metadata` 声明 `dict`，但 DB 中 metadata 列反序列化为 SQLAlchemy `MetaData` 对象（非 dict）→ pydantic 校验失败。修复：`list_chunks` 序列化时非 dict metadata 归一为 `{}`（JWT 用户同样受影响，属既有问题，A1 自测要求 chunks 200 故一并修复）。

### 自测证据（2026-10-11 13:50 UTC，9012 本地后端，14/14 全过）

测试用户 `a1tester`（register/login 取 JWT），KB A/B 各上传 `a1test_A.txt` / `a1test_B.txt`（status=indexed）；`create_view_token` 以运行中后端同 SECRET_KEY 签发。脚本：`05-temp/a1_selftest_v2.py`。

| # | 用例 | 结果 |
|---|---|---|
| 3a | A 文档 view_token 读 A 文档 4 只读端点（detail/download/content/chunks）`?token=` | 全部 **200 PASS** |
| 3b | download 响应头（token 模式） | `Content-Disposition: inline; filename=a1test_A.txt`，`Content-Type: text/plain; charset=utf-8` **PASS** |
| 3b | A 文档 token 读 B 文档 detail / download（越权） | **403 PASS**（"无权访问该文档/知识库"） |
| 3c | 过期 view_token（exp=now-1min）读 detail | **401 PASS**（`{"code":40101,"message":"链接已过期"}`） |
| 3d | view_token 调写端点 DELETE / reparse | **401 PASS**（Bearer 缺失且 token 非 access 型 → 拒绝） |
| 3e | 回归：JWT 用户读 detail | **200 PASS** |
| 3e | 回归：JWT 用户 download | **200 PASS**，CD=inline（行为不变，仅 inline+MIME 增强） |
| 3e | 无任何认证读 detail | **401 PASS** |

### 已知问题 / 约束

- view_token 无状态（复用 SECRET_KEY，无撤销表）：泄露后在有效期内（默认 15min）内有效，过期自动失效——设计取舍，见 V2 §4。
- `?token=` 走 query 参数（供 iframe 直链，无法带 Authorization 头）；只读端点专用，写端点不受影响。
- chunks metadata 归一为 `{}` 会丢弃该字段的历史脏数据展示（DB 值本身未动，仅 API 序列化防御）。

---

## A3: 前端 DocView 深链定位 + 高亮 + 原文内嵌三态（t_cea960fa）

**范围**：仅前端（`frontend/`）+ 1 处既有 TS 报错修复（`KbChatView.vue`）。
**前置**：A1 后端 view_token（`create_view_token` / `decode_view_token` / `get_current_user_or_view_token` 已在 `security.py`/`deps.py`）。
**注意**：A1 写 `documents.py` 的其余 3 个只读端点（/download /content /chunks 加 `?token=` + download 改 inline+正确 MIME）属 A1 收尾范围，本段未改后端逻辑（避免与 A1 并发冲突）；DocView 按 A1 完成态契约实现，token 模式下 401/403 不跳登录、仅顶部提示。

### 改动文件
| 文件 | 改动 |
|---|---|
| `frontend/src/router/index.ts` | 新路由 `kb/:id/doc/:docId`（name `KbDoc`）；auth guard 放行：`to.name==='KbDoc' && to.query.token` |
| `frontend/src/api/request.ts` | 请求拦截器 token 模式：`(window as any).__kbTokenMode` 非空 → `?token=` query 优先（不带 Bearer）；401 时 token 模式不跳登录只提示 |
| `frontend/src/views/DocView.vue` | 新建，深链查看页（三态内嵌 + chunk/node 定位高亮 + 只读模式） |
| `frontend/src/views/KbChatView.vue` | 既有 TS 报错修复（`si as number + 1`，v-for index，行为不变）——base HEAD 上 `vue-tsc -b` 即失败，阻塞 `npm run build` |

### DocView 关键实现
**三态原文内嵌**（按 `file_type`）：
- `pdf` → `<iframe :src="downloadUrl + '?token=' + token">`（依赖 A1 的 inline+MIME）
- 图片（jpg/jpeg/png/webp/tiff/bmp）→ `<img :src="downloadUrl + '?token=' + token">` 直显
- 其他 → 文本视图：`GET /content` 的 `full_text`（`<pre>` 保留换行，节点定位时拆 `<span>` 高亮）

**token 只读模式**（`?token=`）：
- `onMounted` 先把 `viewToken` 写入 `window.__kbTokenMode`，再发请求（拦截器据此走 `?token=`）
- 该模式隐藏"返回知识库"等写入口/导航（只读视图）；`get_doc`/`/content`/`/chunks`/`/download` 全部带 `?token=`

**定位 + 高亮**（query `chunk=N` 或 `node=n1.2.3`）：
- `chunk`：`/chunks` 分页循环拉全量（page_size=100，安全上限 50 页）→ 分块列表 → 目标块 `scrollIntoView` + `chunk-highlight` class（3 秒后自动取消）
- `node`：无需新增后端端点——PageIndex 树已随 `GET /content` 的 `meta.pageindex_tree` 返回（节点含 `start`/`end` 全文坐标），在 full_text 内按 `start/end` 切段渲染，高亮段 `scrollIntoView`；`findNodeInTree` 支持 node_id 精确 + 前缀匹配（n1.2 → 最深匹配节点）
- 定位失败（文档未解析 / chunk 缺失 / 树不存在 / 区间无效）→ 顶部 `el-alert` 提示条，仍展示原文

### 自测证据（2026-10-11）
1. **构建**：`vue-tsc -b` → `TSC_EXIT=0`；`vite build` → `✓ built`（DocView 独立 chunk `DocView-*.js`，含 `__kbTokenMode`/`pageindex_tree` 标记；`KbDoc` 路由在主 bundle）
   - 对照实验：base HEAD（无本段改动）`vue-tsc -b` 因 `KbChatView.vue:41` 既有 TS 报错 exit 1 → 确认该报错先于本段存在，修复后全量构建通过
2. **深链路由可达**（`vite preview` 本地起 dist）：
   - `GET /kb-management/kb/KB1/doc/DOC1?chunk=2&token=***` → **HTTP 200** text/html（SPA fallback 正确，刷新不 404）
   - `GET /kb-management/kb/KB1/doc/DOC1?node=n1.2.3&token=***` → **200**
   - 无 token 深链 → **200**（SPA shell，客户端路由/守卫接管）
3. **浏览器视觉验证**（三态渲染、高亮实际效果、token 过期提示）：留到 A5/测试阶段（需真实后端 + 真实文档）

### 本轮补完（run 58，前次 crash 中断后收尾）
1. **KbChatView.vue 修复二次修正**：前次写的 `` `片段 ${si as number + 1}` `` 语法有歧义，改为 `` `片段 ${(si as number) + 1}` ``，`vue-tsc -b` 确认通过。
2. **DocView token 失效兜底提示**：`init()` 捕获 401/403 时，token 模式下改为顶部 `el-alert`（type=error）"token 无效或已过期" 提示条（不再只靠拦截器弹 toast 后白屏），仍不跳登录。
3. **PDF `#page=1` 锚点**：按设计文档 §5 要求，iframe `@load` 后经 `contentWindow.location.hash` 注入 `#page=1`（同源生效、跨域静默忽略），避免把 `#page=1` 拼进请求 URL 发给服务端。
4. **复验**：`npm run build` → `BUILD_EXIT=0`（vue-tsc + vite 全过，DocView 独立 chunk 7.35 kB）；`vite preview` 下 4 条深链 URL（chunk+token / node+token / 无 token / 基路径）均 **200 text/html**；构建产物 grep 确认 `__kbTokenMode`/`pageindex_tree`/`KbDoc` 标记存在。
5. **后端 pageindex tree 端点：未新增**——`GET /content` 的 `meta.pageindex_tree` 已带完整树（节点含 node_id/title/start/end/children），前端直接消费，符合任务"已有则用"条款，零后端改动。

### 已知问题 / 风险
- A1 的 /download /content /chunks 若尚未切换 `get_current_user_or_view_token`，token 模式下这 3 个端点会 401 → DocView 顶部提示条兜底（不白屏、不跳登录）；A1 完成后即恢复。
- PDF iframe 依赖 A1 的 inline+正确 MIME；若 A1 未改，浏览器会按 octet-stream 下载而非内嵌——同样由 A1 收尾保证。
- 非 token 模式（已登录用户直接打开 `/kb/{id}/doc/{docId}` 不带 token）时 iframe/img 无法携带 Authorization 头，原文内嵌仅文本视图可用；深链场景始终带 token，不影响主链路。

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

---

## 上传 bug 修复：同库顺序上传两份文档第一份失败（t_670a7d8a，commit edf8ca4）

**一句话根因**：外部 embedding 端点 `34.64.61.208:4000`（gte-qwen2）已下线（connection refused），所有 `index_type=embedding` 文档在 embedding 阶段必 failed；同库顺序上传两份（embedding + pageindex 混合）时 embedding 那份失败、pageindex 那份成功——用户看到的「第一份失败」正是那份 embedding 文档。附带缺陷：`.env` 写 `EMBEDDING_API_BASE` 而代码读取 `EMBEDDING_BASE_URL`，端点配置长期无效。

**修复**：部署本地 OpenAI 兼容 embedding 服务（`deploy/embedding/`，sentence-transformers CPU，`paraphrase-multilingual-MiniLM-L12-v2`，384 维，容器 `kb-embed` @ 127.0.0.1:8100）；`.env` 改 `EMBEDDING_BASE_URL` 指向本地；`ai_client.dim()` 实测维度并缓存；`es_client.ensure_index` 维度不符时空索引重建/非空拒改；worker+lifespan 用实测维度。

**本轮（run 60）重跑自测证据（2026-10-11，backend 重启后）**：
- health：`embedding=ok`（postgresql/elasticsearch/minio/redis/llm 均 ok，mineru 本机未起仅影响 pdf/docx）。
- 同库连续 3 份（含混合 index_type）全成功：
  | 文档 | index_type | 终态 | chunks |
  |---|---|---|---|
  | r1_first.txt | embedding | **indexed** | 3 |
  | r2_second.md | embedding | **indexed** | 4 |
  | r3_third.md | pageindex | **indexed** | 树（LLM 建树） |
  第一份（embedding）不再失败 ✅（修复前必 failed）。
- 检索回归：`hybrid`/`keyword`/`vector` 均 HTTP 200（items 10/7/10）。
- 单文档上传（embedding）→ indexed（3 chunks）✅。
- 自测脚本：`05-temp/regression_v2.py`、`05-temp/single_doc_test.py`。

详见 `02-development/BUGFIX_REPORT.md`。

---

## A4: 9100 nohup 常驻 + 前端重建部署 + DEPLOY 文档 + 台账回写（t_21febf33）

**范围**：部署+文档（主体不碰功能代码）；唯一的代码改动是 `mcp_server.py` 补传 `transport_security`（修 421，属部署使能项，见下）。A2/A3 代码已落盘（git 工作区 14 处改动 + DocView.vue 未提交，A5 统一提交）。

### 1. 9100 常驻（与 9012 同机制：harry.zhang 用户 nohup + 主 venv，无 systemd）
- `scripts/start_mcp.sh` 重写：
  - `MCP_STAGE`（默认 `05-temp/mcpstage`）挂 PYTHONPATH 头部（mcp 2.3.0 与主 venv pydantic 2.9.2 隔离，**目录缺失硬失败**，不静默降级）；
  - `source backend/.venv/bin/activate`（uvicorn/app.* 来自主 venv）；
  - `infra/.env` 只校验存在性 + KB_MCP_API_KEY 是否配置（值由 `app.core.config` pydantic env_file 与 9012 同源加载；**不 shell source .env**——.env 有含空格未加引号的值，source 会炸，实测踩过）；
  - `exec uvicorn mcp_server:streamable_app --host 0.0.0.0 --port 9100 --log-level info --proxy-headers`。
- 实际启动：`nohup bash scripts/start_mcp.sh > 05-temp/mcp_9100.log 2>&1 &`，进程 **pid 1472601**，`LISTEN 0.0.0.0:9100`，RSS ~115MB。

### 2. 部署使能修复（421 → 200，mcp_server.py 唯一改动）
首启后 agent 容器经 172.19.0.1:9100 调 initialize 返回 **421 Invalid Host header**（非 uvicorn 0.30.6 的 host-fallback 缺失——`--proxy-headers` 实测无效）。真实来源：**mcp 2.3.0 `mcp/server/transport_security.py` 的 DNS rebinding 保护**——非 loopback 绑定（0.0.0.0）时默认 `enable_dns_rebinding_protection=True` 且 `allowed_hosts=[]`，任何非本机 Host 头一律 421。
修复：`streamable_http_app(...)` 显式传 `TransportSecuritySettings(allowed_hosts=["127.0.0.1:9100","localhost:9100","172.19.0.1:9100"])`（内网白名单，Bearer 仍是唯一门禁）。重启 9100 后验证通过。

### 3. 连通性实测（2026-10-11，全部真实运行）
| 用例 | 结果 |
|---|---|
| 本机 `POST 127.0.0.1:9100/mcp` 无 Authorization | **401** `{"error":"unauthorized"}` ✅ |
| 本机 错误 key | **401** ✅ |
| 本机 正确 key（infra/.env 注入）initialize | **200**，SSE `event: message` + serverInfo ✅（`05-temp/a4_mcp_smoke.py`） |
| Host 头 `172.19.0.1:9100` | **200** ✅（修复前 421） |
| Host 头 `agent.carefold.ai`（外部域名） | **421** ✅ 白名单生效（`05-temp/a4_host_probe.py`） |
| agent 容器（carefold-agent, 172.19.0.7）`docker exec` python socket 探 172.19.0.1:9100 | **TCP OPEN** ✅ |
| agent 容器内 python urllib initialize（Bearer 经 stdin 注入，key 不进容器/不打印） | **HTTP 200**，serverInfo `kb-management v1.0.0` ✅（`05-temp/a4_agent_http_smoke.py`） |
| 公网出口 IP（34.64.61.208 / 34.121.9.233）:9100 TCP 探测 | 均 **timeout 不可达** ✅ 公网兜底生效（防火墙 + nginx 不代理 9100；`05-temp/a4_pub_probe.py`） |
| 9012 回归 | `GET /api/v1/health` **200**（mcp 隔离未破坏主 venv）✅ |

### 4. 前端重建部署（A3 改动生效）
`npm run build`（BUILD_EXIT=0，新 asset `DocView-BvyholJg.js` 等）→ 换装 `02-development/deploy/dist/`（nginx-test bind-mount → `/usr/share/nginx/kb-management`；旧 assets 改名留档 `assets.prev_*` 未删，A5 可清理）→ `nginx -s reload`：
- 公网 `https://agent.carefold.ai/kb-management/` → **200**，index 引用 `assets/index-UZVuLY4c.js`（与本次 build 一致）✅
- `assets/DocView-BvyholJg.js` → **200**（7359 bytes）✅ 新前端生效。
- 注：`scripts/deploy_frontend.sh` 里写的旧 NPM 容器 `nginx-proxy-manager-app-1` + `/srv/kb-management` 已失效，实际链路是 bind mount（DEPLOY.md §3 已更正为事实链路）。

### 5. 文档与台账
- 新建 `02-development/DEPLOY.md`：服务总览、9100 启动/鉴权/风险边界（含公网不可达实测）、mcp 依赖隔离说明、前端部署链路、.env 新增三键（占位）、**重启恢复手册**（无 systemd，宿主机重启需手动 nohup 9012/9100/Celery）、自测复现命令。
- `~/hermes-workspace/shared/infrastructure/SERVER_REGISTRY.md`：新增 `kb MCP Server` 行（9100 / nohup / ~115MB / KB_MCP_API_KEY 引用 / running），9012 行更新为 nohup + 实际 ~133MB；最近变更追加 A4 条目。
- `infra/.env` 新增 `KB_MCP_API_KEY`（secrets.token_hex(24) 生成，只进 .env）/ `KB_PUBLIC_BASE_URL` / `KB_VIEW_TOKEN_MINUTES=15`；`.env.example` 占位由 A1 已加。

### 已知问题 / 交 A5
1. **无 systemd**：9012/9100/Celery 重启后不自动拉起，恢复手册见 DEPLOY.md §5。
2. `05-temp/mcpstage` 不进 git（05-temp 被 gitignore）：换机/重装需重建（`pip install --target 05-temp/mcpstage mcp==2.3.0`）；start_mcp.sh 对其缺失硬失败，不会出现假启动。
3. JWT 三段"双接受"仍是兜底（A2 遗留），B 块真实对话验证 agent 实际发的头后再定收紧策略。
4. `assets.prev_*` 旧前端产物留档在 deploy/dist 下，A5 统一提交前清理（dist/ 已被 .gitignore 覆盖，不进 git）。
5. `scripts/deploy_frontend.sh` 内容过时（旧 NPM 容器），A5 可顺手更新或删除（本段未动它，避免超出"部署+文档"范围）。

---

## A5: 回归自测 + DEV_REPORT 汇总 + feat/kb-citations 统一提交（t_df00e48f）

**范围**：收尾段——A 块全链路回归自测（证据见下）、DEV_REPORT 汇总、`feat/kb-citations` 统一 commit+push。不新增功能代码；仅新增自测脚本 `03-testing/a5_citation_acceptance.py`（A1-A4 已验证，浏览器视觉留给测试 t_a52daf8a）。

### 1. kb-management 核心回归（2026-10-11 14:42 UTC，9012 本地后端 + Celery + 本地 embedding 8100）
脚本 `05-temp/regression_v2.py`（复用 A 块既有自测）：注册→建 KB→**同库顺序上传 3 份（2 embedding + 1 pageindex 混合）**→轮询→检索。

| 文档 | index_type | 终态 | chunks |
|---|---|---|---|
| r1_first.txt | embedding | **indexed** | 3 |
| r2_second.md | embedding | **indexed** | 4 |
| r3_third.md | pageindex | **indexed** | 0（建树，chunk_count=0 互斥正确） |

`ALL_INDEXED: True`（bug 修复 t_670a7d8a 后第一份 embedding 不再失败 ✅）。检索回归：`hybrid`/`keyword`/`vector` 均 **HTTP 200**（items 10/7/10）。health 全 ok（`mineru`=unreachable 仅影响 pdf/docx，本轮未用）。

### 2. 新功能验收（A 块侧，端到端 API，全部真实运行，2026-10-11）
脚本 `03-testing/a5_citation_acceptance.py`（对运行中的 9100 MCP + 9012 后端；真实 key 从 `infra/.env` 读，不打印）。**11/11 用例全过**：

| # | 用例 | 结果 |
|---|---|---|
| 1 | MCP 无 Bearer（`list_knowledge_bases`） | **401** `{"error":"unauthorized"}` ✅ |
| 2 | MCP `search_knowledge`（真实检索） | **200**，5 items 全含 `doc_url`+`location` ✅ |
| 3 | MCP `rag_query`（真实问答） | **200**，answer 240 字符，5 sources 全含 `doc_url`+`location` ✅ |
| 4 | 深链 URL 形态 | 以 `https://agent.carefold.ai/kb-management` 开头 + `/kb/{id}/doc/{id}` + `chunk=N` + `token=` 全满足 ✅ |
| 5 | 深链公网可达（nginx） | 去 token 走 nginx → **200 text/html**（SPA fallback）✅ |
| 6 | `?token=` 调 4 只读端点（detail/download/content/chunks） | 全部 **200**；download `Content-Disposition: inline; filename=…` + `text/plain` ✅ |
| 7 | view_token 过期（exp=now-1min）读 detail | **401** `{"code":40101,"message":"链接已过期"}` ✅ |
| 8 | 跨文档：doc A 的 token 读 doc B（同 KB） | **403** `{"code":40301,"message":"无权访问该文档"}` ✅ |
| 9 | 跨 KB：doc 的 token 读另一 KB 下同名 doc | **403** `{"code":40301,"message":"无权访问该知识库"}` ✅ |
| 10 | view_token 调写端点 DELETE | **401**（非 access 型 → 拒绝）✅ |
| 11 | 9100 常驻 | 进程在跑（**pid 1472601**）+ 本机直连 `172.19.0.1:9100` **TCP OPEN**（agent 容器侧等价探测）✅ |

**深链真实响应样例（脱敏，token 截断）**：
```
doc_url: https://agent.carefold.ai/kb-management/kb/f8f4d065-7436-4e54-9536-f67f916148c8/
          doc/507ef3a5-6750-4e1e-a0ad-f034af92cc17?chunk=1&token=eyJhbG…pDuE
location: {"type": "chunk", "value": 1}        # embedding 文档
```
（pageindex 文档命中 node 时 `location={"type":"node","value":"n1.2"}` + `node=` 参数，分支已在 A2 单元验证；本轮检索数据以 embedding 文档为主。）

### 3. 已知问题 / 约束
1. **无 systemd**：9012 / 9100 / Celery 均为 host nohup 进程，宿主机重启不自动拉起，恢复手册见 `DEPLOY.md §5`（手动 nohup）。
2. **`05-temp/mcpstage` 不进 git**（05-temp 被 gitignore）：mcp 2.3.0 与主 venv pydantic 2.9.2 冲突，靠该目录 PYTHONPATH 隔离；换机/重装需 `pip install --target 05-temp/mcpstage mcp==2.3.0` 重建，`start_mcp.sh` 对缺失硬失败（不假启动）。
3. **JWT 三段"双接受"仍是兜底**（A2 遗留）：MCP 中间件对合法三段式 JWT 形态放行（仅格式校验不验签）。B 块注册真实对话后确认 agent 实际发的头，再决定是否收紧为仅 `KB_MCP_API_KEY`。
4. **pageindex node 定位精度**：node 锚点为 LLM 建树的 `start/end` 全文字符偏移，定位到节/段级而非精确句子；前端按 chunk 降级渲染（node 缺失时）。非缺陷，属 LLM 建树粒度。
5. **`scripts/deploy_frontend.sh` 过时**（旧 NPM 容器）：实际前端链路是 nginx-test bind mount（见 DEPLOY.md §3），脚本内容未更正（留待后续，未超本段范围）。
6. 浏览器视觉验证（三态原文内嵌、chunk/node 高亮实际效果、token 过期提示条）留给测试 t_a52daf8a。

### 4. 提交
本段将 A1-A5 全部未提交改动 + 自测脚本统一 commit 到 `feat/kb-citations` 并 push（排除 `.env`/`node_modules`/`tsconfig.tsbuildinfo`/`05-temp`/`deploy/dist`，`.env` 仅进本地）。
- **主提交：`1d0980d`**（16 files，+1647/-25）：`feat: 文档引用元数据+深链定位+view_token+MCP 鉴权+9100 常驻`
- 已 `git push origin feat/kb-citations`（远端新分支，PR 入口：https://github.com/harryzhang-carefold/kb-management/pull/new/feat/kb-citations）。
- 不含 bug 修复 t_670a7d8a 的改动（其已单独提交 `edf8ca4`，本提交未触碰其文件）。

---

## LLM 切换到 DeepSeek（t_3cdebd1f，分支 feat/default-pageindex，2026-10-12）

**背景**：kb-management 依赖的 vllm 端点已下线，实测两个旧端点均不可达（TCP timeout、HTTP 000）。本次把 **LLM（PageIndex 建树 + RAG 问答）** 切到 DeepSeek（用户指定）。embedding 不在本次范围。

### 1. 改动（diff）

| 文件 | 改动 |
|---|---|
| `backend/app/core/config.py` | 默认值三处：`llm_base_url` `http://34.121.9.233:4000/v1` → `https://api.deepseek.com/v1`；`llm_model` `default` → `deepseek-flash`；`pageindex_llm_model` `vllm-qwen3.8-27b` → `deepseek-flash` |
| `infra/.env`（**不进 git**） | 写入 `LLM_API_KEY`（来自指定密钥文件，35 字符 sk- 前缀）；新增/对齐 `LLM_BASE_URL=https://api.deepseek.com/v1`、`LLM_API_BASE`（旧名，代码不读，仅为不误导）、`LLM_MODEL=deepseek-flash`、`PAGEINDEX_LLM_MODEL=deepseek-flash`；文件权限收紧 0600 |
| `infra/.env.example` | LLM 段落补 `LLM_BASE_URL`/`PAGEINDEX_LLM_MODEL`，`LLM_MODEL` 由空值改 `deepseek-flash`，并把**曾提交进 git 的真实 key 改为占位**（见已知问题 3） |
| `backend/app/services/pageindex_engine.py` | 仅文档字符串里写死的 `vllm-qwen3.8-27b` → “模型名走 settings.pageindex_llm_model，当前 deepseek-flash”（零逻辑改动） |
| `scripts/start_backend.sh` | **顺带修复的部署阻塞 bug**：redis 预检硬编码 `127.0.0.1:6179` + 旧密码，而实际 redis 在 `6390`（.env：`REDIS_PORT=6390`，无密码）→ `set -e` 下脚本必然退出，`DEPLOY.md §5` 的“手动恢复 9012”路径实际不可用。改为从 `settings` 读取（不硬编码、不打印密码） |

**注**：任务书写“密钥写入项目根 `.env`”，实际代码读的是 **`infra/.env`**（`config.py:10` `parents[3]/infra/.env`）；密钥写进项目根 `.env` 不会生效。已按真实生效路径写入 `infra/.env`（两者都被 `.gitignore` 忽略）。

未改（红线）：`embedding_base_url`/embedding 相关配置、embedding 路径、`feat/pageindex` 与 `feat/kb-citations` 已有语义、`.env` 之外的任何 key 存放。

### 2. 部署（重启加载新配置）

```bash
# 后端 API 9012（新 .env + 新 config.py 需重启；MCP 9100 不依赖 LLM，无需重启）
cd /home/harry.zhang/kb-management && bash scripts/start_backend.sh
# Celery（pageindex 建树在 worker 内执行，必须重启）
bash scripts/start_worker.sh
```
- 两者均为 host 进程（本机无 systemd），起停方式与 `DEPLOY.md §5` 一致；本次以 `persist_on_release` 后台方式拉起。
- 实例：后端 9012（uvicorn，`backend/.venv`），Celery（`-Q kb --concurrency=2`，broker `redis://127.0.0.1:6390/3`）。
- 校验：`ss -ltn | grep :9012`（LISTEN）+ `GET /api/v1/health`（llm=ok）。
- 台账：`~/hermes-workspace/shared/infrastructure/SERVER_REGISTRY.md` 已按实测回写（LLM vLLM 行标记 deprecated、新增 DeepSeek 行、记录本次重启）。

### 3. 自测证据（全部真实运行，2026-10-12 UTC；脚本在 `05-temp/`，不进 git）

**证据 1 — settings 生效 + LLM 真调用**（`05-temp/t_3cdebd1f_check_settings.py`）
```
llm_base_url       = https://api.deepseek.com/v1
llm_model          = deepseek-flash
pageindex_llm_model= deepseek-flash
llm_api_key        = SET(len=35, sk- prefix)          # 不打印明文
llm_client.health() = True  (0.35s)
/v1/models 该 key 可见 = ["deepseek-flash", "deepseek-v4-pro"]
最小 chat (json_mode, pageindex_llm_model) 0.82s → '{"ok": true}'
```

**证据 2 — 系统健康接口 llm=ok**（`GET /api/v1/health`，system.py:50 的 llm 健康检查）
```
本地直连 9012:
{"status":"degraded","services":{"postgresql":"ok","elasticsearch":"green","minio":"ok",
 "redis":"ok","llm":"ok","embedding":"ok","mineru":"unreachable"}}
经 nginx 公网 https://agent.carefold.ai/kb-management/api/v1/health → 同上（llm=ok）；前端 /kb-management/ → 200
```
（整体 `degraded` 仅因 mineru 未起，见已知问题 1；llm、embedding 均 ok。）

**证据 3 — PageIndex 真实建树（DeepSeek，非降级规则树）**
（`05-temp/t_3cdebd1f_e2e_pageindex_rag.py`：登录/签 token → 建 KB → 上传 `index_type=pageindex` → 轮询建树）
```
KB  c6b82a44-9656-487d-a27f-1beabae18bb3
doc 88616ba1-6a7b-4003-8a19-3ae9891c1d1d  t_3cdebd1f_pi_doc.md  1076 bytes / 483 字
poll: status=chunking(0~21s) → indexed(t=24s)，pageindex_status: building → ok
document.status       = indexed
meta.index_type       = pageindex
meta.pageindex_status = ok              ← ok = LLM 真实建树（degraded 才是规则降级树）
tree.model            = deepseek-flash  ← 建树记录在树上，确认走 DeepSeek
tree.node_count       = 2      tree.piece_count = 1
tree.build_ms         = 25815  tree.full_text_chars = 483
tree.version/status   = 1/ok
root  n1  北极星项目技术白皮书（摘要）[0,483]
  └─  n1..1  北极星项目技术白皮书（摘要）全文 [0,483]
```

**证据 4 — RAG 流式问答（pageindex 与默认 hybrid 两条路径都走通）**
```
(a) retrieval_mode=pageindex（同一 KB/文档）
    POST /knowledge-bases/{kb}/chat  HTTP 200
    SSE events = {meta:1, token:32, sources:1, done:1, error:0}
    来源: t_3cdebd1f_pi_doc.md  node=n1..1  title='…全文'  score=0.98  range=[0,483]
    答案（55 字，5.54s）：总负责人=林澈[1]，验收口令=紫罗兰-7391[1]   ← 与文档一致
(b) 默认 hybrid（embedding + ES，KB 77b260a7，含 1618 chunk 的 embedding 文档）
    SSE events = {meta:1, token:91, sources:1, done:1}，来源 3 条，答案 174 字（2.21s），内容正确
(c) 仓库既有端到端脚本 tests/e2e_test.py → 8/8 全 PASS（含 hybrid 检索 + RAG 流式 + 会话落库）
```
→ `llm_client.chat()`（pageindex 建树/检索）与 `llm_client.chat_stream()`（RAG 问答）均实测走通 DeepSeek。

**证据 5 — 端点连通性探测（`05-temp/t_3cdebd1f_endpoint_probe.py`）**
```
TCP: 34.121.9.233:4000 → timeout(FAIL)   34.64.61.208:4000 → timeout(FAIL)
     api.deepseek.com:443 → OPEN 0.01s   127.0.0.1:8100 → OPEN
HTTP: 旧 LLM 000（不可达）  旧 Embedding 000（不可达）
     DeepSeek 401（无鉴权请求，网络+协议通）  本地 kb-embed 200
```

### 4. 已知问题 / 约束

1. **PDF 解析链路仍不可用（与本次改动无关）**：`kb-mineru` 容器/镜像在本机不存在（`docker ps -a` 无该容器），pdf/docx/xlsx/图片解析报 `MinerU 解析异常: [Errno 111] Connection refused`，存量 PDF 文档状态均为 `failed`。因此任务书里“上传小 PDF 选 pageindex”**无法按原样执行**，本次以 `.md`（本地解析，同一 pageindex 建树/检索链路）完成建树实测；恢复 PDF 需按 `infra/docker-compose.yml` 的 `mineru` profile 构建镜像（首次还需下载 ~2GB 模型），属独立事项。
2. **`deepseek-flash` 是推理型模型**：`reasoning_content` 与 `content` 同源计入 `max_tokens`。实测 `max_tokens=32` 时全部预算被推理吃掉 → `finish_reason=length`、`content` 为空（`ai_client.chat` 返回 `''`）。当前配置：建树 `max_tokens=8192`（实测通过）、检索推理 `max_tokens=1024`（本次 483 字文档实测通过，score 0.98）、RAG 流式 `2048`（实测通过）。**风险点**：`pageindex_retrieve` 的 1024 对长 outline/复杂问题可能被推理吃满而返回空选区，建议后续提到 2048（本轮未改，避免超出任务范围）。
3. **`.env.example` 曾在 git 中泄露真实 vllm key**：本轮已把它替换为占位，但 **git 历史里仍存在该 key**（该 key 属已下线的 34.121.9.233 端点，实际风险低）。是否需要轮换/清理历史由褚岩决策，本轮不动历史。
4. **`config.py` 的 `embedding_base_url` 默认值仍指向已下线的 `34.64.61.208:4000`**（红线：本次不改 embedding）。实际生效值由 `.env` 的 `EMBEDDING_BASE_URL=http://127.0.0.1:8100/v1`（本地 kb-embed 容器）覆盖，health 实测 embedding=ok。新环境若无 `.env` 覆盖会打到死端点。
5. **部署脚本修复**（见 §1）：`scripts/start_backend.sh` 的 redis 预检参数此前硬编码且与 `.env` 漂移，导致 `DEPLOY.md §5` 的手动恢复路径失效；已改为读 settings。同类硬编码在 `scripts/start_worker.sh` 中不存在（worker 走 `celery_app` 配置）。
6. **文档/设计稿未同步**：`00-management-PAGEINDEX_BRIEF.md`、`00-management-PAGEINDEX_DESIGN.md`、`docs/prd.md`、`docs/architecture.md`、`03-testing/TEST_PLAN.md` 中仍写旧端点 `34.121.9.233:4000` / 旧模型 `vllm-qwen3.8-27b`。它们是历史设计记录，本轮未改（避免混淆历史），需要时单独更新。
7. **未重启 MCP 9100**：其不依赖 LLM（检索走 ES/pageindex 引擎的自身进程），本轮重启项仅为 9012 + Celery。

### 5. 一句话总结

kb-management 的 LLM 已从已下线的 vllm 切到 DeepSeek（`api.deepseek.com/v1` + `deepseek-flash`，密钥只进 `infra/.env`），9012 与 Celery 已重启生效，四项自测（settings 生效 / health llm=ok / PageIndex 真实建树 status=ok·model=deepseek-flash / RAG 流式问答两条路径 + 仓库 e2e 8/8）全部真实通过；embedding 与 PDF(MinerU) 两项环境限制如实记录未修。

---

## BUG-01（P1）修复：检索 `vector`/`hybrid` 模式跨知识库泄露（t_f4aac859，2026-10-12）

> 完整报告（根因 / ES 层直证 / 风险点排查 / 证据）见 **`02-development/BUGFIX_BUG01_CROSS_KB_LEAK.md`**。本节为汇总。

### 1. 根因与改动

`backend/app/utils/es_client.py` 的 `hybrid_search()` kNN 分支顶层带了**没有 kb_id 过滤**的 `"query": {"match_all": {"boost": 0}}`；ES 8 对 `knn` 与顶层 `query` 的命中**取并集**，于是本 KB 的 kNN 真命中不足 `size=top_k` 时，全索引其它知识库的 chunk（`_score=0.0`）被并入结果填满条数 → 跨租户泄露（`kb_chunks` 为多租户共享单索引，隔离完全依赖 `kb_id` filter）。

改动（唯一代码文件 `backend/app/utils/es_client.py`）：

1. 删除 kNN 请求体的顶层 `query`，过滤只由 `knn.filter = base_filter` 承担（附根因注释防回归）；
2. 两个检索分支各加一道结果层防御：命中 `_source.kb_id != 查询 kb_id` → 丢弃并告警（多租户隔离红线兜底）；
3. 返回结构、`vector/hybrid/keyword` 三模式语义、RRF 融合逻辑不变。

### 2. 验证（全部真实运行，2026-10-12 UTC）

| 验证 | 结果 |
|---|---|
| `bash 03-testing/curl/case_BUG-01.sh`（mode=vector） | **`SUMMARY case=BUG-01 mode=vector foreign_docs=0 verdict=PASS`**（修复前 `foreign_docs=1 BUG_REPRODUCED`） |
| `BUG_MODE=hybrid bash …/case_BUG-01.sh` | **`foreign_docs=0 verdict=PASS`**（修复前 `foreign_docs=1`） |
| 双向隔离 × 三模式自测（`05-temp/t_f4aac859_verify.py`，KB A=被测库 / KB B=泄露片段归属库） | **16/16 PASS**；`vector`/`hybrid` 命中 `score_zero=0`（不再有 score=0 填充项） |
| ES 层机制直证（`05-temp/t_f4aac859_es_evidence.py`） | OLD 请求体：10 条中 **3 条他库 chunk（score=0）**；NEW 请求体：7 条**全属本 KB**；`NEW ⊆ OLD` 且 **丢失真命中 0 条**（只少了 3 条跨库填充） |
| 仓库回归 `tests/e2e_test.py` | **8/8 PASS** |
| 防御层触发计数（重启后后端日志） | 0 次 → 泄露是在 ES 查询层被消除，非 Python 兜底掩蔽 |
| 自建 fixture 端到端 + 反证（`05-temp/t_f4aac859_verify_fixture.py`） | **15/15 PASS**：自建 A(9 chunk)/B(11 chunk) 两库，A 三模式 `foreign=0`；同一份数据下"修复前请求体"**必泄露**（10 条含 1 条他库 score=0）、"修复后"0 条；用后即删（ES 两库 chunk 归零） |
| 同类风险点排查 | 全仓 `es.search` 仅 2 处（本次均已过滤）；`count(kb_id=None)` 的 `match_all` **无调用点**（潜在项，登记观察） |

### 3. 部署

- 重启 kb 后端 9012 加载修复（2026-10-12 03:12:11 UTC），`health` 200（本地与 nginx-test 公网同值），RSS 149MB，无新增容器/端口；
- 启动方式升级为 **systemd user 常驻单元 `kb-backend-9012.service`（`Restart=always`）**——此前 9012 寄生在 agent 会话 scope 内的 `nohup`，会话结束即被回收；`DEPLOY.md §5` 已同步；
- **未改** nginx 配置（红线）、Celery、MCP 9100、前端 dist、embedding。

### 4. 已知问题

1. `es_client.count(kb_id=None)` 用 `match_all` 统计整索引：当前**无调用点**，未改（新增统计接口时必须要求 kb_id）。
2. 同分支并行任务 t_7f451c5f 正在改 `documents.py`/`pageindex_engine.py`/前端；本次提交只含 `es_client.py` + 文档，未触碰其文件，**未 push**。
3. Celery 仍寄生在别的 agent 会话 scope（PID 3043762/3043869/3043870），该会话结束会被回收；本次未动（避免双 worker 抢队列），建议后续统一为 `kb-celery.service` 常驻单元。
4. `mode=vector` 不再返回 `score=0` 的全库填充项 → 真命中不足 `top_k` 时条数会少于 `top_k`（此前是被他库 chunk 填满的假满足）。


---

## 上传默认索引方式 embedding → pageindex（t_7f451c5f，分支 feat/default-pageindex，2026-10-12）

### 1. 改动（4 个文件）

| 文件 | 改动 |
|---|---|
| `backend/app/api/documents.py` | `upload_doc` 的 `index_type: str = Form("embedding", pattern=...)` → **`Form("pageindex", ...)`**（+ docstring 默认值同步） |
| `frontend/src/views/KbDetailView.vue` | `const indexType = ref<'embedding' \| 'pageindex'>('embedding')` → **`('pageindex')`**（+ 注释同步；22-31 行 radio 文案/说明是跟随选中态渲染的，无需改） |
| `backend/app/services/pageindex_engine.py` | 新增 `BUILD_MAX_TOKENS=32768` / `RETRIEVE_MAX_TOKENS=8192` 两个输出预算常量；建树**解析失败也触发一次重试**（见 §2 缺陷 A/B） |
| `tests/e2e_test.py` | 第 4 步上传**显式**传 `index_type="embedding"`（该套件 6/7 步断言的是 embedding/hybrid 链路，不能依赖默认值，见 §2） |

**红线兜底逐条核对（**未改**，改动后 grep 复核仍在）：**
```
backend/app/workers/tasks.py:72      new_meta["index_type"] = old_meta.get("index_type", "embedding")
backend/app/workers/tasks.py:119     if (doc.meta or {}).get("index_type") == "pageindex":   # 分流判断
backend/app/api/documents.py:289     index_type = (doc.meta or {}).get("index_type", "embedding")
backend/mcp_server.py:100            "index_type": (d.meta or {}).get("index_type", "embedding")
frontend KbDetailView.vue:60-61,272  (row.meta?.index_type || 'embedding')
```
即：**新建上传默认 pageindex，历史无 `index_type` 的文档仍按 embedding 兜底**（含显示、重建索引、MCP 引用拼装）。

### 2. 自测中暴露并修复的两个真实缺陷（pageindex 变成默认后必须修）

**缺陷 A — 建树输出预算被推理吃满 → 静默降级成规则树（默认路径 20% 命中）**

`deepseek-flash` 是推理型模型，`reasoning_content` 与 `content` **同源计入 `completion_tokens`**。
建树固定 `max_tokens=8192` 时，模型思考可吃掉全部预算 → `content` 为空 → `_extract_json` 抛
`LLM 输出不含 JSON 对象` → 上层降级为 heading 规则树（`pageindex_status=degraded`）。

线上 worker 日志（修复前，默认上传一上传就命中）：
```
2026-10-12 02:53:36 [upload] task published: doc=dde3cabc-…（未传 index_type）
2026-10-12 02:54:23 WARNING pageindex_engine:build_tree_index:502 -
  [pageindex] LLM 建树失败（doc=dde3cabc-…）: LLM 输出不含 JSON 对象 → 降级 heading 规则树
2026-10-12 02:54:25 INFO build_pageindex_task:279 - [pageindex_build] done … status=degraded
```
定量（`05-temp/t_7f451c5f_budget_probe.py`，同一 484 字文档、同一 prompt 真实调用）：
```
max_tokens=8192  n=5
  trial1: finish=stop   completion=8134 content_len=1042 reasoning_len=18569 parse=OK
  trial2: finish=length completion=8192 content_len=   0 reasoning_len=23932 parse=FAIL   ← 预算截断
  → 4/5 parse OK（20% 降级）
max_tokens=32768 n=3
  trial0/1/2: finish=stop completion=5625/9750/8465 content_len=679/272/263 parse=OK
  → 3/3 parse OK
```
修复：`max_tokens=32768` + **解析失败也走原来那条“带错误信息重试一次”**（原实现只在“结构校验失败”时重试，
解析失败直接上抛降级）。

**缺陷 B — 检索选节点输出预算 1024 同样可被推理吃满 → 空结果**

`pageindex_retrieve` 固定 `max_tokens=1024`。实测 6 次检索调用中 1 次
`completion=1024 / finish_reason=length / content 为空` → 解析失败 → 返回 0 条
（`05-temp/t_7f451c5f_retrieve_matrix.py`，修复前）。这正是 t_3cdebd1f 交接里标记的“建议后续提到 2048”风险点，
pageindex 成为默认后它会直接打在默认链路上，故本轮一并提到 `RETRIEVE_MAX_TOKENS=8192`（只抬上限，不改语义/返回结构）。

> 说明：这两处是**同一类**缺陷（推理型模型的输出预算），不是本次 2 处默认值改动的语义变化；
> 但它们决定“默认 pageindex 是否真的可用”，属本次交付的必要条件。

### 3. 自测证据（5 项，全部真实调用，非构造数据）

**证据 1 — 契约层：OpenAPI 默认值（`05-temp/t_7f451c5f_openapi.py`）**
```
file       {'type': 'string'}
index_type {'type': 'string', 'pattern': '^(embedding|pageindex)$', 'default': 'pageindex'}
required = ['file']       ← 不传 index_type 即 pageindex
```

**证据 2 — 不传 index_type 走 API 上传：meta.index_type=pageindex 且真实建树 ok（非降级）**
（`05-temp/t_7f451c5f_selftest.py` → `_out3.txt`，7/7 PASS）
```
用例1 不传 index_type 上传 → http=200
  poll: status=chunking(0~36s) → indexed(t=40s)，pageindex_status: building → ok
  meta.index_type       = pageindex
  meta.pageindex_status = ok          ← ok = LLM 真实建树（degraded 才是规则降级树）
  tree.model            = deepseek-flash   tree.node_count = 6   build_ms = 37727
用例2 pageindex 检索（'北极星项目采用了哪些核心组件？'）
  total=2 took_ms=2148  → n1..3 '2. 核心组件' score=0.98（内容含原文片段）/ n1 score=0.72
  多问法覆盖：核心组件/环境要求/验收口令/总负责人/验收口令 → 5/5 有命中
用例3 RAG 流式问答 retrieval_mode=pageindex → events={meta:1,token:83,sources:1,done:1}，sources=1，答案 143 字带引用
用例4 回归：显式 index_type=embedding → status=indexed chunk_count=1（pageindex_status 为空=不走树）
       向量检索命中该文档（match=vector score=0.758）
[RESULT] 7/7 PASS
```

**证据 3 — 建树稳定性（修复后连续 3 次默认上传，`05-temp/t_7f451c5f_stability.py`）**
```
run0: status=indexed pi=ok nodes=6 build_ms=41235 检索命中=1 总耗时=45.9s
run1: status=indexed pi=ok nodes=2 build_ms=46592 检索命中=1 总耗时=51.1s
run2: status=indexed pi=ok nodes=5 build_ms=44423 检索命中=1 总耗时=50.1s
[RESULT] 3/3 建树 ok（非降级）；node_count 分布=[6,2,5]；检索命中=[1,1,1]
```
（修复前同一路径为 4/5 成功 + 1 次 degraded；修复后 3/3 ok，合计 4/4 默认上传均非降级。）

**证据 4 — 线上 UI：默认选中 pageindex，且不碰 radio 直接上传就走 pageindex**
（无密码自动化：本地签发 access_token 注入 `localStorage.kb_token` 后驱动真实浏览器，`05-temp/t_7f451c5f_ui_prep.py` + `ui_verify.py`）
```
DOM 实测（页面 https://agent.carefold.ai/kb-management/kb/21f3f148-…）：
  radios: [{text:"Embedding（分块+向量）", active:false, inputChecked:false},
           {text:"PageIndex（树索引）",  active:true,  inputChecked:true}]   ← 默认选中 pageindex
  uploaded_desc: "无向量、基于层级树 + LLM 推理检索；上传后异步建树（约 30-120s），一个文档只建一种索引。"
  → 该说明只在 indexType==='pageindex' 时渲染，作为第二重佐证

CDP setFileInputFiles 上传 695B .md（未触碰 radio）→ 文档列表行为：
  "t_7f451c5f_ui_doc.md  md  695 B  0  PageIndex  建树中  分块中 …"
回读：status=indexed index_type=pageindex pageindex_status=ok node_count=2 build_ms=14317
  pageindex 检索 '星尘知识库的验收口令是什么？' → total=2（n1..1 score=0.9 / n1 score=0.85，均含口令原文）
  pageindex 问答 → sources=2，答案 "星尘知识库的验收口令是 **靛蓝-5824**。[1][2]"
[RESULT] UI 默认链路端到端 PASS
```

**证据 5 — 回归 + LLM 依赖可用（`05-temp/t_7f451c5f_mode_mismatch.py`、`tests/e2e_test.py`）**
```
LLM 依赖：llm_base_url=https://api.deepseek.com/v1  llm_model=pageindex_llm_model=deepseek-flash
          llm_client.health()=True   models=['deepseek-flash','deepseek-v4-pro']
          （任务书里的 llm_base_url=34.121.9.233:4000 已在 t_3cdebd1f 实测 TCP timeout 下线并切走）
仓库 e2e：tests/e2e_test.py 8/8 PASS（含 hybrid 检索 + RAG 流式 + 会话落库；上传步骤已显式 embedding）
存量文档：73 篇（embedding 51 / pageindex 22），**无 index_type 的 0 篇** → 兜底分支不影响任何存量数据
```

### 4. 部署（沿用既有方式，已生效）

**前端（本轮实际执行）**
```
cd frontend && npm run build                         # vite/rolldown，确定性构建（同源两次构建 md5 一致）
mv 02-development/deploy/dist/assets → assets.prev_031057
cp -r frontend/dist/assets 02-development/deploy/dist/assets
cp frontend/dist/index.html 02-development/deploy/dist/index.html && sed -i 's/crossorigin //g'
docker exec nginx-test nginx -s reload               # nginx-test: /home/harry.zhang/kb-management/02-development/deploy/dist → /usr/share/nginx/kb-management (ro)
```
公网验证：
```
GET https://agent.carefold.ai/kb-management/ → 200，入口 assets/index-CaTnCPvY.js（= 本次构建）
KbDetailView-BFQ19UFl.js 内含 `o(`pageindex`)`（indexType 默认值）与 radio 组绑定
```
> 顺带发现并修正的**部署滞后**：线上 dist 原为 10-11 14:28 构建，**不含 1d0980d 的前端改动**
> （DocView.vue 引用深链视图 + KbChatView + api/request.ts + router/index.ts，该提交时间 14:51 晚于构建）。
> 本轮“重建 + 换装”顺带把 1d0980d 的前端一并带上线（前后端同类功能，服务端 A1-A4 早已就绪）。

**后端（本轮实际执行）**
```
9012  uvicorn: 重启加载新代码（启动脚本 scripts/start_backend.sh；旧进程 TERM 后清理，健康 200）
Celery: 重启（旧 main 进程 TERM 不退出 → SIGKILL 清理，确保只剩 1 个 worker + 2 子进程；queue=kb）
未重启：MCP 9100（不依赖本次改动；pid 2382073 持续 running）
```
> **补充（并发卡影响，已核对）**：本轮期间同仓并行卡 t_f4aac859 于 03:12 把 9012 的常驻方式升级为
> **systemd user 单元 `kb-backend-9012.service`（Restart=always）**，故 03:12 之后线上 9012（pid 3056922，
> PPID=systemd --user）由 systemd 托管并从工作树重新加载代码。本报告 §3 证据 4/5 与 §5 的实测均运行在该实例上
> （health 200、默认 pageindex 上传→建树 ok→检索/问答正常），即**结论对当前运行实例有效**。
> Celery 目前仍是会话内 nohup 进程（未做 service），本轮的重启仅影响 worker 进程本身。
**部署后实测占用（`05-temp/t_7f451c5f_env_snapshot.sh`，已回写台账）**
```
容器: kb-pg 55.16MiB / kb-es 1.184GiB / kb-minio 137.6MiB / kb-dev-redis 12.25MiB
      kb-embed 1.195GiB (上限 4G) / nginx-test 10.7MiB        ← 无新增容器、无新增端口
host 进程 RSS: 9012 ≈150MB / 9100 ≈130MB / celery 112+145+128MB
端口: 80/443/9011/9012/9200/9002/8100/9100 均监听正常（无变化）
```
台账更新：`~/hermes-workspace/shared/infrastructure/SERVER_REGISTRY.md`（变更日志新增本条）。

### 5. 已知问题 / 风险

1. **【P1，需产品决策】默认上传=pageindex 与默认问答模式=hybrid 错配**：新文档默认走树索引、**不写 ES 分块**
   （`chunk_count=0`），而问答接口/问答页的默认 `retrieval_mode` 仍是 `hybrid`（`schemas.py:240`、
   `KbChatView.vue:103`）。实测同一篇默认上传的文档：
   ```
   默认（不传 retrieval_mode → hybrid）: sources=0  answer="知识库中未找到相关内容。…【参考片段】为空…"
   显式 retrieval_mode=pageindex      : sources=1  answer="…验收口令是：靛蓝-5824。[1]"（正确）
   ```
   这正是 `tests/e2e_test.py` 第 7 步在改动后首次运行失败的原因（该套件已改为显式 embedding 上传）。
   **本轮未改问答默认模式**（任务书限定只改 2 处，且问答默认全局改为 pageindex 会反向打断 51 篇 embedding 存量库的问答）。
   建议由产品/PM 决策：问答页按 KB 索引构成自动选模式，或在识别到「本 KB 无 ES 分块」时给出明确引导。
   → 已建后续卡（见完成说明）。
2. **推理型模型的输出预算 = 成本与延迟**：`deepseek-flash` 单次建树思考可吃掉 ~2.5 万字符 reasoning
   （completion_tokens 最高观测 9750），单篇建树 ~25-50s、检索单次 ~2-4s。预算抬高只影响“上限”，
   但 reasoning tokens 是按量计费的，KB 规模上来后需评估成本；若要根治，应换非推理模型或支持关闭 thinking。
3. **小文档的树粒度不稳定（既有特性，非本次引入）**：同一 484 字文档，LLM 建树结果是 `node_count=2`（单叶子
   “全文”）到 `6`（按 heading 展开）之间浮动。树退化成单叶子时，若该叶子 summary 未覆盖问题涉及的细节，
   检索会**按设计**返回空选区（提示“未检索到相关内容，换一种问法”），而不是乱凑。
   建议（非阻塞）：小文档建树时要求按 heading 展开、或对单叶子树在检索侧加“整篇兜底”。
4. **线上前端 dist 曾滞后于代码**：见 §4 备注，本轮已同步到 1d0980d + 本次改动。
5. **`node_id` 出现双点 `n1..1`**（`_renumber` 在单分片时 `prefix="n1"` + 子节点 `n1.1` → `"n1" + "." + ".1"`）：
   该 id 会出现在 outline、sources.metadata.node_id 与引用深链里，不影响检索/定位实测结果。
   属既有实现，本轮**未改**（改 id 方案会动到存量文档的存储语义）。
6. **并发写同一工作树**：本轮自测期间，同仓并行运行着另一张开发卡（t_f4aac859，同 profile、同
   `workspace_path`、同分支），期间 9012 被对方重启过一次（03:12）。本轮验证结论均在
   各自时间点真实有效；`02-development/DEV_REPORT.md` 是本轮唯一共享写入点（追加式写入）。
   → 已在卡片上标注 `hotspot`。

### 6. 一句话总结

上传文档的默认索引方式已从 embedding 改为 pageindex（后端 Form 默认值 + 前端 radio 默认值，兜底逻辑一处未动），
并顺带修掉「pageindex 成默认后才暴露」的两个真实缺陷——推理型模型输出预算把建树压成降级树（8192→32768，另加解析失败重试）、
检索选节点被截断返回空结果（1024→8192）；重构后的 dist 已换装到 nginx 挂载目录并公网生效（默认选中 pageindex、
不碰 radio 直接上传确实走树索引并建树 ok），7/7 自测 + 3/3 建树稳定性 + UI 端到端 + 仓库 e2e 8/8 全部真实通过。

---

## BUG-06（P1，部署缺口）修复：MCP :9100 常驻化并加载 BUG-01 修复（t_29066864，2026-10-12）

> 完整报告见 **`02-development/BUGFIX_BUG06_MCP_DEPLOY.md`**。本节为汇总。

### 1. 问题与根因

VERIFY-6（`t_87e536bf`）独立裁定：BUG-01 的**代码修复 PASS**，但 MCP `search_knowledge`（:9100）
**仍跨库泄露**——:9100 是**裸进程**（PID 2382073，启动 00:43:24 UTC），早于 `es_client.py` 修复文件
mtime（03:11:00 UTC）2h28m，模块未重载 → MCP 侧跑的还是修复前 `hybrid_search`。属**部署缺口**，非代码缺陷。

### 2. 改动（1 个新增单元文件 + 文档；未改任何代码语义）

| 项 | 内容 |
|---|---|
| 新增 | `~/.config/systemd/user/kb-mcp-9100.service`（持久单元文件，`enabled`；`Restart=always`/`RestartSec=5`；`ExecStart=/bin/bash scripts/start_mcp.sh`；日志 append `05-temp/mcp_9100.log`） |
| 切换 | `kill -TERM 2382073 2381809` → `daemon-reload` → `enable` → `start`（就绪后 PID 3089178，03:27:02） |
| 文档 | `02-development/DEPLOY.md`：§1 服务总览、§2.1 启动方式（单元优先/nohup 兜底）、**§5.0 新增「改代码后重启口径」**、§5 恢复手册与单元文件原文、§6 自测复现 |
| 未动 | `es_client.py`（红线）、`scripts/start_mcp.sh`、nginx、Celery、前端、服务器台账以外资源、测试侧夹具 |

### 3. 部署验证（全部真实执行，2026-10-12 UTC）

```
[同夹具对照 kb_id=30f60da2… kb-docs=1 mode=hybrid top_k=10]
  修复前 03:26 PID 2382073(00:43:24 启动) items=10 foreign_docs=1  → BUG_REPRODUCED exit=2
  修复后 03:27 PID 3089178(03:27:02 启动) items=9  foreign_docs=0  → PASS exit=0
  （修复后 9 条 score 与修复前本 KB 9 条逐位一致，第 10 条他库项消失）
[MCP 三模式]  hybrid PASS / vector PASS / keyword PASS（items=9 foreign_docs=0）
[回归]        case_BUG-01 vector/hybrid/keyword 三模式 foreign_docs=0 PASS；
              case_NGX-01/02/03/04/05/06/07/10 全 PASS（NGX-06 items=9，修复前 10）
[常驻性]      kill -9 主进程 → 10s 内 systemd 自动拉起（NRestarts=1，PID 3093498，03:28:30），:9100 重新 LISTEN
[可达性]      a4_mcp_smoke.py 无 key 401 / 错 key 401 / 正确 key 200；
              agent 容器 172.19.0.1:9100 TCP OPEN + HTTP 200 initialize（跨容器链路未退化）
[进程级证据]  :9100 进程启动时刻晚于 es_client.py mtime（03:11:00）→ 确已加载修复后代码
```

### 4. 资源占用（已回写台账）

`kb-mcp-9100.service`：MainPID 3093498，内存 ≈92MB（`systemctl show MemoryCurrent` 96,370,688 B），
端口占用不变（0.0.0.0:9100），无新增容器、无新增端口；单元文件 1 个（1.0KB，`~/.config/systemd/user/`）。

### 5. 已知问题 / 风险（详见报告 §6）

1. **验证 KB 被我方回归写脏**：重放 `case_NGX-01/03/05`（卡片要求）向 `kb.json` 的 KB 上传 3 个文档 →
   该 KB 由 1 文档/9 chunk 变 4 文档/18 chunk，使 `case_BUG-06.sh` 判别力下降；因红线与并发测试卡
   （`t_32351222` running）**未清理，只报告**；决定性对照是「修复前后同为 1 文档」那组数据。
2. **`pdf_3mb.pdf` / `pdf_1_1mb.pdf` 上传后 `status=failed`（0 chunk）**：本次重放观察到，疑与
   parse 引擎（`/api/v1/parse-engine` 报 `mineru=unreachable`）有关；非本卡引入，另行待查。
3. **9012 单元仍是 transient**（`systemd-run` 起，reboot 后不自动恢复）：已在 `DEPLOY.md` §5 注②登记为
   后续建议；本次未改（红线：不动已验证 PASS 的 9012 链路）。**Celery 仍是 nohup 裸进程**（沿用既有登记）。
4. **并发写码**：本卡执行期间另一张本人卡 `t_efead8b4`（检索/问答 auto 模式，running）于 03:28:17 重启过
   9012；若其再改 `es_client.py`/检索链路，**必须按 `DEPLOY.md` §5.0 同时重启 9100**，否则会重演 BUG-06。
   → 已在卡片上标注该并发事实。

### 6. 一句话总结

MCP :9100 已从裸进程常驻化为 systemd user 单元（`Restart=always`，实测 kill -9 自愈）并重启加载 BUG-01 修复：
同一夹具下 MCP `search_knowledge` 由 `items=10 / foreign_docs=1` 变为 `items=9 / foreign_docs=0`，
`case_BUG-06.sh` 转 **PASS**，BUG-01 三模式与 NGX-01/02/03/04/05/06/07/10 回归全 PASS，跨容器可达性与鉴权未退化，
`DEPLOY.md` 已补「改 `es_client.py` 必须重启 9012 与 9100 两处」口径；待测试侧重放复核后关闭。


---

## 检索/问答默认模式 `auto`（智能）：按 KB 索引构成自动路由 + 混合库联邦检索（t_efead8b4，分支 `feat/default-pageindex`，2026-10-12）

**规格**：`01-product/PRODUCT_DECISIONS.md` §PD-001 + `01-product/PRD-AUTO-RETRIEVAL.md`（F1–F8 / AC1–AC11 / 红线）。
**触发**：t_7f451c5f 暴露的默认值错配 —— 上传默认 `pageindex`（不写 ES 分块）+ 问答默认 `hybrid` → 默认链路 0 来源。

### 1. 改动清单（13 文件，未动任何显式 mode 分支 / es_client / pageindex_engine / mcp_server）

| 文件 | 改动 |
|---|---|
| `backend/app/services/kb_index.py` **（新增）** | `kb_index_composition(db, kb_id)`：单条 SQL 聚合出 `{embedding_docs, pageindex_docs}`（口径同 PRD §F2，不缓存跨请求） |
| `backend/app/services/auto_retrieval.py` **（新增）** | `auto` 路由执行体：`run_auto()`（es/pageindex/both/none）、F4 合并、F5 单腿降级、F6 五条文案常量 |
| `backend/app/schemas/schemas.py` | `SearchReq.mode` / `ChatReq.retrieval_mode`：pattern 加 `auto`，默认值 `hybrid` → `auto`（OpenAPI 已核） |
| `backend/app/api/search.py` | 新增 `mode == "auto"` 分支（在原 pageindex 分支**之前**，红线分支 42–46 行原样保留）；`message` / `degraded` 承载 |
| `backend/app/services/rag_engine.py` | `stream_answer()` 新增 `auto` 分支 + `db` 参数；`meta` 事件新增可选 `notice`；显式 pageindex / hybrid 分支逻辑一字未改 |
| `backend/app/api/chat.py` | 把 `db` 传给 `stream_answer`；`meta` 事件 payload 透传 `notice` |
| `backend/app/api/knowledge_bases.py` | 新增 `GET /{kb_id}/index-stats`（鉴权同 KB 详情，404 沿用 `not_found`） |
| `frontend/src/api/index.ts` | `search(... mode='auto')`、`chatStream(... retrievalMode='auto')`；SSE `meta.notice` 透传到 `onDone` |
| `frontend/src/views/KbChatView.vue` | 模式组首位「智能（推荐）」+ 默认 `'auto'` + 小字提示 + 灰色 `notice` 提示条 |
| `frontend/src/views/KbSearchView.vue` | 同上（渲染 `message` 为灰色提示条） |
| `frontend/src/views/KbDetailView.vue` | PageIndex 说明追加一句「问答与检索时选择「智能」或「PageIndex」模式即可命中本类文档。」 |
| `docs/api.md` | `auto` 取值/默认值、路由与合并规则（含"归一化分只用于排序、不是阈值"）、5 条文案、`index-stats`、SSE `meta.notice`；顺带修正上传 `index_type` 默认值描述（`embedding`→`pageindex`，上一卡遗漏） |
| `05-temp/t_efead8b4_*.py/.sh` | 5 个自测/验证脚本 + 输出（见 §4） |

**未改**：`es_client.hybrid_search` 内部、`pageindex_engine` 内部、`mcp_server.py`（MCP 默认 `hybrid`，枚举不含 `auto`）、上传默认 `index_type=pageindex`（`documents.py:73`）、`tests/e2e_test.py`（断言语义未动）、nginx 配置、任何容器本体。

### 2. 关键实现决策（含对规格的 3 处显式裁定）

1. **单腿不归一化**：F4 的分数归一化只发生在"混合库两路合并"时；单腿 `auto` 直接透传该腿原始分数与顺序 → 与对应显式模式**逐条一致**（AC3 要求"items 与 mode=hybrid 完全相同"）。已写入 api.md 与代码注释。
2. **去重键加 `node_id`**：F4 规定去重键 `(document_id, chunk_index)`，但 pageindex 命中的 `chunk_index` 是"文档内首个 chunk 的锚点"（整篇同值），严格按二键去重会把**同一文档的多个树节点合并成 1 条**（问答上下文被削）。实现为 `(document_id, chunk_index, metadata.node_id or "")`：ES 命中无 `node_id` → 退化为规格中的二键，语义等价且不误合并。`_dedup_key()` 注释 + api.md 记录。
3. **chat 的 ES 腿取数沿用 `settings.rag_top_k`**、最终截断到 `top_n`（与既有 `hybrid` 问答路径完全一致），而非把 `top_n` 直接当 ES 取数条数 → 纯 embedding 库的 `auto` 问答与改动前 `hybrid` 逐条同源。
4. 混合库两腿**串行执行**（先 ES 后 pageindex），`took_ms` 为实际墙钟；`degraded` 仅回 `["pageindex"]`（规格未定义 es 腿降级标记，ES 腿异常沿用现状：embedding 不可用 → es_client 内退化关键词）。

### 3. 部署（本次无新增容器/端口，台账已回写）

| 项 | 操作 | 实测 |
|---|---|---|
| kb 后端 9012 | `systemctl --user restart kb-backend-9012`（systemd user 单元，uvicorn 无 `--reload`） | `health=200`，`llm=ok / embedding=ok / es=green`；PID 3093130，`MemoryCurrent=122,064,896 B ≈116MB` |
| kb MCP 9100 | `systemctl --user restart kb-mcp-9100`（DEPLOY §5.0：检索链路改动建议一并重启） | 端口 0.0.0.0:9100 不变；PID 3107592，`MemoryCurrent=95,412,224 B ≈91MB` |
| 前端 | `vite build` → 换装 `02-development/deploy/dist`（旧 assets 留档 `assets.prev_033028`）→ `docker exec nginx-test nginx -s reload` | 公网 `https://agent.carefold.ai/kb-management/` 200；懒加载 chunk `KbChatView-Dh7oHtit.js` / `KbSearchView-BrUHZm5U.js` 各含「智能（推荐）」与提示小字；**12 个 js 本地 dist 与线上 md5 逐个一致** |
| 容器/端口 | 无新增、无删除 | kb-pg 59.61MiB / kb-es 1.22GiB / kb-minio 134.4MiB / kb-dev-redis 8.75MiB / kb-embed 1.192GiB(上限 4G) / nginx-test 13.09MiB（`docker stats --no-stream`） |

台账：`~/hermes-workspace/shared/infrastructure/SERVER_REGISTRY.md` 已追加本次变更条目（无新增端口/容器，仅重启与前端换装）。

### 4. 自测证据（全部真实调用 9012 / 9100 / 数据库；脚本在 `05-temp/`）

| 脚本 | 覆盖 | 结果 |
|---|---|---|
| `t_efead8b4_selftest.py`（HTTP 端到端，输出 `t_efead8b4_all_out.txt`） | F1 + Fixture(4 KB) + AC1/AC2/AC3/AC4/AC5/AC6/AC7/AC8 | **35/35 PASS** |
| `t_efead8b4_chat_notice_unit.py` | chat 侧 5 条文案的 `meta.notice` 承载通道（桩 `run_auto` + 桩 LLM，不产生真实调用） | **17/17 PASS** |
| `t_efead8b4_unit_matrix.py`（进程内真实 DB/ES/embedding/LLM） | A 构成分类 / B 纯 embedding / C 纯 pageindex / D 混合库 / E 空构成 / F 降级 / G 合并规则 / H 文案逐字 / I 延迟与 LLM 增量 | **32/32 PASS** |
| `t_efead8b4_ac9_mcp.py` | MCP 9100 不变性（工具清单 + 不传 mode 调用 + 鉴权） | **6/6 PASS** |
| `tests/e2e_test.py` | 仓库既有 e2e（第 4 步显式 `index_type=embedding`，未改动） | **8/8 PASS** |

**AC 自测矩阵（逐条）**

| AC | 结论 | 证据（实测值） |
|---|---|---|
| AC1 默认上传+默认提问 | PASS | 新建 KB（不传 `index_type`，15s 建树 `pageindex_status=ok`）→ 默认 chat（不传 `retrieval_mode`）`sources=3`，答案含口令 `星火-7315`，无 error，`leg=pageindex`×3 |
| AC2 显式模式回归 | PASS | `retrieval_mode=pageindex` 有来源、无 error、**无 notice**（notice 只属 auto）；hybrid 路径由 `tests/e2e_test.py` 第 6/7 步回归通过 |
| AC3 纯 embedding 零变化 | PASS | `auto` 与 `mode=hybrid` 的 `(document_id, chunk_index, score)` 三元组逐条相同（`[('4c4f9041…', 0, 0.032787)]`），`leg=es`，无 `degraded`；进程内计数证明 **pageindex 腿 0 次调用** |
| AC4 混合库不漏检 | PASS | 夹具混合库 `{embedding_docs:1, pageindex_docs:1}`：`auto` items=4，`leg=pageindex`×3 + `leg=es`×1，两腿各≥1 条，降序 |
| AC5 红线回归 | PASS | 纯 embedding 库显式 `mode=pageindex` → `total=0`、`items=[]`，仍带既有 `message`（未回退 ES） |
| AC6 文案逐字 | PASS | 5 条逐字比对：空库/仅 embedding 0 命中（`filters.file_type=pdf` 置空两腿）/仅 pageindex 0 命中/混合两路 0 命中 走 HTTP；`pageindex 腿异常降级` 走进程内桩（真实触发需破坏 LLM） |
| AC7 空库 | PASS | search `message` 逐字；chat `meta.notice` 逐字且事件序列 `meta→token→done`，**无 error 事件** |
| AC8 接口契约 | PASS | 4 个 KB 的 `index-stats` 与 DB 聚合逐字段一致；KB 不存在 404；OpenAPI 两字段 `default='auto'`（pattern 含 auto） |
| AC9 MCP 不受影响 | PASS | 工具清单 `mode.default='hybrid'`、描述/枚举不含 `auto`；不传 mode 调用 `items=1` 且命中属本 KB；无 key → 401；`mcp_server.py` 未在本次 diff 中 |
| AC10/AC11 前端与线上 | **部分**（部署与产物已验证，浏览器级 DOM 断言留给测试侧） | dist 已重建换装、公网 200、本地/线上 12 个 js md5 一致、懒加载 chunk 含「智能（推荐）」；默认选中 `auto` 的**浏览器 DOM/网络断言**与"默认链路提问有来源"的公网端到端由云天明按 `05-temp/t_7f451c5f_ui_verify.py` 方式复核 |

### 5. 延迟与 LLM/token 增量实测（同一台机、DeepSeek `deepseek-flash`）

| 场景 | 实测 |
|---|---|
| 索引构成统计（新增 SQL） | 20 次 `kb_index_composition`：avg **1.33ms** / p95 **1.92ms** / max 2.27ms（P95 要求 <50ms） |
| 纯 embedding 库 `auto` vs `hybrid`（search） | 43ms vs 11ms（HTTP `took_ms`）；进程内 77ms vs 11ms —— 差值以 SQL(≈1.3ms)+连接/调度抖动为主，**无 LLM 调用** |
| 混合库单腿 | ES 腿 42–44ms（1 条）；pageindex 腿 **1877 / 3343ms**（LLM 波动，4 条） |
| 混合库 `auto`（两路串行） | **2187 / 5486 / 7922ms**（同 query 三次观测）→ 额外代价 = 1 次 pageindex LLM 调用（延迟即 pageindex 腿本身） |
| 纯 pageindex 库 `auto` | 5777ms（= 显式 pageindex 检索耗时） |
| token 增量 | 每次混合库 `auto` 多 **1 次** LLM 调用；pageindex 腿输入 prompt 实测 **644 字符**（中文粗估 ≈402 tokens，未含其 JSON 输出）。⚠️ `pageindex_engine.retrieve` 未回传 usage，**token 数只能按 prompt 字符数估算**，非精确账单值 |

### 6. 已知问题 / 未闭环项

1. **Q1（PD-001 §8，待褚岩向用户确认）**：`/search.mode`、`/chat.retrieval_mode` 的**接口层默认值**已按本卡默认方案由 `hybrid` 改为 `auto`；若用户要求接口默认值不变，退路是"接口默认仍 `hybrid`，仅前端默认传 `auto`"（前端改动不变，后端只保留 `auto` 取值与路由）——本次已按默认方案实现，**该点待确认**。
2. **AC6 的 chat 侧两条文案难以自然触发**：「仅 embedding 0 命中」「混合两路 0 命中」在 chat 上无法用 `filters` 置空（`ChatReq` 无 filters），且 ES kNN 无阈值（几乎总能返回近邻）→ 这两条在 chat 上的**真实触发路径依赖 ES 侧无 chunk 的异常态**。本次用 search 侧真实 HTTP 触发 + chat 侧桩验证承载通道；云天明若要端到端复现，需构造"composition 说有 embedding 文档、ES 里无该 KB chunk"的状态（如清空 ES 后不重建）。
3. **混合库 auto 的延迟由 pageindex 腿决定且波动大**（1.9s–7.9s 观测；同一 query 连续三次 max/min ≈3.6×），远超 `hybrid` 的 10–44ms。产品侧只要求"允许新增 1 次 LLM 调用"，但**用户可感知的等待变长**，建议后续评估：并行两腿、或 pageindex 腿单独超时/短超时降级（现状 `pageindex_retrieve_timeout` 60s）。
4. **merged 分数不可当阈值**：ES RRF 分（≈1/60）与 LLM relevance 量纲不同，归一化后 `1.0` 只是"该腿最高分"，不代表绝对相关性。已在 api.md + 代码注释 + 本节写明，**禁止**据此做阈值过滤。
5. **MCP 9100 仍不支持 pageindex**（既有缺口，本卡范围外）：MCP 工具枚举只有 hybrid/vector/keyword，`auto` 也未暴露给 MCP（会得到空结果）；已按 R9 保持"不改"，另开卡。
6. **本次未提交 `git` 变更文件**：见 §7 —— 同工作树内有其它并行卡的未提交改动（`DEPLOY.md`、`BUGFIX_BUG06_MCP_DEPLOY.md`、`03-testing/*`），本次只提交本卡文件，避免把别人的在建内容卷进提交。
7. **验证夹具**：新建 4 个 KB（`auto验收-纯PI/混合/纯EMB/空库-1791775813`，见 `05-temp/t_efead8b4_fixtures.json`）与若干 chat 会话/消息落库；**未清理**（红线：测试侧可能要用；空库 KB 需保留以复现 AC7）。如测试完成后要清，按 `fixtures.json` 里的 KB id 逐个删除即可。

### 7. commit 与并发说明

- 分支：`feat/default-pageindex`（沿用本卡产出所在的现有分支；未新开 `feat/retrieval-auto`，**原因**：`workspace_kind=dir` 的共享工作树里同时有其它卡的未提交改动，新开分支会把别人未完成的提交一起带过去）。
- commit：`<见下方 kanban 完成说明 / git log>`。仅包含本卡 12 个代码/文档文件 + 本报告段；`05-temp/` 证据按项目惯例**不入 git**。
- 并发：本卡执行期间另一张本人卡（MCP 常驻化）与测试卡的进程/文件同时存在；本卡重启 9012 与 9100 各一次，已按 DEPLOY §5.0 口径（检索链路改动 → 两处都重启），未触碰 nginx 配置与容器本体。

### 8. 一句话总结

新增 `auto`（智能，前端「智能（推荐）」）检索模式并作为 `/search.mode`、`/chat.retrieval_mode` 默认值：按 KB 实时索引构成主动路由（仅 embedding→ES 混合、仅 pageindex→树索引、两者都有→**两路都执行后合并**、都无→空+引导文案），显式 mode 与 `pageindex 0 命中不回退 ES` 红线零改动；混合库「默认上传 + 默认提问」由 0 来源变为带来源作答（AC1 sources=3 且答案含口令），纯 embedding 库与 `hybrid` 逐条一致且不产生任何 pageindex 调用，新增 SQL p95 1.92ms，混合库每次多 1 次 LLM 调用（prompt 644 字符）与 1.9–7.9s 墙钟；自测 35/35 + 17/17 + 32/32 + 6/6 + e2e 8/8 全绿，前端 dist 已重建换装（本地/线上 md5 一致），Q1（接口默认值是否获用户认可）待褚岩确认。

### 9. 补充：线上浏览器级验证（AC10/AC11 证据补强，2026-10-12 03:41 UTC）

在换装后的公网 `https://agent.carefold.ai/kb-management/` 上用真实浏览器（无密码：本地签 token 注入 `localStorage.kb_token`，脚本 `05-temp/t_efead8b4_ui_prep.py`）核验：

1. **问答页** `/kb/665c922d…/chat`（纯 pageindex 夹具 KB）：
   模式组渲染为 `[智能（推荐）, 混合, 向量, 关键词, PageIndex]`，**默认选中「智能（推荐）」**（`.el-radio-button.is-active`），
   模式组旁小字 `智能模式：按本知识库的索引构成自动选择检索方式` 存在。
2. **默认提问的真实请求体**（页面 fetch 抓取）：`{"question":"本知识库的验收口令是什么？","retrieval_mode":"auto"}`
   → **前端确实按默认传 `auto`**（不是 `hybrid`）。返回：3 条 sources（均为 `t_efead8b4_doc_pi_ac1.md`，`leg=pageindex`），
   答案含口令 `星火-7315`；**无 notice 提示条、无红色错误弹窗**。
3. **检索页** `/kb/665c922d…/search`：默认同为「智能（推荐）」；查询「验收口令是什么」→ 3 条结果 / 1649ms，
   `match_type=PageIndex` 且结果元信息中可见 `leg: pageindex`（本次新增字段在前端可见）。

> 结论：AC10 的"默认选中「智能（推荐）」+ 默认传 `auto`"与 AC11 的"线上默认链路提问有来源"在**换装后的线上产物**上成立。
> 该证据由开发侧提供，**AC10/AC11 的最终判定仍归测试侧**（建议按 `05-temp/t_7f451c5f_ui_verify.py` 方式独立复现一遍，并补测"手动切到其他模式后请求体为对应值"与"0 命中灰色提示条（非红色）"两个分支）。

---

## BUG-V4-01（P1）修复：pageindex 检索/问答间歇性 0 命中（t_9b05deec，分支 `feat/default-pageindex`，2026-10-12）

### 1. 复现（先复现，再改）

```bash
cd /home/harry.zhang/kb-management
# ① 检索链路的 LLM 侧根因探针（复刻 pageindex_engine.retrieve 的选节点调用，
#    捕获 finish_reason / usage / 原始 content；只读，不改数据）
backend/.venv/bin/python 05-temp/t_9b05deec_probe.py 22bcb345-8326-479c-958b-51daa2905715 12
# ② HTTP 级同参重复取样（同 KB 同 query 同参数 ×12，记录原始 total 序列）
RUNS=12 bash 05-temp/t_9b05deec_http_repro.sh
# ③ 问答侧（SSE，retrieval_mode=pageindex ×5，记录 sources 与 error 事件）
RUNS=5 bash 05-temp/t_9b05deec_chat_repro.sh
# ④ 修复后自测链（重启 + 上面三步 + 回归用例 AR-203/PI-02/AR-105）
bash 05-temp/t_9b05deec_selftest.sh
```

**修复前实测（探针 ①，12 次同一 prompt 调用，2026-10-12 04:18 UTC）**：

```
selected 非空: 4/12                      # 8/12 返回 {"selected": []}，finish_reason=stop、JSON 合法
content_len: [16,16,77,16,16,16,71,16,140,71,16,16]     # 16 = '{"selected": []}'
reasoning_len: [1070,1009,8313,229,1284,334,7237,1688,2219,8239,810,674]
wall_ms:      [2251,2217,13372,1428,2672,1233,12218,3163,8163,13284,2031,2915]
```

与测试侧 `03-testing/BUGS.md` BUG-V4-01 的 HTTP 原始取样一致（`total=2/0/0`、`sources=0/2/0`、
DIAG3 三组 12 次观测 5 次空）。**字面同一份 outline + 同一个问题**，输出在 `{"selected":[]}`
与 `{"selected":[{...}]}` 之间跳——`temperature=0.0` 也**不保证确定性**（推理型模型
`deepseek-flash`：judgment 抖动；实测空判定 run 的 reasoning 只有 130–422 tokens，
命中 run 是 1294–2373 tokens；`took_ms` 2–3s vs 3–20s 的差异同源）。

### 2. 根因（两条，都在检索侧 `pageindex_engine.retrieve()`）

1. **空判定被当作合法终态**：`RETRIEVE_SYSTEM` 明确写着"没有任何相关节点时返回空数组，不要硬凑"，
   而 outline 当时**只含标题 + 50 字摘要**（且摘要常被截在句中），问题问的细节（口令/编号）
   在正文里 → 模型频繁认定"目录里查不到 → 空数组"；`retrieve()` 对空数组**既不重试也无兜底**，
   直接返回 `[]`，且 `extra` 里既无 `message` 也无 `error`（Bugs.md 记录的"静默空结果"正是这条）。
2. **选中但不可解析被静默丢弃**：`doc_id`/`node_id` 必须在 `doc_index`/树里解析到，否则
   `for sel in selected:` 里 `continue` 丢弃；全部丢弃时 `results=[]` **同样静默返回 0**
   （本次修复过程中在 12 次 HTTP 取样里抓到 1 次，见 §4 修复前中间态）。

> 一句话共性：**"LLM 没给出可用节点" 没有被当成失败**，既没有重试、没有降级、也没有可区分的文案。

### 3. 修复（5 个代码/配置文件 + 2 个文档文件，`git diff --stat`）

```
backend/app/services/pageindex_engine.py | 319 +++++++++++++++++++++++++------
backend/app/core/config.py               |   3 +
backend/app/api/search.py                |   6 +
backend/app/services/rag_engine.py       |   7 +-
infra/.env.example                       |   3 +
02-development/DEPLOY.md                 |   1 +      # 重启口径表补 pageindex_engine 行
02-development/DEV_REPORT.md             |   本段
```

1. **提高选节点精度（outline 拼装）**：`_outline_lines()` 支持「标题|摘要|区间|**正文开头摘录**」
   （`OUTLINE_EXCERPT_CHARS=150`），`retrieve()` 侧受 `OUTLINE_BUDGET_CHARS=24000` 总预算约束，
   超限自动退回旧的「标题+摘要」精简模式（`extra.outline_mode` 可观测）。让模型能**看见**
   问题所问的细节出现在哪个节点。
2. **提示词按事实收紧**：`RETRIEVE_SYSTEM` 说明摘录是**截断**的开头（非全文），
   细节出现在摘录里 → 选它并给高分；细节未覆盖时按**主题**相关选中并给低分；
   只有"与所有节点主题明显无关"才返回空数组。新增 `RETRIEVE_RETRY_HINT`（仅重试时追加）。
3. **有限重试**：`PAGEINDEX_RETRIEVE_ATTEMPTS`（默认 3，`settings.pageindex_retrieve_attempts`）——
   超时/解析失败/**空判定**/**选中但不可解析** 都走同一重试路径（第 2 次起追加纠正提示）。
4. **确定性词面降级（兜底）**：`_lex_tokens`/`_lexical_rank` 对全部节点按「问题词元在**节点正文**中的
   覆盖率」打分；重试后仍无可用结果时——
   - 判为**词面相关**（`matched ≥ 2` 或 `coverage ≥ 0.5`）→ 按覆盖率降序**降级返回**这些节点，
     `score` 上限 0.30，`metadata.selected_by="lexical_fallback"`、`score_source="lexical_fallback"`、
     附 `lex_coverage`/`lex_matched`，`extra.fallback` 说明成因；**不再静默空结果**。
   - 判为**确实无关** → 维持 0 命中（保留 `pageindex 0 命中不回退 ES` 红线与 auto 的 F6 文案）。
5. **文案区分（OBS-V4-1）**：`extra.empty_reason` + `extra.message` 两个分支——
   `no_pageindex_docs`（KB 里没有 PageIndex 文档，原文案不变）与
   `no_node_selected`（"该知识库已有 N 篇 PageIndex 文档，但本次未选中任何相关节点…"）；
   `api/search.py` 透出 `empty_reason`/`fallback`，`rag_engine` 直接用 engine 给出的区分文案
   （原来两种成因混在一句「…请换一种问法或确认已上传 PageIndex 索引的文档」里）。
6. **顺手修 `_renumber()` 编号双点缺陷**：LLM 侧 `n1.1` 被重编号成 `n1..1`（`rel=nid[2:]` 残留前导点），
   outline 与 `location.node_id` 全带双点；检索按串精确匹配故此前不影响命中，但引用展示/外部引用契约脏。
   现 `n1.1`/`n1.1.2` 正确；**既有数据的旧编号不改**（`_find_node` 按树内存值匹配，兼容）。
7. **未改动**：`es_client`、`auto_retrieval` 的 F6 文案常量、显式 mode 的"0 命中不回退 ES"红线、
   建树链路（`build_tree_index`）。

### 4. 自测证据（全部真实运行，2026-10-12 UTC；脚本/日志在 `05-temp/`，不进 git）

**① 检索 `mode=pageindex` 同 KB 同 query ×12（`05-temp/t_9b05deec_selftest.log`，修复后最终版）**

```
run   total  took_ms   items 含 PI-TOKEN-7412
1..12   2     1472,4142,1515,2338,2973,2076,5671,1796,1680,3224,1916,2853    全为 2/2
==== 命中 12/12（0 命中 0 次）====
原始 total 序列: 2,2,2,2,2,2,2,2,2,2,2,2      # 修复前测试侧实测 2,0,0 / 0,2,0（1/3）
```
每个 run 的 2 条结果都含口令（`metadata.node_id=n1..2`、`selected_by=llm`、`score 0.93–0.95`），
即测试侧 `case_PI-09` 的 S1/S2/S3 三项（code=0、`total≥1`、含口令）12/12 全满足。

**② 问答 `/chat`（`retrieval_mode=pageindex`）×5**

```
run  sources  error_events
1..5    2        0            （sources>=1: 5/5；无 event:error）
run1 答案：根据参考片段，追溯本次巡检批次时应使用口令 **PI-TOKEN-7412** 定位日志 [1][2]。
```
修复前同用例为 `sources=0/2/0` 且 0 来源时发 `event:error`（误导文案）。

**③ 进程内打桩（确定性路径，与 LLM 抖动解耦；`05-temp/t_9b05deec_unit.py` + `_result.json`）**

| 打桩 | 相关查询（本 KB） | 无关查询（kb_pi） |
|---|---|---|
| LLM 恒返回 `{"selected": []}` | `total=3`，`selected_by=lexical_fallback`，`lex_coverage=0.632`/`matched=12`，`score≤0.30`，含口令 | `total=0` + `empty_reason=no_node_selected`（文案见 §3.5） |
| LLM 恒返回不可解析 `doc_id/node_id` | `total=3`（同上降级），`extra.unresolved_selected` 记录原因 | `total=0` + 同上文案 + `llm_error` 说明 |

→ 兜底与 LLM 输出**无关**，因此 12/12 是确定性结论（不是"这次运气好"）。

**④ 回归（改动面内的既有用例，全部 PASS）**

- `case_AR-203`（auto、无关 query、F6 文案③）：`VERDICT=PASS`，`search total=0`、
  chat `meta.notice` 逐字一致、**无 error 事件** ⇒ 词面裁定没有污染"真正 0 命中"的语义。
- `case_PI-02`（显式 pageindex 命中）：主查询 `total=1`、`score=0.98`、节点即含口令的 `n1..2`；
  多问法 5/5 命中（含口令条目 1–2 条）。
- `case_AR-105`（显式 pageindex 0 命中不回退 ES 红线）：`VERDICT=PASS`，`total=0`、`es_leg_count=0`，
  「没有 pageindex 文档」文案与 `empty_reason=no_pageindex_docs` 不变。

### 5. 部署（重启加载，无新增组件/端口）

```bash
bash 05-temp/t_9b05deec_restart.sh     # systemctl --user restart kb-backend-9012 kb-mcp-9100
```
- 9012（检索/问答 API）与 9100（MCP，经 `rag_engine` 复用同一 `pageindex_engine`）**两处都已重启**
  （uvicorn 无 `--reload`；沿用 DEPLOY §5.0 口径，并为 `pageindex_engine.py` 补了该表一行）。
- 本次**未新增容器/端口/volume**，`SERVER_REGISTRY.md` 无变化（沿用 kb-backend-9012:9012 /
  kb-mcp-9100:9100 两个既有 systemd user 单元）。
- 新配置项 `PAGEINDEX_RETRIEVE_ATTEMPTS`（默认 3）已写入 `infra/.env.example`；
  线上 `infra/.env` 未覆盖该项 → 走代码默认值 3。

### 6. 已知问题 / 风险（如实列出）

1. **残余漏检面**：词面裁定只看字面（CJK 2-gram + 拉丁词）。若问题与文档**同义但无字面重叠**
   （例如问"机密串"而文档写"口令"），空判定仍会被判为"确实无关"→ 维持 0 命中。
   彻底解决需要向量/语义通道，而 embedding 模型当前不可用（本卡边界）→ 记为后续项。
2. **词面降级的分值下限**：降级命中 `score ≤ 0.30` 只是"低置信"标记（`selected_by`/`score_source`
   可区分），**不可当相关度阈值用**；上层若要区分"LLM 命中"与"降级命中"请读 metadata。
3. **延迟**：空判定重试最坏 3 次 LLM 调用（每次 `pageindex_retrieve_timeout=60s` 上限）；
   实测修复后 12 次检索 1.4–5.7s（带摘录后模型更快给出高分判定），未见明显变慢，
   但**极端抖动下**单次检索上限由 60s 变为 180s —— 若上层有更短超时要求需调
   `PAGEINDEX_RETRIEVE_ATTEMPTS=1`（退化为"不重试、只降级"）。
4. **文案变更**：显式 pageindex 的 0 命中文案由旧句改为区分后的新句（OBS-V4-1 的建议项）。
   测试侧若有断言旧字面（`PI-10` 的 evidence 记录过）需按新文案更新；auto 侧 F6 文案**未改**。
5. **既有数据的双点编号**：`n1..1` 只在**新建成**的树里被修正；老文档（本 KB 2 篇）仍是旧编号，
   需要干净编号时对文档执行 `pageindex/rebuild`（本次未动任何既有文档）。
6. **MCP 侧仍不支持 pageindex**（BUG-V4-02，另卡 `t_21918fb2`）：本修复让它以后能拿到非空结果，
   但 MCP 工具契约（`search_knowledge` 的 mode 分支）仍需按那张卡补。

### 7. 一句话总结根因

> 推理型模型（`deepseek-flash`）对**同一** prompt 非确定性地返回"空数组/不可解析节点"
> （实测空判定 8/12），而 `pageindex_engine.retrieve()` 把"LLM 没给出可用节点"当成合法终态
> ——不重试、不降级、无区分文案，于是同一问题有时 2 条有时 0 条；
> 现在改为"空判定先做词面相关性裁定 → 有限重试 → 仍不可用则按词面覆盖率**确定性降级返回**，
> 仅当问题与所有节点主题确实无关时才 0 命中"，并补上"有没有 PageIndex 文档"的文案区分。

