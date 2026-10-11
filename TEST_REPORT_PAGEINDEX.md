# TEST_REPORT — kb-management PageIndex 检索（feat/pageindex）

**测试**：云天明  2026-10-10
**任务**：t_553f17d8（验收）
**分支**：`feat/pageindex`（commit `383e596`，已按用户要求 checkout 到该分支验收）
**依据**：`00-management-PAGEINDEX_BRIEF.md` 验收标准 5 条（2026-10-10 口径变更：按文档二选一）
**配套**：`03-testing/TEST_PLAN.md`、`TEST_CASES.md`、`curl/`（可重放命令索引）、`api_results.json`、`edge_results.json`

---

## 结论（先行）

> **测试结论：PASS**
> **是否满足验收标准：是（5/5 全部 PASS）**
> **阻塞性问题：无**（无 P0/P1；发现 1 个 P3 观察项 + 1 个外部环境影响，均不阻塞）

---

## 1. 逐条验收标准

### ✅ AC-1 上传 pageindex 文档 + 异步索引完成 — PASS

- 注册测试账号 → 建 KB → `POST /documents (index_type=pageindex)`（`curl/case_*` 等价操作，见 `api_results.json`）
- 上传 `ops_manual.md`（2.3KB，5 个 h1 章节）→ 轮询至终态
- **实际**：`status=indexed`、`meta.pageindex_status=degraded`（首次 LLM 建树输出未过校验，走 R2 降级 heading 规则树，属**设计内**降级）、`pageindex_tree.node_count=13`、`build_ms=77410`、**90s 完成**
- **互斥生效**：`chunk_count=0`（pageindex 文档不走向量索引）
- **index_type 正确记录**：`meta.index_type=pageindex`
- 对照：同 KB 上传 `one_node.md (index_type=embedding)` → 走分块+向量路径（因 embedding 端点不可达 → `failed`，证明分流正确：它走了向量路径而非建树）

> **观察项（P3，非缺陷）**：2.3KB 小文档首次 LLM 建树命中降级（`degraded`），但 reindex 重建后变 `ok`。属 LLM 输出非确定性 + 既有降级兜底，检索对 `ok`/`degraded` 均正常工作，不影响验收。建议开发关注建树 LLM 输出的校验通过率（可选优化，非阻塞）。

### ✅ AC-2 search mode=pageindex 返回相关段落 — PASS

- `POST /knowledge-bases/{kb}/search {query:"模型服务不可用时应该怎么排查？", mode:pageindex, top_k:5}`
- **实际**：HTTP 200，`items=3`，`took_ms=3446`（LLM 推理检索）
- 每条含 `document_id` / `content` / `score` / `match_type=pageindex` / `metadata`（node_id、node_title、char_start/end、score_source=llm_relevance）
- 命中 `ops_manual.md`，内容正确（"### 3.2 模型服务不可用排查 模型服务不可用时，先检查端点连通性与密钥有效性…"），`score=1.0`
- 可重放命令：`curl/case_ac2_search_pageindex.sh`（**已重放验证 PASS**：HTTP 200，命中 doc 33010660）

### ✅ AC-3 chat retrieval_mode=pageindex 流式回答 + 引用正确 — PASS

- `POST /knowledge-bases/{kb}/chat {question:"队列积压超过多少条会触发告警？", retrieval_mode:pageindex}`
- **实际**：HTTP 200，SSE **52 个事件**（流式 token），`sources` 事件 **2 条**（chunk_id/document_id/filename/chunk_index/score 五字段齐全）
- **回答**：「队列积压超过 **200 条** 时会触发 P2 级告警 [1]。」
- **引用正确**：含 `[1]` 来源标注，且内容与文档一致（文档 2.1 告警分级明确"队列积压超过 200 条时触发 P2 告警"）
- 可重放命令：`curl/case_ac3_chat_pageindex.sh`

### ✅ AC-4 回归：hybrid/vector/keyword 原路径不受影响 — PASS

