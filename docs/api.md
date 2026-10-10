# 知识库管理系统 — API 契约

**版本**: v1.0
**Base URL**: `/api/v1`
**认证**: `Authorization: Bearer <access_token>`（除 login/register/refresh 外全部需要）
**响应包裹**: 所有非流式接口返回统一结构

```json
{
  "code": 0,            // 0=成功, 非0=错误码
  "message": "ok",
  "data": { ... }       // 业务数据
}
```

**分页结构** (`data` 内):
```json
{
  "items": [ ... ],
  "total": 100,
  "page": 1,
  "page_size": 20
}
```

**统一错误码**:
| code | HTTP | 含义 |
|---|---|---|
| 0 | 200 | 成功 |
| 40001 | 400 | 参数错误 |
| 40101 | 401 | 未认证 / token 失效 |
| 40301 | 403 | 无权限 |
| 40401 | 404 | 资源不存在 |
| 40901 | 409 | 资源冲突（重名等） |
| 41301 | 413 | 文件过大 |
| 50001 | 500 | 服务器内部错误 |
| 50301 | 503 | 依赖服务不可用（ES/MinIO/LLM/Embedding） |

---

## 1. 认证 `/auth`

### POST `/auth/login`
登录，返回 token。
**Request**
```json
{ "username": "admin", "password": "Admin@123" }
```
**Response 200**
```json
{
  "code": 0,
  "data": {
    "access_token": "eyJ...",
    "refresh_token": "eyJ...",
    "token_type": "bearer",
    "user": { "id": "uuid", "username": "admin", "email": "admin@kb.local", "role": "admin", "display_name": "系统管理员" }
  }
}
```

### POST `/auth/register`
注册（仅创建普通用户；admin 由 seed 创建）。
**Request**
```json
{ "username": "alice", "email": "a@x.com", "password": "Str0ng!Pass", "display_name": "Alice" }
```
**Response 200**: 同 login 的 `data.user`。
**Error**: 40901 用户名/邮箱已存在。

### POST `/auth/refresh`
刷新 access_token。
**Request**: `{ "refresh_token": "eyJ..." }`
**Response 200**: `{ "access_token": "...", "token_type": "bearer" }`

### GET `/auth/me`
当前用户信息。**Response 200**: `user` 对象。

### PUT `/auth/password`
修改当前用户密码。
**Request**: `{ "old_password": "...", "new_password": "..." }`
**Response 200**: `{}`

---

## 2. 用户管理 `/users` (admin only)

### GET `/users`
列出用户。**Query**: `page`, `page_size`, `role?`, `keyword?`
**Response 200**: 分页 `items: User[]`。

### POST `/users`
创建用户。**Request**: `{ username, email, password, role, display_name? }`
**Response 200**: `User`。

### GET `/users/{id}`
用户详情。

### PUT `/users/{id}`
更新用户。**Request**: `{ email?, role?, display_name?, is_active?, password? }`

### DELETE `/users/{id}`
软停用（`is_active=false`）。**Response 200**: `{}`

---

## 3. 知识库 `/knowledge-bases`

### GET `/knowledge-bases`
列出当前用户可访问的知识库（admin 全部）。
**Query**: `page`, `page_size`, `status?`, `keyword?`
**Response 200**: 分页 `items: KnowledgeBase[]`。

### POST `/knowledge-bases`
创建知识库。创建者自动成为 `owner`。
**Request**
```json
{
  "name": "产品文档库",
  "description": "公司产品技术文档",
  "chunk_size": 500,
  "chunk_overlap": 50,
  "embedding_dim": 3584,
  "embedding_model": "gte-qwen2",
  "member_user_ids": ["uuid", "uuid"],
  "member_roles": { "uuid": "editor", "uuid": "viewer" }
}
```
**Response 200**: `KnowledgeBase`。

### GET `/knowledge-bases/{id}`
知识库详情（含成员列表）。**Response 200**: `KnowledgeBaseDetail`。

### PUT `/knowledge-bases/{id}`
更新知识库（owner 或 admin）。
**Request**: `{ name?, description?, chunk_size?, chunk_overlap?, status? }`

### DELETE `/knowledge-bases/{id}`
删除（owner/admin，级联清理 ES + MinIO + PG）。**Response 200**: `{}`

### GET `/knowledge-bases/{id}/members`
成员列表。**Response 200**: `items: KbMember[]`。

### POST `/knowledge-bases/{id}/members`
添加成员。**Request**: `{ "user_id": "uuid", "role": "editor" }`

### PUT `/knowledge-bases/{id}/members/{user_id}`
更新成员角色。

### DELETE `/knowledge-bases/{id}/members/{user_id}`
移除成员（不能移除 owner）。

---

## 4. 文档 `/knowledge-bases/{kb_id}/documents`

### GET `.../documents`
列出文档。**Query**: `page`, `page_size`, `status?`, `keyword?`
**Response 200**: 分页 `items: Document[]`。

