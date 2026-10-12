# TEST_REPORT_DEFAULT_PAGEINDEX — 上传默认索引方式 embedding → pageindex 独立验证报告

- 报告卡：`t_474fa19f`（VI-PI-5，验证链 `t_7e6b150e` 最后一段）
- 报告人：云天明（测试工程师）
- 验证链：`t_fa5d836a`(脚手架) → `t_32351222`(用例1+3) → `t_bbb32bcf`(用例4+5) → `t_2ba41218`(用例2+6) → `t_474fa19f`(本报告)
- 交付物：本报告 + `03-testing/evidence/` + `03-testing/curl/` + `03-testing/fixtures_pi/` + `03-testing/BUGS.md`
- 证据纪律：本报告**所有判定只引用本验证链自己产生的证据文件 + 执行时间戳**；`02-development/DEV_REPORT.md`、`05-temp/*`（开发自测）**仅用于"与开发自测是否一致"一栏的对照，不作为证据**。

---

## 1. 结论摘要

### 1.1 测试时间窗口（UTC）

| 阶段 | 卡 | 时间（UTC） |
|---|---|---|
| 环境快照 / 夹具 / curl 脚手架 | t_fa5d836a | 2026-10-12 03:22:12 ~ 03:26:53 |
| 用例1 + 用例3 | t_32351222 | 03:29:53（建 KB）/ 03:30:40 ~ 03:32:14（主执行）/ 03:35:00 ~ 03:38:00（同参重放）|
| 用例4 + 用例5 | t_bbb32bcf | 03:39 ~ 03:47:53（含只读存量审计 03:47）|
| 用例2 + 用例6 | t_2ba41218 | 03:50:15 ~ 04:08:19（DIAG3 隔离实验 04:04:04 ~ 04:06:04）|
| 汇总（本卡）| t_474fa19f | 04:10:54 ~ 04:11:46（契约/健康度复核）|

**整窗口：2026-10-12T03:22:12Z ~ 2026-10-12T04:11:46Z**

### 1.2 被测分支 / commit / 部署实例

- 分支：`feat/default-pageindex`
- **被验证的改动 commit**：`3dc1ddf`（`feat(upload): 上传默认索引方式 embedding → pageindex`，2026-10-12 03:16:05 UTC）
- **窗口内 HEAD 漂移（必须记录的环境态）**：
  - 用例1/3/4/5 运行时 HEAD = `74287fa`（2026-10-12 03:17:51）
  - 用例2/6 运行时 HEAD = `078a65c`（2026-10-12 03:39:16）
  - 漂移原因：并发卡 `t_efead8b4` 的 `5856436`（`feat(retrieval): 检索/问答默认模式新增 auto（智能）`，03:36:51 UTC）在验证链窗口内合入。
  - ⇒ 本报告对**默认检索/问答模式**的观测跨了两个 commit（详见 §3.5 与 §5）。
- 部署实例（本卡实测 `ss -ltnp` + `ps -eo lstart` 复核，04:11:46 UTC）：
  - 后端 9012：uvicorn PID **3093130**，启动 **2026-10-12 03:28:16 UTC**（实测持有 :9012）
  - MCP 9100：uvicorn PID **3123268**，启动 2026-10-12 03:42:06 UTC（`mcp_server:streamable_app`）
  - Celery：PID 3043762 / 3043869 / 3043870，`-Q kb --concurrency=2`，启动 2026-10-12 03:05:40 ~ 03:05:41 UTC（未重启）
  - 说明：V1 快照时 9012 为 PID 3056922（03:12:10），窗口内被并发卡重启为 3093130；`backend/app/schemas/schemas.py`、`api/search.py`、`api/chat.py`、`services/auto_retrieval.py` 的 mtime 均为 03:26:0x~03:26:34 **早于**该进程启动时间，故 03:28:16 起 9012 加载的是含 auto 的工作树代码（与实测 openapi `mode/retrieval_mode default=auto` 自洽）。
- 契约复核（04:11:46 UTC，本卡实测 `GET /openapi.json`，HTTP 200）：
  - `Body_upload_doc_...documents_post.index_type` → `default=pageindex`, `pattern=^(embedding|pageindex)$`
  - `SearchReq.mode` → `default=auto`, `pattern=^(auto|hybrid|vector|keyword|pageindex)$`
  - `ChatReq.retrieval_mode` → `default=auto`, `pattern=^(auto|hybrid|vector|keyword|pageindex)$`

### 1.3 环境快照要点（`03-testing/evidence/PI-V1_env_snapshot.txt`，03:26:53 UTC）

- `GET /api/v1/health` → HTTP 200，`code=0`，整体 `status=degraded`（**仅** `mineru=unreachable`，历史已知）；`postgresql/elasticsearch(green)/minio/redis/llm/embedding` 全 ok。
- LLM：`https://api.deepseek.com/v1` + `deepseek-flash`（`PAGEINDEX_LLM_MODEL=deepseek-flash`，`LLM_MAX_TOKENS=2048`）。
- Embedding：`http://127.0.0.1:8100/v1` + `gte-qwen2`，`EMBEDDING_DIM=3584`。
- 端口：9011(PG) / 9012(后端) / 9100(MCP) / 9200(ES) / 9002(MinIO) / 6390(Redis) 均在监听。
- 登录：`kb_login` OK，HTTP 200，token 仅记长度（209），未落盘。
- DB 只读基线（`lib/db_probe.py dist`）：`total_docs=97`；`embedding/indexed=33`、`embedding/failed=35`、`pageindex+ok/indexed=26`、`pageindex+degraded/indexed=2`、`pageindex/failed=1`。

### 1.4 整体判定