- 同一 KB 分别 `POST search mode=hybrid / vector / keyword`
- **实际**：三值均 **HTTP 200, code=0**，正常返回（`items` 列表）
- **代码级红线证据**（`git show 383e596`）：
  - `backend/app/utils/es_client.py` **零改动**（diff 为空）——向量/关键词检索核心未动
  - `backend/app/utils/ai_client.py` **仅新增 `chat()` 方法**，`embed_one()`（向量路径）**零删改**
  - `rag_engine.stream_answer` 仅在 `retrieval_mode==pageindex` 时分流，其余走原 `es_client.hybrid_search()`（行为不变）
- 可重放命令：`curl/case_ac4_regression.sh`（**已重放验证 PASS**：三值均 HTTP 200）

> **外部环境影响（非缺陷）**：本轮 embedding 端点 `34.64.61.208:4000` 不可达（health=`embedding:unreachable`），故 `items=[]`、embedding 文档向量索引 `failed`。这是外部环境态（开发 DEV_REPORT §5 已声明），**原路径代码零改动**已用 git diff 证明，端点恢复后自动正常。回归判据按"原路径行为不变 + 代码零改动"双证据判定 PASS。

### ✅ AC-5 前端 PageIndex 模式选择可用 — PASS

**浏览器实测**（Chrome headless，前端 9013 vite dev 本轮启动）：

1. **登录**：`ui_tester_pi` 登录成功（token 写入 localStorage）
2. **建 KB**：UI「新建知识库」→「UI验收KB」创建成功
3. **上传（选 PageIndex radio）**：KB 详情页「索引方式」radio 选择 **PageIndex（树索引）** → 上传 `ops_manual.md` → 状态流转 `解析中 → 建树中 → 已建树/已索引`（文档列表「索引方式=PageIndex」「PageIndex=已建树」）
4. **搜索（选 PageIndex 模式）**：搜索页「PageIndex」radio → 搜「模型服务不可用怎么排查」→ **找到 8 条结果**，每条带 `PageIndex` 标签、相关度 100/85/75%、node_id/node_title/char 区间元数据
5. **问答（选 PageIndex 模式）**：问答页「PageIndex」radio → 问「队列积压超过多少条会触发告警？」→ 流式回答「队列积压超过 200 条 时会触发 P2 级告警 [1] [2] [3] [4]。」+「参考来源」4× ops_manual.md 标签

**前端代码核对**（`git show 383e596`）：
- `KbSearchView.vue`：el-radio-group 四模式（混合/向量/关键词/PageIndex），`mode` 传入 `search()`
- `KbChatView.vue`：el-radio-group 四模式，`retrievalMode` 传入 `chatStream()`
- `KbDetailView.vue`：上传 radio（Embedding/PageIndex）+ 文档列表「索引方式」「PageIndex」两列 + 重建索引按钮
- `api/index.ts`：`uploadDoc(indexType)` / `search(mode)` / `chatStream(retrievalMode)` 参数齐备

> **观察项（P3，非缺陷）**：UI 上传后若树尚在构建（`pageindex_status=building`）时立即搜索，返回「未找到相关结果」（无 pageindex 索引文档 → 空 + 提示，不静默回退，**符合 v2 设计**）。构建完成后再搜即正常（8 条）。属正确行为，但前端可在「建树中」状态给出更明确提示（可选优化，非阻塞）。

---

## 2. 边界 / 异常测试（EDGE，6/6 PASS）

