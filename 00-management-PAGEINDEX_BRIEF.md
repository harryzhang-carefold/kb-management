# kb-management 新增 PageIndex 检索选项 — 需求简报

**来源**：用户要求，2026-10-10
**参考**：https://github.com/VectifyAI/PageIndex

## 背景

kb-management 当前检索方式：embedding（gte-qwen2, 34.64.61.208:4000）+ Elasticsearch 混合/向量/关键词检索（`es_client.hybrid_search`）。注意：代码里向量检索用的是 **ES**，不是 milvus（用户描述有误，按实际代码来）。

本次需求：新增 **pageindex** 检索选项（与现有 hybrid/vector/keyword 并列），采用 PageIndex 的思路——**无向量、基于层级树索引 + LLM 推理检索**。

## PageIndex 核心机制（两步骤）

1. **Index（建索引）**：对每个文档用 LLM 生成层级树结构索引（类似"目录"），每节点含标题、摘要、页码/段落范围。
2. **Retrieve（推理检索）**：LLM 在树上做 agent 式搜索——逐层判断哪个节点最相关，选中后读取该节点对应的原文段落作为引用。

特点：无 embedding、无 chunk 切割、检索可溯源（到具体页/段）、适合长文档。

## 环境事实（已勘察）

| 组件 | 地址 | 备注 |
|---|---|---|
| PostgreSQL | 127.0.0.1:9011, kb_admin/kb_password_2026, 库 kb_management | 存 Document / Chunk / KnowledgeBase |
| Elasticsearch | 127.0.0.1:9200, 索引 kb_chunks | 现有向量/关键词检索 |
| MinIO | 127.0.0.1:9002 | 存原始文档 |
| Redis/Celery | 127.0.0.1:6179, 密码 Leaflong2025! | 异步任务 |
| LLM（PageIndex 用） | `http://34.121.9.233:4000/v1`, model=`vllm-qwen3.8-27b` | 用户指定；OpenAI 兼容 API |
| Embedding（现有） | `http://34.64.61.208:4000/v1`, model=gte-qwen2 | 不变 |

**注意**：`infra/.env` 当前不存在（只有 `.env.example`），开发需创建 `.env`（从 `.env.example` 复制并填入值）。`.env` 里 LLM key 为空——开发时向用户确认或留空（vllm 端点可能无鉴权）。

## 交付范围

### 1. 后端 — PageIndex 引擎

新文件 `backend/app/services/pageindex_engine.py`：
- `build_tree_index(document: Document) -> dict`：用 LLM（vllm-qwen3.8-27b）从 `document.full_text` 生成层级树索引。树结构 JSON 存入 `document.meta` 的 `pageindex_tree` 字段（或新表，开发自行决定，优先复用 `meta` JSONB）。
- `retrieve(kb_id, question, top_n) -> list[dict]`：用 LLM 推理在树上选择相关节点，返回引用段落列表（格式与现有 `sources` 兼容：`{chunk_id, document_id, filename, chunk_index, content, score}`，PageIndex 的 score 可用 1.0 或 LLM 给出的相关性评分）。

### 2. 后端 — API 层

- `SearchReq.mode` 增加 `pageindex`（pattern 改 `^(hybrid|vector|keyword|pageindex)$`）
- `ChatReq` 增加 `retrieval_mode: str = "hybrid"`（可选值：hybrid / vector / keyword / pageindex）
- `rag_engine.stream_answer()` 增加 `retrieval_mode` 参数：mode=pageindex 时走 `pageindex_engine.retrieve()`，其他走现有 `es_client.hybrid_search()`
- `search.py` 路由：mode=pageindex 时跳过 embedding 步骤，直接走 pageindex_engine

### 3. 后端 — 摄取流程