> ## ❌ 不通过 / 有条件通过
>
> 6 条用例中 **3 条整体 PASS**（用例1、4、5），**3 条含 FAIL**（用例2 子项 FAIL、用例3 FAIL、用例6 CONFLICT）。
> 存在 **2 条未决 P1 阻塞项**（BUG-V4-01、BUG-V4-02），另有 1 条未决 P2 观察项。
> **不得进入项目完成状态**（阻止项目完成是测试岗的权限）。**不得进入褚岩验收**，须先修复/定级两条 P1 并回归。
>
> 判定口径：本链 6 条用例的**任何一条硬断言 FAIL ⇒ 该用例整体记 FAIL**（即使其它子项 PASS）。子卡使用过的 PARTIAL / CONFLICT 标签在表中保留为"子卡裁定"，便于追溯。

---

## 2. 逐条用例表

| 用例 | 判定（本报告） | 子卡裁定 | 证据（文件 + 关键数字 + 时间戳） | 与开发自测结论是否一致 |
|---|---|---|---|---|
| **1. API 不传 `index_type` 上传 → meta 应为 pageindex 且非降级** | ✅ **PASS** | PASS | `evidence/PI-V2_result.json` → `case1.assertions` A1–A5/A7/A8 全 true；`evidence/PI-V2_case1_case3.txt` L10–L38：HTTP 200 / `code=0` / `index_type=pageindex` / `pageindex_status=ok` / `tree_status=ok` / `tree_model=deepseek-flash` / `node_count=3`（4 个 H2+3 个 H3 的 heading 规则树应 ≥7 节点 ⇒ 确为 LLM 归并树）/ `build_ms=64107` / `chunk_count=0` / `status=indexed` / doc=`034cc16f-d230-4fca-beb1-04da2337cc2d`；`openapi` upload `index_type default=pageindex`。时间：上传 03:30:40Z → indexed 03:31:46Z（轮询 t=70s） | **一致**（开发自测：不传 index_type → `index_type=pageindex` + `pageindex_status=ok`） |
| **2. 线上 https://agent.carefold.ai/kb-management/ 默认选中 pageindex，直接上传成功并走树索引** | ❌ **FAIL**（主体 PASS / A5 检索问答稳定性子项 FAIL） | PARTIAL | 主体：`evidence/PI-V4_result.json` → `case2.checks` C2-1~C2-7d 全 PASS；`evidence/PI-V4_case2_case6.txt` A6/A6b/A3/A4 段 —— 线上入口 200、入口 js 实测 `assets/index-BHI8vxe6.js`、chunk `assets/KbDetailView-CcLfGsq-.js` sha256 `c4c9ff349fd02ec4f7c81f0151f2a2ae97f49c43a33b56ac565f4fb42b538f53`、minified `V=o(`pageindex`)`+`me=c(()=>({index_type:V.value}))`、DOM `PageIndex（树索引）` `isActive=true`/`inputChecked=true` 而 `Embedding` 均 false、`radioClicks=0` 直传 FormData=`[["index_type","pageindex"],["file","pi_default_doc.md"]]`、结果 `pageindex/ok/indexed`、`node_count=3`、`build_ms=34212`、`chunk_count=0`；截图 `PI-V4_ui_default.png`/`_row.png`/`_indexing.png`/`_indexed.png`。时间：03:50:15Z（线上产物）/ 03:52:09Z（DOM）/ 03:52:16Z（首次上传）/ 04:00:41Z（二次上传抓建树中）。**子项 A5 FAIL**：`case_PI-09` 主查询 ×3 `total=2/0/0`（1/3 命中，04:06:54~04:07:03Z）；`case_PI-10` ×3 `sources=0/2/0`（1/3，04:07:06~04:07:45Z），0 命中时发 `event:error`「未检索到相关 PageIndex 内容…」（该 KB 确有 2 篇 `pageindex_status=ok` 文档）→ 见 BUG-V4-01 | **不一致（新增缺陷）**：开发自测只做了**单次**「UI 默认选中 → 上传 → 检索/问答有来源」，未做同参重复取样，未暴露 1/3 空结果率。线上 js 指纹亦不一致（开发文档称 `index-CaTnCPvY.js`，实测 `index-BHI8vxe6.js`）——属文档滞后 |
| **3. pageindex 文档的检索/问答可用（sources 正常）** | ❌ **FAIL**（检索子项 FAIL；问答子项 PASS） | FAIL | 检索 `evidence/PI-V2_result.json` → `case3.search`：首执 HTTP 200 但 `total=0`/`items=[]`（`took_ms=1440`，无 `message`），S2/S3 FAIL；同参重放 4 次 `total=[0,0,1,0]`（1/4），变体问法 5 条命中 3/5（`variants_hit_rate_summary=3/5`）——非确定性。原始输出 `evidence/PI-V2_case1_case3.txt` L42–L57、`evidence/raw/PI-02_search_main.json`、`evidence/raw/PI-02_replay_main_1..4.json`。问答 `case3.chat` **PASS**：SSE `meta→token×50→sources→done`，`sources=1`，答案「…应使用口令 **PI-TOKEN-7412**…[1]」，重放 2 次 `sources=1/2`（`evidence/raw/PI-03_chat_main.sse`）。时间：03:31:46Z ~ 03:32:14Z，重放 03:35:00Z ~ 03:38:00Z | **不一致**：开发自测称 pageindex 检索 **5/5 问法命中**；本链同参重复取样仅 1/4~3/5 命中 ⇒ 单次自测无法覆盖该非确定性 |
| **4. 回归：显式选 embedding 上传 → 仍走分块 + 向量索引，功能正常** | ✅ **PASS** | PASS（10/10 断言） | `evidence/PI-V3_result.json` → `checks` PI-04 A1/A2/A3a/A3b/A4a/A4b/A5/A6/A7a/A7b 全 PASS；`evidence/PI-V3_case4_case5.txt` A 段：`index_type=embedding` / `status=indexed` / `chunk_count=1` / `meta` 无 `pageindex_tree` / `pageindex_status` 不存在；`mode=vector` `total=1` 命中、`mode=hybrid` `total=1` 命中；同文件显式 pageindex 对照 `pageindex_status=ok`/`node_count=2`；KE 对照 `tests/e2e_test.py` 8/8 通过（`evidence/PI-V3_case4_ke_e2e.txt`）。时间：03:39 ~ 03:40Z | **一致**（开发自测：显式 embedding → 分块+向量正常；e2e 8/8 PASS） |
| **5. 存量文档不受影响（meta 无 index_type 或为 embedding 仍按原方式检索/重建，未被错改成 pageindex）** | ✅ **PASS** | PASS（A1–A5 violations=0 + 步骤5 全 PASS） | 只读审计 `evidence/PI-V3_legacy_audit.json` + `evidence/PI-V3_legacy_audit_run1.txt` + `evidence/PI-V3_legacy_docs.tsv`：全量未删文档 **117** 篇，存量口径（uploaded_at ≤ 3dc1ddf 的 03:16:05Z）**89** 篇，严格改动前（<02:40Z）**55** 篇；`index_type` 全量 `{<none>:2, embedding:81, pageindex:34}`、存量 `{embedding:60, pageindex:29}`；A1 存量 embedding **无一**带 `pageindex_tree`（violations=0）、A2 无非法 `index_type`（0）、A3 三口径均成立、A4 存量 embedding+indexed 均保有分块（0）、A5 真实存量「无 index_type」**0 篇**（2 篇 `<none>` 全部为本链 PI-07 自建模拟，`other=0`）。行为性重建：`evidence/PI-V3_case4_case5.txt` D/E 段 —— 存量 embedding 文档 `99c37b1e-…` reindex 响应 `index_type=embedding`、重建后 `indexed`/`chunk_count=1`/`meta.index_type` 未被改写、vector 命中；`pageindex/rebuild` 对非 pageindex 文档 HTTP **400**「该文档不是 PageIndex 索引方式…」；存量 pageindex 文档 `7b678d3f-…` 重建后 `pageindex_status=ok`/`index_type=pageindex`；模拟无 index_type 文档 `08aca631-…`（自建 KB `52d96f8c-…`，DB 删键）reindex 响应 `index_type=embedding`、`indexed`、`chunk_count=1`、vector/hybrid 各 `total=2` 命中 `LEG-TOKEN-6390`；前端兜底 `|| 'embedding'` grep 命中 3 处（KbDetailView.vue:61/62/273）。时间：03:43 ~ 03:47Z | **一致（方向），但口径数字不一致**：开发侧称存量 73 篇（51 embedding / 22 pageindex、无 index_type 0 篇）；本链实测全量 117 篇 / 存量 89 篇 / 存量分布 60/29、真实无 index_type **0 篇**。结论方向一致（无 index_type 真实存量为 0、存量未被错改），**数据库口径需对齐** |
| **6. push 默认 pageindex 场景下与 MCP 引用链路不冲突** | ❌ **FAIL**（冲突成立） | CONFLICT | `evidence/PI-V4_result.json` → `case6.checks` C6-1/C6-3/C6-4/C6-6 PASS、C6-2/C6-5a 为冲突项；`evidence/PI-V4_case2_case6.txt` B7/B8/B7+ 段：run1（KB 只有 2 篇默认 pageindex 文档，`chunk_count=0`/`pageindex_status=ok`）→ MCP `search_knowledge` `total` = hybrid **0** / vector **0** / keyword **0**（04:01:51Z）；`MODES=pageindex` 探针 → `total=0`、`took_ms=0`、**无 error**（静默空结果，04:08:12Z）；反向对照 run2（同 KB 追加 1 篇**显式 embedding、同夹具同口令** 文档 `9c8f8743-…`，04:07:51Z）→ `total` = hybrid **2** / vector **2** / keyword **1**，全部命中 embedding 副本并带 `doc_url` + `location`（04:08:00Z）；两篇默认 pageindex 文档 `30691711-…`/`dd083cf9-…` 在 run1+run2 共 **12 次返回中 0 次出现**；`tools/list` 全响应中 `pageindex` 出现 **0 次**（04:08:19Z）→ 见 BUG-V4-02 | **未验证**：开发自测完全未覆盖 MCP 引用链路（`mcp_server.py` 侧无任何验证）；本链属首次实测，发现冲突 |