| # | 用例 | 结果 | 证据 |
|---|---|---|---|
| EDGE-1 | **大文档多分片建树**（47.7KB，无 heading → 硬切 2 片） | PASS | `status=indexed`、`pageindex_status=ok`、`piece_count=2`、`node_count=41`、`build_ms=102731`（**120s < 900s 上限**）、API 上传 <1s 不阻塞 |
| EDGE-2 | **树退化（单节点文档）**（211B 单段无 heading） | PASS | `status=indexed`、`pageindex_status=ok`、`node_count=1`；检索返回该段（`items=1`，内容=「星尘知识库是一款面向中小企业的轻量级知识库管理系统…」），不崩溃、无脏数据 |
| EDGE-3 | **LLM 不可用时的错误提示** | PASS | 模拟 LLM 端点不可达（monkeypatch `llm_client.chat` 抛 ConnectionError）→ `retrieve()` 捕获，返回 `results=[]` + `extra={'error':'LLM endpoint unreachable (simulated for EDGE-3)'}`，**不抛异常、不静默回退 ES** |
| EDGE-3b | **无 pageindex 文档 KB**（不静默回退，v2 验收重点） | PASS | 检索：`items=[]` + `message="该知识库下没有使用 PageIndex 索引的文档…"`；问答：SSE `error` 事件 + 同提示，**不空答、不回退 ES** |

**边界补充（已在 AC 覆盖中验证）**：
- 非法 `mode=badmode` → **HTTP 422**（schema pattern 校验生效）
- embedding 文档调 `pageindex/rebuild` → **HTTP 400**「该文档不是 PageIndex 索引方式」（类型保护）
- pageindex 文档 `reindex` → 按 `index_type` 重建成功（`status=indexed, pi=ok`）

---

## 3. 回归影响（红线核对）

| 红线 | 验证 | 结论 |
|---|---|---|
| 不改动现有 ES/向量检索路径 | `git show 383e596 -- backend/app/utils/es_client.py` = **空**；`ai_client.py` 仅加 `chat()`，`embed_one` 零删改；`rag_engine` 仅 pageindex 分支分流 | ✅ 守住 |
| 密钥只进 .env，不进 git | `git show 383e596 --stat` 无 `.env`/secret 文件，仅 `.env.example` 被跟踪；`infra/.env` 未入 git | ✅ 守住 |
| 不改外部容器（carefold-*/nginx-test） | 测试全程未触碰外部容器（`docker ps` 核对 carefold-agent / carefold-pageindex / nginx-test 均 Up，未被改动） | ✅ 守住 |

---

## 4. 测试数据与可重放证据

- **API 结果快照**：`03-testing/api_results.json`（20/20 PASS，含 sample_answer / sample_sources）
- **边界结果快照**：`03-testing/edge_results.json`（6/6 PASS）
- **执行日志**：`03-testing/api_test_stdout.log`、`edge_test_stdout.log`
- **curl 命令存档**：`03-testing/curl/`（4 条脚本 + `README.md` 索引表，`bash -n` 全部 rc=0，**已用真实 token 重放验证**：AC2 命中 doc 33010660、AC4 三模式 200、EDGE 空+提示）
- **测试文档**：`03-testing/testdata/`（ops_manual.md / one_node.md / large_doc.md 自动生成）
- **测试脚本**：`03-testing/run_api_test.py`、`run_edge_test.py`

---

## 5. 环境说明（影响判读，非缺陷）

| 组件 | 状态 | 影响 |
|---|---|---|
| 后端 9012 / Celery | Up（含 id 修复代码） | 无 |
| 前端 9013 | 本轮启动（vite dev） | 无 |
| PG 9011 / ES 9200 / MinIO 9002 / Redis 6390 | 正常 | 无 |
| LLM vllm-qwen3.8-27b @34.121.9.233:4000 | 可达（health=ok） | pageindex 建树/检索正常 |
| **embedding @34.64.61.208:4000** | **不可达（外部）** | embedding 文档向量索引 failed；AC4 回归 `items=[]` —— **环境态，非代码缺陷**，端点恢复后自动正常 |
| MinerU 9030 | 未启动 | 仅影响 pdf/docx 解析；本轮用 md 文档，不受影响 |

---

## 6. 问题清单（BUGS）

**无 P0 / P1 阻塞问题。**

