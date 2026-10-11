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
本段将 A1-A5 全部未提交改动 + 自测脚本统一 commit 到 `feat/kb-citations` 并 push（排除 `.env`/`node_modules`/`tsconfig.tsbuildinfo`/`05-temp`/`deploy/dist`，`.env` 仅进本地）。commit hash 见 DEV_REPORT 末尾或 `git log`。