### 2.1 判定明细统计

- PASS：用例 1、4、5（3/6）
- FAIL：用例 2（A5 子项）、用例 3（检索子项）、用例 6（冲突成立）（3/6）
- NOT-RUN：0 条（无"缺证据"项；所有判定均指向本链证据文件）

---

## 3. 回归段

### 3.1 embedding 显式路径（用例4）

- `index_type=embedding` 显式上传 → `meta.index_type=embedding`、`status=indexed`、`chunk_count=1`、meta 内**无** `pageindex_tree`、`pageindex_status` `<absent>`；`mode=vector` 与 `mode=hybrid` 均 `total=1` 命中 `EMB-TOKEN-8251`。
- 同一 KB 内显式 pageindex 对照文档 `pageindex_status=ok`、`node_count=2` — 两种索引方式在同一 KB 内共存互不干扰。
- 仓库自带 E2E 套件 `tests/e2e_test.py`（该套件上传步骤显式 `index_type=embedding`）独立跑 **8/8 全绿**（`evidence/PI-V3_case4_ke_e2e.txt`）。
- 结论：**embedding 路径无回归**。

### 3.2 存量文档审计（用例5）

| 口径 | 篇数 |
|---|---|
| 全量（`is_deleted=false`） | 117 |
| 存量（uploaded_at ≤ 3dc1ddf 03:16:05Z） | 89 |
| 严格改动前（uploaded_at < 02:40Z） | 55 |
| 位于**已软删** KB 内 | 73（行为性操作不可达，只读审计覆盖） |
| 位于 live KB 内 | 44（行为性重建只在此子集） |