### POST `.../documents`
上传文档（multipart/form-data）。
**Form**: `file`（必填）、`index_type`（可选，`embedding`|`pageindex`，默认 `embedding`，v2 按文档二选一索引方式，互斥）
**支持格式**: `.pdf .docx .pptx .xlsx .txt .md .html .htm .jpg .jpeg .png .bmp .webp .tiff`
（`.xls` 不支持，返回 40001 提示另存为 `.xlsx`）
**大小上限（按类型）**: pdf 15MB（MinerU CPU 解析时长保护）/ docx·pptx·xlsx·图片 20MB / txt·md·html 10MB
- `index_type=embedding`（默认）：解析 → 分块 → 向量索引（现有行为）。
- `index_type=pageindex`：解析 → 异步 LLM 建树（跳过分块/向量），完成后 `status=indexed`。
**Response 200**:
```json
{ "code": 0, "data": { "document_id": "uuid", "status": "uploaded", "task_id": "uuid" } }
```
**Error**: 41301 文件过大（超按类型上限），40001 不支持的文件类型，422 `index_type` 取值非法。

### GET `.../documents/{id}`
文档详情（含最新 task 状态）。**Response 200**: `DocumentDetail`。

### GET `.../documents/{id}/download`
下载原始文件（重定向到 MinIO 预签名 URL 或代理流）。**Response**: 二进制流 + `Content-Disposition`。

### GET `.../documents/{id}/chunks`
查看分块列表。**Query**: `page`, `page_size`
**Response 200**: 分页 `items: Chunk[]`。（pageindex 文档无 chunk）

### POST `.../documents/{id}/reparse`
重新解析（重置状态，重新入队；pageindex 文档会清旧树并按 index_type 重建）。**Response 200**: `{ "task_id": "uuid" }`。

### POST `.../documents/{id}/reindex`
文档级重建索引（v2）：按该文档 `index_type` 执行——`pageindex` → 重建树索引；`embedding`（默认/旧文档）→ 重建分块+向量索引。**Response 200**: `{ "task_id": "uuid", "index_type": "embedding"|"pageindex" }`。

### POST `.../documents/{id}/pageindex/rebuild`
手动触发 PageIndex 树索引重建（异步）。仅对 `index_type=pageindex` 的文档有效，否则 400 提示改用「重建索引」。**Response 200**: `{ "task_id": "uuid" }`。

### DELETE `.../documents/{id}`
删除文档（级联清理 chunk + ES + MinIO）。**Response 200**: `{}`。

---

## 5. 检索 `/knowledge-bases/{kb_id}/search`

### POST `.../search`
混合检索。**Request**
```json
{
  "query": "如何配置 RAG 的 top_k 参数",
  "mode": "hybrid",      // hybrid | vector | keyword | pageindex
  "top_k": 10,
  "filters": { "file_type": "md" }   // 可选
}
```
- `mode=pageindex`：跳过 embedding，走 PageIndex 树索引 LLM 推理检索（仅对 `index_type=pageindex` 且已建树的文档生效）；
  KB 下无此类文档时返回 `items=[]` + `message` 提示（不静默回退 ES）。
**Response 200**
```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "chunk_id": "uuid",
        "document_id": "uuid",
        "filename": "guide.md",
        "chunk_index": 3,
        "content": "...",
        "score": 0.87,
        "match_type": "hybrid",   // vector | keyword | hybrid | pageindex
        "metadata": { "page": 5 }
      }
    ],
    "total": 25,
    "took_ms": 42,
    "message": "（仅 mode=pageindex 且无 pageindex 索引文档时返回提示）"
  }
}
```

---

## 6. RAG 问答 `/knowledge-bases/{kb_id}/chat`

### POST `.../chat`
流式问答（**SSE**，`Content-Type: text/event-stream`）。
**Request**
```json
{
  "question": "部署时 ES 内存应该怎么配？",
  "conversation_id": "uuid",   // 可选；不传则新建会话
  "history": [                 // 可选；不传则用 conversation_id 的历史
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ],
  "top_n": 5,
  "system_prompt": "你是一个知识库助手",   // 可选
  "retrieval_mode": "hybrid"              // 可选：hybrid | vector | keyword | pageindex（默认 hybrid）
}
```
- `retrieval_mode=pageindex`：走 PageIndex 树索引 LLM 推理检索（跳过 embedding/ES）；
  KB 下无 pageindex 索引文档时返回 `error` 事件提示（不静默回退、不空答）。
  其他取值走现有 ES 混合检索路径，行为不变。

**SSE 事件流**（每个 `data:` 是一行 JSON，`event` 标注类型）:
```
event: meta
data: {"conversation_id":"uuid","message_id":"uuid"}

event: token
data: {"token":"建议"}

event: token
data: {"token":"将"}
...
event: sources
data: {"sources":[{"chunk_id":"uuid","document_id":"uuid","filename":"ops.md","chunk_index":1,"score":0.91}]}

event: done
data: {"message_id":"uuid","token_count":256,"finish_reason":"stop"}
```
前端用 `EventSource` 或 `fetch` + `ReadableStream` 解析。