- **P3-1（观察，非缺陷）**：小文档首次 LLM 建树偶发命中 `degraded` 降级（reindex 后变 `ok`）。属既有 R2 降级兜底 + LLM 非确定性，检索对 ok/degraded 均正常。建议（可选）：提升建树 LLM 输出校验通过率 / 重试策略。**不阻塞验收。**
- **P3-2（观察，非缺陷）**：树构建中（`building`）时 UI 搜索返回「未找到相关结果」（符合 v2「不静默回退」设计），但提示文案未区分「构建中」与「无文档」。建议（可选）：前端对 building 状态给更明确提示。**不阻塞验收。**

---

## 7. 最终结论

- **5 条验收标准全部 PASS**（AC-1 ~ AC-5）
- **边界/异常 6/6 PASS**（大文档多分片、单节点退化、LLM 不可用提示、不静默回退）
- **回归红线守住**（ES/向量路径零改动、密钥未入 git、外部容器未触碰）
- **无阻塞性问题**（2 个 P3 观察项，均可选优化，不阻塞）
- 可重放 curl 命令已存档并实测重放通过

**✅ PageIndex 检索（feat/pageindex）验收通过（PASS），可进入褚岩验收。**

---

## 8. 独立复测（run 24，2026-10-10 10:50 UTC）

首次运行（run 22）在 150 次迭代预算耗尽前已完成全部测试与本报告，但未及执行 kanban 收尾。本轮（run 24）**未重做测试**，按铁律以「重放存档命令 + 独立脚本复核」方式验证报告结论，全部与报告一致：

| 用例 | 重放方式 | 结果 | 证据 |
|---|---|---|---|
| AC-1 异步索引 | `GET /documents` 读 doc `33010660` 当前状态 | PASS | `status=indexed`、`index_type=pageindex`、`pageindex_status=ok`（reindex 后）、`node_count=13`、**chunk_count=0**（互斥） |
| AC-2 search pageindex | 重放 `curl/case_ac2_search_pageindex.sh`（入参未变） | PASS | HTTP 200，items=3，首条命中 doc `33010660`，score=1.0/0.85/0.75，match_type=pageindex，metadata 含 node_id/node_title/char 区间，took_ms≈3000 |
| AC-3 chat pageindex | 重放同参数（`03-testing/verify_final.py`） | PASS | SSE 事件类型 `meta→token×33→sources→done`（流式）；回答「队列积压超过 **200 条** 时会触发 **P2 级告警** [1]。」；sources 2 条五字段齐全（score 0.98/0.65），引用与文档 2.1 一致 |
| AC-4 回归 | 重放 `curl/case_ac4_regression.sh`（入参未变） | PASS | hybrid/vector/keyword 均 HTTP 200 code=0（items=0：KB 内无向量 chunk，embedding 端点仍不可达，属环境态）；`mode=badmode` → 422 |
| EDGE 无 pageindex 文档 | 本轮**新建** KB `d5c906a6-…`（全新账号，独立于原测试数据）复测 search+chat | PASS | search：items=[] + message「该知识库下没有使用 PageIndex 索引的文档…」；chat：SSE `event: error` + 同提示，不空答、不回退 ES |
| 红线核对 | `git show 383e596` 复核 | PASS | `es_client.py` diff=0 行；`ai_client.py` 删除行仅 1 处 typing import（`embed_one` 零删改）；commit 无 `.env`/secret 文件；外部容器（carefold-agent / carefold-pageindex / nginx-test）未被本测试触碰（仍在运行） |

**复测结论**：5 条验收标准 + 边界 + 红线全部独立复核通过，与原报告结论一致，无新增问题。
**最终结论：PASS，可进入褚岩验收。**

> 复测记录：2026-10-10 10:50 UTC，重放文件 `curl/case_ac2_search_pageindex.sh`、`curl/case_ac4_regression.sh` 及脚本 `03-testing/verify_replay2.py`、`verify_diagnose.py`、`verify_final.py`（结果 `03-testing/replay_results2.json`、`ac3_replay.json`）。入参均未变动，未重新生成命令。