- `index_type` 分布（全量）：`<none>` **2** / `embedding` **81** / `pageindex` **34**；存量：`embedding` **60** / `pageindex` **29**。
- 无 `index_type` 兜底：**真实存量为 0 篇**。审计断言 `A5_no_real_legacy_docs` PASS（`none_total=2`，全部为本链 PI-07 自建模拟，`other=0`）。该分支以**自建 fixture 模拟**（`fixtures_pi/legacy_no_index_type_doc.md` + DB 删键）验证，**不得当作存量真实分布**。
- 未被错误改写：存量 `index_type=embedding` 文档无一带 `pageindex_tree`（violations=0）、无非法 `index_type`（0）、存量 embedding+indexed 均保有分块（0）。
- 行为性重建：存量 embedding 响应 `index_type=embedding`（`documents.py` 兜底未被改）、存量 pageindex 重建后 `pageindex_status=ok`；非 pageindex 文档 `pageindex/rebuild` HTTP 400 明确拒绝。
- 结论：**存量文档未受本次默认值变更影响**（例外：见 §4 OBS-REINDEX-CHUNK-DUP，属改动前既有行为）。

### 3.3 线上 UI 默认值（用例2 主体）

- 线上入口 200；`KbDetailView` chunk 内 `indexType` 默认值 minified 为 `V=o(`pageindex`)`，上传体 `me=c(()=>({index_type:V.value}))`。
- DOM 实测：`PageIndex（树索引）` `class` 含 `is-active` 且内部 `input.checked===true`；`Embedding（分块+向量）` 两者均 false。
- `.upload-options-desc` 文案（**仅在选中 pageindex 时渲染**）可见并与源码模板串一致，含第 5856436 追加的「问答与检索时选择「智能」或「PageIndex」模式即可命中本类文档。」
- **不点任何 radio** 用 CDP `DOM.setFileInputFiles` 直塞文件上传 → 实测 FormData `index_type=pageindex`、`radioClicks=0` ⇒ 默认值来自前端默认而非用户操作。
- 结论：**线上 UI 默认值 = pageindex 成立**（该部分 PASS）。

### 3.4 回归观察：reindex 分块重复堆积

- 存量 embedding 文档 `99c37b1e-…` 重建索引前后：PG `chunk` 行 1 → 2 → 3，而 `doc.chunk_count` 恒为 1；同查询 `mode=vector` 检索 `total` 同步 1 → 2 → 3，返回 **content/score 完全相同的重复条目**。
- 证据：`evidence/raw/PI-06_chunks_before.txt`、`PI-06_chunks_after.txt`、`PI-06_search_vector.json`。
- **非本次改动引入**（`workers/tasks.py::chunk_index_task` 只 `add` 不 `delete`，`api/documents.py` reindex 无清理），故 **不作为本次 PASS/FAIL 依据**，列为 P2 观察项。

### 3.5 MCP 链路对照（用例6）

- MCP `search_knowledge` 的工具 schema 明示 `mode: hybrid(混合) / vector(纯向量) / keyword(纯关键词)，默认 hybrid`，**无 `pageindex`**；`tools/list` 全响应 `pageindex` 出现 **0** 次。
- 同 KB、同 query（`PI-TOKEN-7412`）、同脚本：只有 pageindex 文档时 `total=0/0/0`；追加显式 embedding 副本后 `total=2/2/1` ⇒ 脚本有效，差异只能归因于索引方式。
- 结论：**冲突成立**（用例6 FAIL）。

### 3.6 默认检索/问答模式的行为漂移（必须在报告中留痕）

- 用例3 段（HEAD `74287fa`，auto 尚未合入）：同一 pageindex 文档**不传 `retrieval_mode`** → `sources=0` + `meta.notice`「未在 PageIndex 索引中检索到相关内容…」（`evidence/PI-V2_case1_case3.txt` L72–L77，03:32:04Z）——即既有 P1 产品决策错配（`t_9013e8b2`）的原始现象。
- 用例2 段（HEAD `078a65c`，`5856436` auto 已合入并生效于 03:28:16 启动的 9012）：同一 KB **不传 `retrieval_mode`** → `sources=2` 且 `metadata.leg="pageindex"`（`evidence/PI-V4_case2_case6.txt` A5-2 观察项，04:07Z）。
- ⇒ 该 P1（`t_9013e8b2`）**已被 PD-001 的 auto 路由正面覆盖**，本链实测未复现站内默认链路 0 来源。
- **注意（不要误读）**：`case_PI-09` 观察项标注的"mode=hybrid（默认模式）"**实际是脚本显式传 `mode=hybrid`**（`case_PI-09_...sh:60`），并非"不传走默认"；该 KB `mode=hybrid` `total=0` 属已知 P1 现象，不判 FAIL。

---

## 4. BUG / 风险清单

> 复现一律引用 `03-testing/curl/case_*.sh` 文件名，不粘贴命令全文（命令在文件里，可直接重放）。

### 4.1 BUG-V4-01 — pageindex 检索/问答间歇性 0 命中（≈1/3），静默空结果无重试，错误文案误导