- `chunk_index_task` 完成后（或并行），如果 KB 开启了 pageindex（`kb.settings.get("enable_pageindex", False)`），调用 `pageindex_engine.build_tree_index(doc)` 建索引
- KB 创建/更新 API 支持 `settings.enable_pageindex` 开关
- 对已有文档提供 `POST /knowledge-bases/{kb_id}/documents/{doc_id}/pageindex/rebuild` 手动触发建索引

### 4. 前端

- `KbChatView.vue`：增加检索模式选择器（el-radio-group：混合/向量/关键词/PageIndex），传给 ChatReq.retrieval_mode
- `KbSearchView.vue`：增加 mode 选择器（同上），传给 SearchReq.mode
- `KbDetailView.vue` 或 KB 设置：增加"启用 PageIndex 索引"开关
- 前端 `api/index.ts`：对应请求参数增加

### 5. 文档

- `docs/architecture.md`：新增 PageIndex 引擎章节（原理、流程图、与向量检索对比）
- `docs/api.md`：新增 pageindex 相关 API 文档
- `backend/requirements.txt`：如需要 `pageindex` SDK（`pip install pageindex`）则加入；如果不直接用 SDK 而是自实现（基于 LLM 生成树 + 推理），则不需要

## 🔄 需求变更（2026-10-10 用户确认，优先级最高）

**索引方式改为"上传时按文档二选一"，废弃 KB 级开关方案：**

- 上传文档时选择该文档的索引方式：**embedding**（现有 chunk+向量）或 **pageindex**（树索引），**互斥**——一个文档只建其中一种索引
- 上传入口增加方式选择（radio，默认 embedding 保持现有行为）
- 文档记录自己的索引方式（如 `document.meta["index_type"] = "embedding" | "pageindex"`）
- 文档级"重建索引"按该文档的 index_type 执行
- **检索/问答侧不变**：mode / retrieval_mode 仍可选 pageindex 等；对只有 embedding 索引的文档做 pageindex 检索时返回空/提示（不静默回退）
- 原 KB 级 `enable_pageindex` 开关方案作废

## 约束

- **PageIndex 的 LLM 用 `vllm-qwen3.8-27b`**（34.121.9.233:4000），不用其他模型
- **不改动现有 embedding/ES 检索路径**——pageindex 是新增选项，默认行为不变
- **PageIndex 树索引构建是 LLM 密集型操作**（一次调用可能 30-120s），必须走 Celery 异步任务，不能阻塞 API
- 密钥只进 `.env`，不进 git
- 后端端口 9012（`scripts/start_backend.sh` 固定），前端 dev 端口看 `frontend/vite.config.ts`
- 如果 vllm 端点需要 API key 而 .env 为空，开发时先 `curl -s http://34.121.9.233:4000/v1/models` 验证是否需要鉴权

## 验收标准

1. 创建 KB 并开启 `enable_pageindex`，上传一个 PDF/文档，等待异步索引完成
2. `POST /knowledge-bases/{kb_id}/search` 带 `mode=pageindex` 返回相关段落（含 document_id、content、score）
3. `POST /knowledge-bases/{kb_id}/chat` 带 `retrieval_mode=pageindex` 正常流式回答，引用来源标注正确
4. 现有 `mode=hybrid` / `mode=vector` / `mode=keyword` 路径不受影响（回归）
5. 前端选择 PageIndex 模式后检索/问答正常

## 分工建议

- 分析（史强）：PageIndex 树结构 schema 设计、LLM prompt 设计、与现有 chunk 数据模型映射
- 开发（章北海）：实现 + 部署验证
- 测试（云天明）：按验收标准独立验证

## 交付分支（用户要求）

开发完成后：`git checkout -b feat/pageindex` → 提交全部改动（`.env` 等密钥文件严禁入库，确认 .gitignore 覆盖）→ `git push origin feat/pageindex`，并在 DEV_REPORT 记录分支名与 commit hash。测试验收在 `feat/pageindex` 分支上进行。

## 红线

- 不改动现有 ES/向量检索路径
- 密钥只进 .env
- 不改 carefold-agent / carefold-pageindex / nginx-test 等外部容器