### GET `.../conversations`
会话列表。**Query**: `page`, `page_size`
**Response 200**: 分页 `items: Conversation[]`。

### GET `.../conversations/{id}`
会话详情 + 消息列表。
**Response 200**: `{ conversation: {...}, messages: Message[] }`。

### DELETE `.../conversations/{id}`
删除会话。**Response 200**: `{}`。

---

## 7. 监控 `/system` (admin only)

### GET `/system/health`
系统健康（**无需 admin，但可放在 /health 供 LB 用**）。
**Response 200**
```json
{
  "code": 0,
  "data": {
    "status": "ok",
    "services": {
      "postgresql": "ok",
      "elasticsearch": "ok",
      "minio": "ok",
      "redis": "ok",
      "llm": "ok",
      "embedding": "unreachable",
      "mineru": "ok"
    },
    "version": "1.0.0"
  }
}
```

### GET `/system/parse-engine`
MinerU 解析服务健康检查（admin）。**Response 200**
```json
{
  "code": 0,
  "data": {
    "status": "ok",              // ok | unreachable
    "url": "http://127.0.0.1:9030",
    "backend": "pipeline",
    "latency_ms": 12
  }
}
```

### GET `/system/monitor`
监控数据（admin）。
**Response 200**
```json
{
  "code": 0,
  "data": {
    "document_stats": { "total": 120, "indexed": 100, "failed": 5, "processing": 15 },
    "chunk_count": 5400,
    "es_index": { "name": "kb_chunks", "docs": 5400, "size_bytes": 104857600 },
    "minio": { "bucket": "kb-docs", "objects": 120, "size_bytes": 524288000 },
    "celery": { "queue": "kb", "active": 2, "queued": 3 },
    "kb_count": 8,
    "user_count": 12
  }
}
```

---

## 8. 数据模型 (Pydantic / JSON 形态)

### User
```json
{
  "id": "uuid", "username": "admin", "email": "admin@kb.local",
  "role": "admin", "display_name": "系统管理员", "is_active": true,
  "created_at": "2026-09-14T10:00:00Z", "updated_at": "..."
}
```

### KnowledgeBase
```json
{
  "id": "uuid", "owner_id": "uuid", "name": "产品文档库",
  "description": "...", "status": "active",
  "chunk_size": 500, "chunk_overlap": 50,
  "embedding_dim": 3584, "embedding_model": "gte-qwen2",
  "settings": {}, "document_count": 12, "chunk_count": 540,
  "created_at": "...", "updated_at": "..."
}
```

### Document
```json
{
  "id": "uuid", "kb_id": "uuid", "uploaded_by": "uuid",
  "filename": "guide.pdf", "file_type": "pdf", "file_size": 1048576,
  "minio_key": "kb/{kb_id}/doc/{id}.pdf", "status": "indexed",
  "chunk_count": 42, "error_message": null, "version": 1,
  "meta": { "parse_engine": "mineru-pipeline", "page_count": 12, "source_type": "pdf" },
  "uploaded_at": "...", "indexed_at": "...",
  "created_at": "...", "updated_at": "..."
}
```
**file_type 枚举**: `pdf | docx | pptx | xlsx | txt | md | html | jpg | png | bmp | webp | tiff`
（2026-09-21 扩展；`meta` 为新增 JSONB 字段，存解析元数据，详见 docs/parsing-strategy.md）

### DocumentDetail（含 task）
```json
{
  "document": { /* Document */ },
  "task": {
    "id": "uuid", "task_type": "chunk_index", "status": "success",
    "celery_task_id": "...", "error_message": null,
    "started_at": "...", "finished_at": "..."
  }
}
```

### Chunk
```json
{
  "id": "uuid", "document_id": "uuid", "kb_id": "uuid",
  "chunk_index": 0, "content": "...", "token_count": 120,
  "metadata": {}, "created_at": "..."
}
```

### ProcessTask
```json
{
  "id": "uuid", "document_id": "uuid", "task_type": "parse",
  "status": "running", "celery_task_id": "abc-123",
  "result": null, "error_message": null, "retry_count": 0,
  "started_at": "...", "finished_at": null, "created_at": "..."
}
```

### Conversation
```json
{
  "id": "uuid", "kb_id": "uuid", "user_id": "uuid",
  "title": "新对话", "system_prompt": null, "message_count": 8,
  "created_at": "...", "updated_at": "..."
}
```

### Message
```json
{
  "id": "uuid", "conversation_id": "uuid", "role": "assistant",
  "content": "...", "sources": [{ "chunk_id": "uuid", "document_id": "uuid", "filename": "ops.md", "chunk_index": 1, "score": 0.91 }],
  "token_count": 256, "created_at": "..."
}
```

### KbMember
```json
{ "id": "uuid", "kb_id": "uuid", "user_id": "uuid", "role": "editor", "created_at": "..." }
```