| 项 | 内容 |
|---|---|
| 严重程度 | **P1（未决）** |
| 影响面 | `3dc1ddf` 让 pageindex 成为**默认上传方式**、`5856436` 让默认检索/问答走 `auto → pageindex` 腿 ⇒「默认上传 + 默认检索」链路继承该 ~1/3 空结果率。用户表现为"问什么都答没资料"。 |
| 复现步骤 | ① `bash 03-testing/curl/case_PI-09_ui_chain_pageindex_search.sh`（`RUNS=3`，观察 3 次 `total`）<br>② `bash 03-testing/curl/case_PI-10_ui_chain_pageindex_chat.sh`（`RUNS=3`，观察 3 次 `sources`）<br>③ 第 2 段对照：`bash 03-testing/curl/case_PI-02_search_pageindex.sh`（主查询 + 4 次同参重放） |
| 预期 | 同参数重复调用稳定命中（`total>=1` / `sources>=1`）——这是检索功能，不是抽样统计 |
| 实际 | `case_PI-09`：`2/0/0`（1/3）；`case_PI-10`：`0/2/0`（1/3）；`case_PI-02`：首执 0 + 同参重放 `0/0/1/0`（1/4）；DIAG3 隔离实验：单文档 KB `3/3`、本 KB（重复文档）`2/3`、第 2 段对照 KB `1/3`。**合计 12 次观测、5 次 0 命中（≈42%）** ⇒ 非本 KB 特有、非重复文档特有，pageindex 引擎本身不稳定 |
| 证据 | `evidence/PI-V4_case2_case6.txt`（A5-1/A5-2/A5-3 段）、`evidence/PI-V4_result.json` → `case2.checks[C2-8, C2-9]`（verdict=FAIL）、`evidence/PI-V2_result.json` → `case3.search`（verdict=FAIL）+ `findings[PI-V2-F1]`、`evidence/raw/PI-02_replay_main_1..4.json`、`evidence/PI-V4_raw/PI-09_console.txt`/`PI-10_console.txt`/`DIAG3_console.txt` |
| 机制旁证（非根因结论） | 0 命中 run `took_ms` 仅 2–3s（命中 run 3–20s）；返回体 `{code:0,total:0}` **既无 `message` 也无 `error`** ⇒ `pageindex_engine.retrieve()` 选节点 LLM 返回空/解析失败后静默返回空，**retrieve 阶段无重试、无兜底**（仅 build 阶段有"带错误信息重试一次"）。与 `3dc1ddf` 提交说明中「`RETRIEVE_MAX_TOKENS` 1024→8192 修 1/6 空结果」属同一缺陷类，**放大预算后仍可复现** |
| 建议 | ① 在 `pageindex_engine.retrieve()` 补：解析失败/空 selected 的重试（至少 1 次，带错误信息）+ 明确日志；② 0 命中且 KB 内确有 pageindex 文档时，错误文案不得写"确认已上传 PageIndex 索引的文档"（见 OBS-V4-1）；③ 定级：因 pageindex 已成默认路径，建议按 P1 提级处理，修后必须重放 `case_PI-09`/`case_PI-10`/`case_PI-02` 做稳定性回归（建议 ≥5 次同参取样） |

### 4.2 BUG-V4-02 — 默认上传的 pageindex 文档在 MCP（智能助手引用链路）上完全不可检索

| 项 | 内容 |
|---|---|
| 严重程度 | **P1（未决）** |
| 影响面 | 所有通过 MCP 检索知识库的智能助手（carefold-agent → kb MCP）**看不到任何默认上传的文档**——用户在默认路径上传的文档，助手侧一律"没有资料" |
| 复现步骤 | ① run1（KB 内只有默认 pageindex 文档）：`bash 03-testing/curl/case_PI-08_mcp_search_knowledge.sh`<br>② 反向对照：`bash 03-testing/curl/case_PI-11_ui_chain_embedding_control.sh` 后重放 `bash 03-testing/curl/case_PI-08_mcp_search_knowledge.sh`（同脚本同 query 应 ≥1）<br>③ 根因取证：`MODES=pageindex bash 03-testing/curl/case_PI-08_mcp_search_knowledge.sh`（key 从 `infra/.env` 读取，只回显长度） |
| 预期 | 默认上传的文档在智能助手链路上应可检索并返回可点击引用（`doc_url` + `location`）；若产品上不支持，工具应**显式拒绝/报错**，让助手能区分"没资料"与"没能力检索这类资料" |
| 实际 | run1 → `total=0/0/0`；`MODES=pageindex` → `total=0`、`took_ms=0`、无 error（静默空结果）；run2（追加显式 embedding 副本）→ `total=2/2/1` 且带 `doc_url`；两篇默认 pageindex 文档 12 次返回中 **0 次出现** |
| 证据 | `evidence/PI-V4_case2_case6.txt`（B7/B8/B7+ 段）、`evidence/PI-V4_result.json` → `case6`（verdict=CONFLICT，C6-2/C6-5a 为冲突项）、`evidence/PI-V4_raw/PI-08_run1_console.txt`/`PI-08_run2_console.txt`/`PI-08_mode_pi_console.txt`/`MCP_tools_list_console.txt`/`FINAL_state_console.txt` |
| 根因（实测口径） | `backend/mcp_server.py` 的 `search_knowledge` 把 `mode` 直接透传给 `es_client.hybrid_search`（只处理 hybrid/vector/keyword），**没有 pageindex 分支**；pageindex 文档不写 ES 分块（`chunk_count=0`），ES 侧永远检索不到；`tools/list` 中 `pageindex` 出现 0 次 ⇒ 工具契约层没有这个概念 |
| 与 `t_9013e8b2` 的关系 | **同源**（都是"默认上传方式改了、下游链路没跟上"），**但发生面不同**：`t_9013e8b2` 是**站内**默认检索/问答 0 来源（已被 PD-001 的 auto 正面覆盖，见 §3.6）；本项是**智能助手（MCP）引用链路**的检索面，实测站内 auto 已能返回 `sources=2`（`leg=pageindex`）而 MCP 恒为 0 ⇒ **两个面不能互相覆盖**，`t_9013e8b2` 的修复不会顺带修好本项 |
| 建议 | **单独立卡（P1）**；修法二选一：MCP 侧补 pageindex 分支（走 `pageindex_engine.retrieve`）或对 pageindex 文档显式拒绝并回明确错误。**不要让工具静默返回 0 条** |

