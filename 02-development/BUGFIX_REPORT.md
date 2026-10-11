# BUGFIX_REPORT — 同库顺序上传两份文档第一份状态失败

**任务**：t_670a7d8a
**开发**：章北海  2026-10-11
**分支**：`feat/kb-citations`（基于 feat/pageindex）

---

## 一句话根因

**Embedding 端点 `34.64.61.208:4000`（gte-qwen2）已下线（connection refused），所有 `index_type=embedding` 文档在「embedding」阶段必然失败；同库顺序上传两份文档（一份 embedding + 一份 pageindex）时，embedding 那份变成 failed、pageindex 那份成功——用户看到的「第一份失败」正是那份 embedding 文档。**

---

## 1. 根因定位（实测证据）

### 1.1 复现

新注册账号 → 新建 KB → 同库连续上传 2 份小 txt（均 `index_type=embedding`）：

| 文档 | 状态流转 | 终态 |
|---|---|---|
| a_first.txt | uploaded → parsing → parsed → embedding → **failed** | `Connection error.` |
| b_second.txt | uploaded → parsing → parsed → embedding → **failed** | `Connection error.` |

worker 日志（`/tmp/kb_worker.log`）：
```
[chunk_index] start doc=...
[chunk_index] embedding retry 1: Connection error.
[chunk_index] embedding retry 2: Connection error.
[chunk_index] failed doc=...: Connection error.
```

### 1.2 端点实测

- `34.64.61.208:4000`（.env 配的 embedding 端点）→ **TCP ConnectionRefused**（`/v1/models`、`/v1/embeddings` 全部连接被拒）。
- `34.121.9.233:4000`（LLM vLLM）→ 可达，但只服务 `vllm-qwen3.8-27b`，`/v1/embeddings` 返回 404（无 embedding 模型）。
- `34.85.104.227:4000`（Hermes VM）→ 可达，同样只有 LLM，无 embedding。
- 本机无 GPU、无 torch、无本地 embedding 服务。

**结论：embedding 能力整体不可用**（原外部端点下线，其它可达端点均无 embedding 模型）。

### 1.3 为什么表现为「第一份失败」

- 同库顺序上传两份文档时，两份的 `index_type` 可能不同（前端 radio 默认 embedding，用户可切 pageindex）。
- `index_type=embedding` → 走 chunk+向量路径 → 端点不可达 → **failed**。
- `index_type=pageindex` → 跳过分块/向量，直接 LLM 建树（用 LLM 端点，可达）→ **indexed**。
- 所以「第一份（embedding）失败、第二份（pageindex）成功」是该端点不可用下的**确定性结果**，不是并发/竞态/ES-Milvus-MinIO 冲突。

DB 佐证（GINA KB，用户原始场景）：
```
03:35:37  我要创建一个项目开发团队.md  failed    embedding
03:36:57  DATABASE_DESIGN.md           indexed   pageindex
```
全库 14 个 failed 文档全部是 `index_type=embedding` + `Connection error.`；11 个 indexed 全部是 `index_type=pageindex`。

### 1.4 附带发现的配置缺陷（加重根因）

`.env` 写的是 `EMBEDDING_API_BASE`，但代码 `pydantic` 字段 `embedding_base_url` 实际读取的环境变量名是 **`EMBEDDING_BASE_URL`**（旧名不被读取）。因此端点配置长期无效、恒用代码默认值 `34.64.61.208:4000`——该端点下线后 embedding 全挂，且 `.env` 改动也无法生效。

---

## 2. 修复方案（最小、可运行）

**部署本地 OpenAI 兼容 Embedding 服务（CPU），替代已下线的 `34.64.61.208:4000`。**

1. **新增本地 embedding 服务**（`02-development/deploy/embedding/`）：
   - `app.py`：FastAPI，OpenAI 兼容 `/v1/embeddings`、`/v1/models`、`/health`，sentence-transformers CPU 推理。
   - 模型：`paraphrase-multilingual-MiniLM-L12-v2`（多语言含中文，**384 维**，~118M 参数，CPU 友好）。
   - `Dockerfile`（python:3.11-slim + CPU torch + 预烤模型）+ `requirements.txt`。
   - 容器 `kb-embed`（host 网络，`127.0.0.1:8100`，`--memory 4g`，`--restart unless-stopped`）。