### 4.3 风险与观察项（不单独阻塞，但需留痕）

| ID | 严重程度 | 内容 | 复现 / 证据 | 建议 |
|---|---|---|---|---|
| BUGS.md OBS-REINDEX-CHUNK-DUP | **P2** | 文档级重建索引（embedding 路径）不清理旧分块 → PG `chunk` 行与 ES 文档重复堆积（实测 1→2→3），`doc.chunk_count` 恒为 1，检索返回内容/score 完全相同的重复条目 | `bash 03-testing/curl/case_PI-06_reindex_legacy_embedding.sh`；`evidence/raw/PI-06_chunks_before.txt`/`after.txt`、`PI-06_search_vector.json` | 单独立卡：reindex 前按 `document_id` 删 PG 旧行 + ES 旧文档。**非本次改动引入** |
| OBS-V4-1 | info | 问答 0 来源时 `event:error` 文案固定为「未检索到相关 PageIndex 内容，请换一种问法或确认已上传 PageIndex 索引的文档。」，但 KB 内确有 pageindex 文档 ⇒ **文案误导** | `evidence/PI-V4_raw/PI-10_chat_pageindex_run1.sse`/`run3.sse` | 文案区分"没有 pageindex 文档"与"有文档但本次未选中节点" |
| OBS-V4-2 | info | 线上产物指纹与开发文档不一致：开发文档称入口 `assets/index-CaTnCPvY.js`，实测 `assets/index-BHI8vxe6.js`（`KbDetailView-CcLfGsq-.js`，sha256 `c4c9ff34…`）。原因：`3dc1ddf` 之后 `5856436` 又重建过一次前端 dist | `evidence/PI-V4_raw/A6_online_entry.txt`、`online_KbDetailView.js` | 文档滞后非缺陷；后续卡引用线上指纹以实测为准 |
| PI-V2-F2 | info | 「反降级」旁证断言 A6（`root.title != 夹具 markdown 标题`）字面不成立且**无区分度**（降级树 `root.title` 同样取 H1） | `evidence/PI-V2_result.json` → `findings[PI-V2-F2]`、`evidence/raw/PI-01_tree_dump.txt` | 后续把该断言改为「节点数与 heading 数不符 / 子节点标题非 heading / summary 非逐字摘录」 |
| PI-V2-F3 | info | 任务书描述的 SSE 事件顺序（meta→sources→token→done）与实现（`meta → token×N → sources → done`，`chat.py:84-100`）及仓库既有存档口径不一致 | `evidence/raw/PI-03_chat_main.sse` | 任务书/PRD 口径对齐实现 |
| RISK-DIST-DRIFT | info | 线上前端 dist 会随并发卡重建，**指纹不稳定**（窗口内已知被 `5856436` 重建）；以"线上入口 js 名"作为回归断言会误报 | §3.3、`evidence/PI-V4_raw/A6_online_entry.txt` | 线上断言以"chunk 内字符串 + DOM 行为"为准，不以文件名/`md5` 为准 |

### 4.4 已知决策卡 `t_9013e8b2` 的处置说明

- 现象：默认上传 pageindex（不写 ES 分块）+ 默认问答 hybrid → **默认链路 0 来源**（P1 产品决策错配）。
- 处置：`t_9013e8b2`（assignee luoji）**已 done**，产出 `PD-001`（`01-product/PRODUCT_DECISIONS.md`）与 `01-product/PRD-AUTO-RETRIEVAL.md`：检索/问答默认模式改为 `auto`（前端「智能（推荐）」），按 KB 索引构成自动路由；实现于 `5856436`（`t_efead8b4`）。
- 本链实测结论：**该 P1 已被 auto 路由正面覆盖**（§3.6：不传 `retrieval_mode` → `sources=2`，`metadata.leg=pageindex`，04:07Z）⇒ **不再作为本次阻塞项**。
- 但需注意：**`BUG-V4-01` 仍会命中默认链路**（auto→pageindex 腿继承同一 LLM 空选缺陷，间歇性），**`BUG-V4-02` 与 `t_9013e8b2` 同源但发生面不同**（MCP 面，auto 覆盖不到）。两者均为本次未决 P1。

---

## 5. 未覆盖与限制

### 5.1 NOT-RUN 项及原因

| 项 | 状态 | 原因 |
|---|---|---|
| `PI-07 C8`（MCP 9100 兜底复核 `mcp_server.py:100` 的 `|| "embedding"`） | **NOT-RUN（已由用例6 补做）** | 第 3 段只做最小可达性探测（`GET / -> 401`），完整 `tools/call` 序列归第 4 段；第 4 段已用 `case_PI-08` 完整覆盖（结论见 BUG-V4-02） |
| `tests/e2e_test.py` 以 pytest 形式收集 | NOT-RUN | 该文件是 `__main__` 脚本，pytest 收集不到用例；已改为直接执行（8/8 PASS） |
| 存量「无 index_type」文档的**真实**覆盖 | NOT-RUN（以自建 fixture 模拟替代） | 真实存量 0 篇（`A5_no_real_legacy_docs` `other=0`）⇒ 该分支只能模拟，`case_PI-07` 全流程已显式标注"模拟用例" |
| 存量文档位于**已软删 KB** 内的行为性重建 | NOT-RUN | 73/117 篇所在 KB `is_deleted=true`，接口不可达（首轮实测 404「知识库不存在」，`evidence/PI-V3_case6_run1.txt`）；只读审计覆盖全量，行为性操作只覆盖 live 子集 44 篇 |
| 线上**表单登录**路线 | NOT-RUN | `/kb-management/` 未登录跳 `/login`；本链走「本地 API 签发 token → 注入 `localStorage.kb_token` → 直达 `/kb/<id>`」。**未验证登录表单本身**（不在本次改动范围） |
| `carefold-agent` 端（智能助手侧）完整对话链路 | NOT-RUN | 本链只验证到 MCP `tools/call` 层（契约缺口已定位）；agent 侧渲染/引用去截断不在本链范围 |

### 5.2 环境态依赖（判定随环境漂移的风险）

1. **LLM `deepseek-flash`（api.deepseek.com）可用性**：pageindex 建树与检索选节点**全部依赖该外部 LLM**。实测 `build_ms` 34s~64s、检索 2~20s；`BUG-V4-01` 的空结果直接源于 LLM 选节点返回空 ⇒ 判定受该外部服务波动影响，**单次采样不可靠**。
2. **Embedding 端点 `127.0.0.1:8100/v1`（gte-qwen2, dim 3584）**：embedding 路径（用例4/5）依赖，实测 `embedding=ok`；若不可达，vector 腿会退化，用例4/5 结论作废需重跑。
3. **mineru unreachable**：`health` 恒为 `status=degraded`（历史已知，与本次改动无关）；报告中不得把 `degraded` 当作本次回归。
4. **并发卡共用同一 9012 / Celery**：`t_87e536bf`（BUG-01 跨库泄露复验，`9347c56`）、`t_9013e8b2`（决策）/`t_efead8b4`（auto 实现，`5856436`）在本链窗口内并行占用同一 9012 与 Celery `-Q kb`。
   - 实测影响：① 9012 在窗口内被重启（PID 3056922@03:12:10 → 3093130@03:28:16）；② 分支 HEAD 从 `74287fa` 漂移到 `078a65c`；③ Celery `--concurrency=2` 共享，pageindex 建树为长任务（34~64s），并发时轮询耗时被拉长（用例1 轮询至 t=70s 才 indexed）。
   - ⇒ 本链各段均已记录实测时间点；**跨段横向比较数字时必须以 §1.2 的 HEAD/实例时间为准**。
5. **前端线上产物漂移**：见 RISK-DIST-DRIFT（§4.3）。

### 5.3 模拟夹具与真实存量的区别（不得混淆）

- `fixtures_pi/pi_default_doc.md`（`PI-TOKEN-7412`，sha256 `11321dc6870f…`）、`emb_regression_doc.md`（`EMB-TOKEN-8251`，`ad8bc0fb9722…`）、`legacy_no_index_type_doc.md`（`LEG-TOKEN-6390`，`c3257bbe446e…`）均为**测试自建夹具**，只上传到名字带 `VI-PI` + 时间戳的**自建测试 KB**。
- `case_PI-07` 的"无 index_type 老文档"是**人工删键模拟**（唯一写库动作：删自建文档 `08aca631-…` 的 `meta.index_type` 一个键），**不代表真实存量分布**（真实为 0 篇）。
- 本链在自建 KB 内留下的测试文档（后续如需清理请连同 KB 软删，勿当存量数据）：
  - `32b1101f-efd6-467c-900a-255c75656791`（验证-默认pageindex-VI-PI-2）/ 文档 `034cc16f-…`
  - `13d9130b-5d7c-4421-a217-e28267076d91`（验证-回归-embedding-VI-PI-3）/ 文档 `ea40d0c5-…`（embedding）、`edd5c93e-…`（pageindex）
  - `52d96f8c-a5a5-4e49-be3c-d27764223c31`（验证-兜底-legacy-VI-PI-3）/ 文档 `08aca631-…`（无 index_type）
  - `22bcb345-8326-479c-958b-51daa2905715`（验证-默认pageindex-VI-PI-4）/ 文档 `30691711-…`、`dd083cf9-…`（pageindex）+ `9c8f8743-…`（embedding 反向对照）
  - `4d43c2ef-399d-4fe3-bf08-d0a1d0b8403f`（DIAG3 单文档诊断 KB）/ 文档 `e1ad418a-…`
- **业务 KB 未触碰**：全链只读审计 + 自建 KB 操作（`constraints` 见 `PI-V3_result.json` / `PI-V4_result.json`）；代码零改动、服务未由本链重启、密钥只回显长度（token 209 / MCP key 48）。

### 5.4 断言口径偏差（记录，供下游对齐）

- `PI-V2_result.json.A6`（反降级字面断言）不成立且已证明无区分度 —— 反降级由 4~5 条独立证据支撑（`pageindex_status=ok` / 节点数与 heading 数不符 / 子节点标题非 heading / summary 为改写非逐字摘录 / `build_ms=64107`），见 `findings[PI-V2-F2]`。
- `case_PI-09` 观察项标注"mode=hybrid（默认模式）"实为脚本**显式**传 `mode=hybrid`（`case_PI-09_...sh:60`）；默认模式自 `5856436` 起为 `auto`。
- SSE 事件顺序：实现为 `meta → token×N → sources → done`（任务书写的 `meta → sources → token → done` 不符），按"四类事件齐备 + 顺序符合实现"判定 PASS（`findings[PI-V2-F3]`）。

---

## 6. 最终结论（硬要求）