2. **配置修正**：
   - `.env` 增 `EMBEDDING_BASE_URL=http://127.0.0.1:8100/v1`（真正被代码读取的变量名）；`.env.example` 同步并注明旧名失效。
   - 密钥/配置只进 `.env`，不进 git（红线守住）。
3. **代码健壮性（让端点切换/维度变化不再破坏）**：
   - `ai_client.EmbeddingClient.dim()`：实测模型向量维度并缓存（替代写死 3584）。
   - `es_client.ensure_index()`：索引维度与请求不符时，**为空→删除重建**，**非空→抛错拒改**（不静默丢数据）。
   - `workers/tasks.py` chunk_index：`ensure_index` 用实测维度 `real_dim`。
   - `main.py` lifespan：启动时按实测维度确保 ES 索引。

> ES 索引当前为空（0 条 chunk），维度 3584→384 无存量兼容问题。

---

## 3. 自测证据（修复后，全部 PASS）

**同库连续 3 份（含 embedding+pageindex 混合）——验收核心：**

| 文档 | index_type | 终态 | chunks / 树 |
|---|---|---|---|
| r1_first.txt | embedding | **indexed** | 3 chunks |
| r2_second.md | embedding | **indexed** | 4 chunks |
| r3_third.md | pageindex | **indexed** | 树 ok（10 节点） |

- **第一份（embedding）不再失败** ✅（修复前必 failed）
- 混合 index_type 全成功 ✅
- `GET /api/v1/health` → `embedding=ok`（修复前 `unreachable`）
- ES 索引维度自动重建为 384
- 检索回归：`hybrid`/`keyword`/`vector` 均 HTTP 200，items 正常返回（7/3/7）
- 单文档上传正常 ✅

> 说明：pageindex 建树走 LLM（27b），单文档约 1–6 分钟（小文档 ~5–77s，视 LLM 输出），非本次 bug 范围。

---

## 4. 部署（已起、已验证可运行）

- **embedding 容器**：`docker run -d --name kb-embed --network host --memory 4g --restart unless-stopped kb-embed-local:latest`
  - `GET http://127.0.0.1:8100/health` → `{"status":"ok","dim":384}`
  - `POST /v1/embeddings` → 200，dim=384
- **后端 + Celery**：重启 `uvicorn :9012` + `celery -Q kb`（加载新配置）。
  - `GET /api/v1/health` → embedding=ok，其余 ok（mineru 本机未起，仅影响 pdf/docx，不影响 txt/md，与本 bug 无关）。

---

## 5. 已知问题 / 风险

1. **本地 embedding 维度 384 ≠ 原 gte-qwen2 3584**：当前 ES 索引为空，无存量兼容问题；若日后恢复原 gte-qwen2 端点（3584 维），需清一次空索引（`ensure_index` 已对「空索引维度不符→重建」做了自动处理，非空则拒改并告警）。
2. **MinerU（9030）未启动**：仅影响 pdf/docx/xlsx/图片解析；txt/md 本地解析不受影响。本 bug 复现/回归均用 txt/md。
3. **本地 CPU embedding 吞吐有限**：批量每批 64，CPU 推理较慢但可接受（小文档 chunks 数少）。生产若需高吞吐可换 GPU 端点（届时只需改 `.env` 的 `EMBEDDING_BASE_URL`，维度自适应代码已就位）。
4. `.env` 为本地开发配置（含真实密码），.gitignore 已覆盖，未入 git。

## 6. 文件清单（本 bugfix 提交）

- 新增：`02-development/deploy/embedding/{app.py,Dockerfile,requirements.txt}`、`02-development/BUGFIX_REPORT.md`
- 改动：`backend/app/utils/es_client.py`（ensure_index 维度自适应）、`backend/app/utils/ai_client.py`（dim 探测+缓存）、`backend/app/workers/tasks.py`（real_dim）、`backend/app/main.py`（lifespan 用实测维度）、`infra/.env.example`（EMBEDDING_BASE_URL 注释+本地端点）
- `.env`（本地，不入 git）：`EMBEDDING_BASE_URL=http://127.0.0.1:8100/v1`
- 不动：ES/向量检索核心路径、pageindex 功能、前端、外部容器