> ### ❌ **不通过 / 有条件通过**
>
> **不得进入项目完成状态。**（可阻止项目完成是测试岗的权限）
>
> **不通过理由**：任务书 6 条用例中，**用例 2（A5 检索/问答稳定性子项）、用例 3（pageindex 检索子项）、用例 6（MCP 引用链路冲突）判定 FAIL**，且存在 **2 条未决 P1 阻塞项**，不满足"6 条用例全部 PASS 且无未决 P0/P1"的通过条件。
>
> **可以"有条件通过"的部分**（改动核心语义已被证实成立）：
> - ✅ 上传默认索引方式确实已变为 `pageindex`（后端 OpenAPI 默认值 + 线上 UI DOM/网络**双证据**，且**不点任何 radio** 直传即走树索引）；
> - ✅ pageindex 建树非降级（`pageindex_status=ok`、LLM 归并树、真实 `build_ms`）；
> - ✅ 显式 embedding 路径与存量文档（含无 `index_type` 兜底）**均无回归**。
>
> **阻塞项（逐条列出，修复并回归后方可再审）**：
>
> 1. **BUG-V4-01（P1）** — pageindex 检索/问答间歇性 0 命中（12 次观测 5 次空，≈42%），静默空结果、无重试、错误文案误导。**直接命中"默认上传 + 默认检索"主链路**（auto→pageindex 腿）。复现：`03-testing/curl/case_PI-09_ui_chain_pageindex_search.sh`、`case_PI-10_ui_chain_pageindex_chat.sh`、`case_PI-02_search_pageindex.sh`。
> 2. **BUG-V4-02（P1）** — 默认上传的 pageindex 文档在 **MCP（智能助手引用链路）完全不可检索**（`tools/list` 无 `pageindex`，`mode=pageindex` 静默返回 0；反向对照显式 embedding 命中 2 条带 `doc_url`）。复现：`03-testing/curl/case_PI-08_mcp_search_knowledge.sh`、`case_PI-11_ui_chain_embedding_control.sh`。与 `t_9013e8b2` **同源但发生面不同**，需单独立卡。
> 3. **OBS-REINDEX-CHUNK-DUP（P2，非本次引入）** — reindex 不清理旧分块导致重复条目；复现：`case_PI-06_reindex_legacy_embedding.sh`。建议单独立卡，不阻塞本次验收但需登记。
>
> **已解除的阻塞项（记录）**：`t_9013e8b2` 的"默认上传 pageindex 与默认问答 hybrid 错配 → 默认问答 0 来源"P1，已由 `PD-001`（auto 模式）决策并由 `5856436` 实现；本链 04:07Z 实测默认链路 `sources=2`（`leg=pageindex`）**正面覆盖**，不再阻塞。**但其不会覆盖 BUG-V4-02（MCP 面）**。
>
> **后续动作（由测试侧给出，不由本报告代替开发定级）**：
> 1. `BUG-V4-01`、`BUG-V4-02` 各立一张开发/修复卡（建议 assignee：zhangbeihai），修复后回到本报告 §2 对应用例做**稳定性回归**（`case_PI-09`/`case_PI-10` 建议 ≥5 次同参取样，`case_PI-08` 做 run1/run2 反向对照）；
> 2. 存量口径数字（开发侧 73 篇 vs 本链 117/89 篇）由开发与测试对齐后更新 `DEV_REPORT`；
> 3. 三条 P1/P2 全部关闭后，重新出具本报告的修订版，方可提交褚岩验收。
>
> **本报告所有判定均指向本验证链自产证据文件 + 执行时间戳；未引用开发自测结论作为任何一条 PASS/FAIL 的依据。**

---

## 附：证据与脚本索引

| 类别 | 文件 |
|---|---|
| 环境快照 | `evidence/PI-V1_env_snapshot.txt` |
| 用例1/3 | `evidence/PI-V2_case1_case3.txt`、`PI-V2_result.json`、`PI-V2_state.json`、`PI-V2_findings.md`、`evidence/raw/PI-01_*`、`PI-02_*`、`PI-03_*`、`PI-V2_replays.txt` |
| 用例4/5 | `evidence/PI-V3_case4_case5.txt`、`PI-V3_result.json`、`PI-V3_legacy_audit.json`、`PI-V3_legacy_docs.tsv`、`PI-V3_case4_ke_e2e.txt`、`evidence/raw/PI-04_*`、`PI-06_*`、`PI-07_*` |
| 用例2/6 | `evidence/PI-V4_case2_case6.txt`、`PI-V4_result.json`、`PI-V4_state.json`、`evidence/PI-V4_raw/*`、截图 `PI-V4_ui_default.png`/`_row.png`/`_indexing.png`/`_indexed.png` |
| curl 用例脚本 | `curl/case_PI-01_upload_default.sh`、`case_PI-02_search_pageindex.sh`、`case_PI-03_chat_pageindex.sh`、`case_PI-04_upload_embedding.sh`、`case_PI-06_reindex_legacy_embedding.sh`、`case_PI-07_legacy_emulated_no_index_type.sh`、`case_PI-08_mcp_search_knowledge.sh`、`case_PI-09_ui_chain_pageindex_search.sh`、`case_PI-10_ui_chain_pageindex_chat.sh`、`case_PI-11_ui_chain_embedding_control.sh` |
| 公共脚手架 | `curl/lib/kb_common.sh`、`curl/lib/db_probe.py`、`curl/lib/legacy_audit.py`、`curl/lib/strip_index_type.py`；命令索引 `curl/README.md` |
| 夹具 | `fixtures_pi/README.md`、`pi_default_doc.md`、`emb_regression_doc.md`、`legacy_no_index_type_doc.md` |
| BUG 台账 | `03-testing/BUGS.md` |
