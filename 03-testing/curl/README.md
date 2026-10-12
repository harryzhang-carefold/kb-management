# curl 命令索引 — PageIndex 检索（feat/pageindex 验收）

> 原则：一条用例 = 一条可重放的 curl 命令。复测是"重放 + 记录"，不重新发明命令。
> 复测时若入参未变，直接执行下方脚本；若入参/接口变了，更新原脚本并在头部注释留痕。

## 运行前置

```bash
# 取 token（测试账号见 03-testing/api_results.json 的 user 字段，密码 Test123456!）
# 脚本通过环境变量 TOKEN 读取，不要把生产凭据硬编码进脚本
export TOKEN=*** python get_token.py)
export KB_ID=***   # 含 pageindex 文档的 KB（api_results.json kb 字段）
```

## 命令索引表

| 用例 ID | 文件 | 接口 | 入参指纹（摘要） | 首次执行结果 | 最近一次执行结果 |
|---|---|---|---|---|---|
| TC-AC2 | `curl/case_ac2_search_pageindex.sh` | POST /knowledge-bases/{kb}/search | query=模型服务不可用时应该怎么排查？ mode=pageindex top_k=5 | 2026-10-10 PASS（HTTP 200, items=3, score=1.0） | 2026-10-10 10:45 重放 PASS（HTTP 200, items=3, 命中 doc 33010660, took_ms≈3000） |
| TC-AC3 | `curl/case_ac3_chat_pageindex.sh` | POST /knowledge-bases/{kb}/chat | question=队列积压超过多少条会触发告警？ retrieval_mode=pageindex | 2026-10-10 PASS（SSE 52 事件, 回答含"200 条…P2 级告警 [1]"） | 2026-10-10 10:50 重放 PASS（SSE meta→token×33→sources→done, 回答「200 条…P2 级告警 [1]」, sources 2 条） |
| TC-AC4 | `curl/case_ac4_regression.sh` | POST /knowledge-bases/{kb}/search | query=告警分级 mode=hybrid/vector/keyword top_k=5 | 2026-10-10 PASS（三值均 HTTP 200, code=0） | 2026-10-10 10:45 重放 PASS（三值均 HTTP 200 code=0, items=0 环境态） |
| TC-EDGE | `curl/case_edge_no_pi_index.sh` | POST /knowledge-bases/{kb}/search + /chat | query=星尘知识库是什么 mode/retrieval_mode=pageindex（KB 无 pageindex 文档） | 2026-10-10 PASS（search items=[]+message；chat SSE error+message） | 2026-10-10 10:48 重放 PASS（新建 KB d5c906a6 独立复测：同空+提示行为） |

## 说明

- `BASE_URL` 默认 `http://127.0.0.1:9012`，换环境用 `export BASE_URL=...` 覆盖。
- `KB_ID`：AC2/AC3/AC4 用含 pageindex 文档的 KB（`e7213e59-...`）；EDGE 用无 pageindex 文档的 KB（`ca3dedd7-...`）。
- AC4 本轮 `items=[]` 是因 embedding 端点 34.64.61.208:4000 不可达（外部环境态）——vector 按原逻辑退化为 keyword、KB 内无向量 chunk，返回空属原设计行为，非回归缺陷（见 TEST_REPORT §回归）。
- 每条脚本结尾 `-w '\nHTTP_CODE=%{http_code} TIME=%{time_total}s\n'` 便于复测直接对比状态码与耗时。

---

# VI-PI 批次 — 验证「上传默认索引方式 embedding → pageindex」（独立验证）

背景：改动卡 t_7f451c5f / commit 3dc1ddf（分支 `feat/default-pageindex`）。
本批由测试工程师独立验证，**不采信开发自测结论**；最终报告卡 t_474fa19f。
拆分链：t_fa5d836a（脚手架）→ t_32351222（用例 1+3）→ t_bbb32bcf（用例 4+5）→ t_2ba41218（用例 2+6）→ t_474fa19f（报告）。

## 公共脚手架（本批新增）

- `lib/kb_common.sh` — 供各 `case_PI-*.sh` 用 `source` 引入：
  - `BASE_URL` 默认 `http://127.0.0.1:9012`；`KB_USER`/`KB_PASS` 默认 `admin` / `Admin@123`
    （来源：仓库 `tests/e2e_test.py:26-27` 的测试账号，非生产密钥；可 export 覆盖）
  - `kb_login`（登录取 token，**只回显长度**）、`kb_post`、`kb_get`、`kb_multipart_post`（上传用）
- `lib/db_probe.py` — **只读** DB 探针（用 `backend/.venv/bin/python`，复用 `backend/app/core/database.py`；
  会话起始 `SET TRANSACTION READ ONLY`，不含任何写操作）：
  - `dist` — 全量文档 `meta.index_type` 分布（含 `pageindex_status`、doc status）
  - `doc <document_id>` — 单文档 meta 摘要（含 tree 结构统计，不回传整棵树）
  - `by-kb` — 按知识库聚合 pageindex / embedding / 无标记 计数
  - `legacy` — 列出"历史无 index_type"文档（兜底路径证据）
  - 可选 `--kb <kb_id>` / `--json` / `--limit N`

## 夹具（`../fixtures_pi/`，详见该目录 README）

| 夹具 | 唯一 token | sha256（前 12） | 用途 |
|---|---|---|---|
| `pi_default_doc.md` | `PI-TOKEN-7412`（正文段落内） | `11321dc6870f` | 默认上传（不传 index_type）应落 pageindex，树检索问答命中正文 |
| `emb_regression_doc.md` | `EMB-TOKEN-8251` | `ad8bc0fb9722` | 显式 `index_type=embedding` 回归，向量链路不受影响 |
| `legacy_no_index_type_doc.md` | `LEG-TOKEN-6390` | `c3257bbe446e` | 模拟历史无 index_type 文档，仍按 embedding 兜底 |

## 本批用例索引表（框架）

> 行由各**用例卡在首次执行时**填写并存档对应 `case_PI-*.sh`（SOUL：一条用例 = 一条可重放 curl 命令）。
> 本卡（t_fa5d836a）**只留框架，不建空壳脚本**。脚本名与下游卡 body 已对齐（PI-01…PI-08），
> 若某卡实际改名，以存档文件为准并在本表更新。

| 用例脚本 | 对应用例 | 接口 | 入参指纹（摘要） | 最近一次执行结果 |
|---|---|---|---|---|
| `curl/case_PI-01_upload_default.sh`（t_32351222） | 用例1 | POST /api/v1/knowledge-bases/{kb}/documents | **不传 index_type**；file=pi_default_doc.md（sha256 `11321dc6870f…`） | **2026-10-12 03:30–03:31 UTC PASS**（HTTP 200 + code=0；index_type=pageindex / pageindex_status=ok / node_count=3 / build_ms=64107；A1-A5/A7/A8 满足，A6 字面不满足但已证明无区分度，见 `evidence/PI-V2_result.json`） |
| `curl/case_PI-02_search_pageindex.sh`（t_32351222） | 用例3 | POST /api/v1/knowledge-bases/{kb}/search | query 命中 PI-TOKEN-7412；mode=pageindex；top_k=3 | **2026-10-12 03:31 UTC FAIL**（HTTP 200 但 total=0、items=[]，无条目含 PI-TOKEN-7412）；同参重放 4 次 1/4 命中，变体问法 5 条 3/5 命中 → 非确定性，见 findings PI-V2-F1 |
| `curl/case_PI-03_chat_pageindex.sh`（t_32351222） | 用例3 | POST /api/v1/knowledge-bases/{kb}/chat（SSE） | question 同上；retrieval_mode=pageindex；top_n=3 | **2026-10-12 03:32 UTC PASS**（SSE meta→token×50→sources→done，sources=1，答案含 PI-TOKEN-7412 并带 [1] 引用）；重放 2 次 sources=1/2 |
| `curl/case_PI-04_upload_embedding.sh`（t_bbb32bcf） | 用例4 | POST /api/v1/knowledge-bases/{kb}/documents | `-F index_type=embedding`（显式）；file=emb_regression_doc.md（`ad8bc0fb9722…`）；对照上传同文件 `index_type=pageindex` | **2026-10-12 03:39–03:40 UTC PASS**（10/10 断言：index_type=embedding / indexed / chunk_count=1 / 无 pageindex_tree / vector+hybrid 各 total=1 命中；对照页 total=1 建树 pageindex_status=ok node_count=2） |
| `curl/case_PI-06_reindex_legacy_embedding.sh`（t_bbb32bcf） | 用例5 | POST .../documents/{doc}/reindex + .../pageindex/rebuild | 存量 live 样本：embedding=99c37b1e（KB f380d232/E2E测试库）、pageindex=7b678d3f（KB 21f3f148/UI默认pageindex验证-031125） | **2026-10-12 03:44 UTC PASS**（10/10 断言：reindex 响应 index_type=embedding；pageindex/rebuild HTTP 400「不是 PageIndex 索引方式」；重建后 indexed/chunk_count=1/index_type 未改写；vector 命中；存量 pageindex 重建后 status=ok） |
| `curl/case_PI-07_legacy_emulated_no_index_type.sh`（t_bbb32bcf） | 用例5 | POST /documents + /search + lib/strip_index_type.py | **模拟用例**：自建 KB 上传后 DB 删 meta.index_type；file=legacy_no_index_type_doc.md（`c3257bbe446e…`）；query=LEG-TOKEN-6390 vector/hybrid | **2026-10-12 03:46 UTC PASS**（C1a–C7 共 10 条断言全 PASS：删键后 GET 原样无 index_type；reindex 响应 index_type=embedding；vector/hybrid 均命中；前端兜底 grep 3 处。C8 MCP 归第 4 段 NOT-RUN） |
| `curl/case_PI-08_mcp_search_knowledge.sh`（t_2ba41218） | 用例6 | MCP 9100 JSON-RPC `tools/call search_knowledge`（+ `tools/list` 根因取证） | query=`PI-TOKEN-7412`；kb_id 走变量（默认 VI-PI-4 自建 KB `22bcb345-…`）；`MODES="hybrid vector keyword"`；key 从 `infra/.env` 读、只回显长度 | **2026-10-12 04:01:51 UTC run1（KB 内只有 2 篇默认 pageindex 文档）→ CONFLICT**：hybrid/vector/keyword `total=0/0/0`。**04:08:00 UTC run2（同 KB 加 1 篇显式 embedding 副本 `9c8f8743-…`）→ total=2/2/1**，全部命中 embedding 副本且带 `doc_url`+`location`。`MODES=pageindex` 探针：`total=0, took_ms=0`，无 error（静默空结果）。`tools/list` 全响应 `pageindex` 出现 **0** 次。证据 `evidence/PI-V4_raw/PI-08_run*_console.txt`、`MCP_tools_list_console.txt` |
| `curl/case_PI-09_ui_chain_pageindex_search.sh`（t_2ba41218） | 用例2（A5 检索） | POST /api/v1/knowledge-bases/{kb}/search | query=`追溯本次巡检批次时应该用哪个口令定位日志？`；`mode=pageindex`；top_k=3；KB=`22bcb345-…`（文档来自**线上 UI 不点 radio 直传**）；`RUNS=3` | **2026-10-12 04:06:54–04:07:03 UTC FAIL（不稳定）**：3 次 total=`2/0/0` → 1/3 命中。观察项 `mode=hybrid` 同文档 `total=0`（已知 P1，不判 FAIL） |
| `curl/case_PI-10_ui_chain_pageindex_chat.sh`（t_2ba41218） | 用例2（A5 问答） | POST /api/v1/knowledge-bases/{kb}/chat（SSE） | question 同上；`retrieval_mode=pageindex`；top_n=3；`RUNS=3` | **2026-10-12 04:07:06–04:07:45 UTC FAIL（不稳定）**：3 次 sources=`0/2/0` → 1/3 命中；0 来源时发 `event:error`「未检索到相关 PageIndex 内容…」（KB 内确有 2 篇 pageindex_status=ok 文档，文案误导）。观察项：不传 `retrieval_mode`（默认 auto）→ `sources=2` 且 `metadata.leg=pageindex` |
| `curl/case_PI-11_ui_chain_embedding_control.sh`（t_2ba41218） | 用例6（反向对照） | POST /api/v1/knowledge-bases/{kb}/documents + GET .../documents/{doc} | **显式** `-F index_type=embedding`；file=`pi_default_doc.md`（同夹具同口令 `PI-TOKEN-7412`）；KB=`22bcb345-…` | **2026-10-12 04:07:51 UTC PASS**：doc=`9c8f8743-5409-413b-87af-567fab0cb7e0`，`index_type=embedding`，`indexed`，`chunk_count=2`，无 `pageindex_tree` |
| （无 curl 脚本） | 用例2 | 线上 UI（经 nginx）默认索引方式走查 | 前端 `KbDetailView` 默认 `indexType` + 线上端到端 | **2026-10-12 03:50–04:00 UTC 主体 PASS**：线上入口 200（实测入口 js `assets/index-BHI8vxe6.js`）；`KbDetailView-CcLfGsq-.js` 内 `V=o(\`pageindex\`)`/`me=c(()=>({index_type:V.value}))`；DOM `PageIndex（树索引）` `is-active=true`+`input.checked=true`、`Embedding` 均 false；`.upload-options-desc` 可见且前缀一致；**不点任何 radio** 直传 → FormData=`[["index_type","pageindex"],["file","<file:pi_default_doc.md>"]]`、`radioClicks=0`；列表行 `PageIndex / 建树中 → 已建树/已索引`，`meta.index_type=pageindex`、`pageindex_status=ok`、`chunk_count=0`、`node_count=3`、`build_ms=34212`。截图 `evidence/PI-V4_ui_{default,row,indexing,indexed}.png` |

### t_32351222 段（用例1+3）执行备注

- 自建测试 KB：`32b1101f-efd6-467c-900a-255c75656791`（名 `验证-默认pageindex-VI-PI-2-032953`，2026-10-12T03:29:53Z 建）。
- 文档：`034cc16f-d230-4fca-beb1-04da2337cc2d`（pi_default_doc.md，sha256 `11321dc6870f…`），102s 内 indexed。
- 首执全文：`evidence/PI-V2_case1_case3.txt`；重放记录：`evidence/raw/PI-V2_replays.txt`；
  结构化断言：`evidence/PI-V2_result.json`；状态：`evidence/PI-V2_state.json`。
- **观察项**：同一文档不传 `retrieval_mode`（走 schema 默认 auto）→ `sources=0` + meta.notice 提示，
  与开发自测口径（DEV_REPORT §5 P1：sources=0）**一致**；属已上报的既有 P1 产品决策错配（决策卡 t_9013e8b2），非本次回归。

### t_bbb32bcf 段（用例4+5）执行备注

- **用例4**（embedding 回归，自建 KB）：`13d9130b-5d7c-4421-a217-e28267076d91`
  （名 `验证-回归-embedding-VI-PI-3-033943`）；文档 `ea40d0c5…`（emb_regression_doc.md，显式 embedding）
  与对照 `edd5c93e…`（同文件，显式 pageindex）。10/10 断言 PASS。
- **用例5 步骤4**（存量只读审计）：`lib/legacy_audit.py`（**只读**，会话起始 SET TRANSACTION READ ONLY）
  → `evidence/PI-V3_legacy_audit.json` + `PI-V3_legacy_docs.tsv`。口径：全量 `is_deleted=false` 文档 117 篇，
  其中 uploaded_at ≤ 2026-10-12T03:16:05Z（commit 3dc1ddf）的"存量" 89 篇、严格改动前（<02:40Z）55 篇。
  存量 index_type 分布 `{embedding:60, pageindex:29}`；**无任何 embedding 文档带 pageindex_tree**、
  **无非法 index_type**、存量 embedding indexed 文档 chunk_count 均 >0（A1–A4 PASS）。
- **用例5 步骤5**（存量真实文档重建索引）：embedding 样本 `99c37b1e…`（KB `f380d232…`/E2E测试库）、
  pageindex 样本 `7b678d3f…`（KB `21f3f148…`/UI默认pageindex验证-031125，二者 KB 均未软删）。8/8 PASS。
  首轮曾误选 `e1c52f26…`(regress-kb-regress_972a19) 的 r3_third.md，该 KB **已 is_deleted=true** →
  reindex 返回 404「知识库不存在」；已把 `kb_deleted` 纳入审计口径（73/117 篇存量文档位于已软删 KB 内，
  行为性回归只能覆盖 live 子集 44 篇）。首轮原始输出保留在 `evidence/PI-V3_case6_run1.txt`，
  `evidence/raw/PI-06_pi_poll_6..38.json` 为该轮 404 残留（run2 覆盖了 1–5）。
- **用例5 步骤6**（模拟无 index_type 老文档）：`case_PI-07` 自建 KB `52d96f8c…` + 文档 `08aca631…`；
  用 `lib/strip_index_type.py`（**本段唯一写库动作**，仅删该文档 meta.index_type 一个键）复现老文档形态。
  C1a–C7（10 条）PASS，C8（MCP）NOT-RUN 归第 4 段。
- ⚠ **环境提示（给后续卡）**：本段 `case_PI-07` 执行 2 次，在**自建** KB
  `验证-兜底-legacy-VI-PI-3-034602 / -034620` 内留下 **2 篇 meta 无 index_type 的文档**
  （`214a9b3e…` / `08aca631…`）。真实存量原本 0 篇（`db_probe legacy` = 0 行）；
  后续任何"存量无 index_type"断言请用 `legacy_audit.py` 的
  `assertions.A5_no_real_legacy_docs`（其中 `其它=0`）口径，勿把这 2 篇当存量真实数据。
- **观察项 OBS-REINDEX-CHUNK-DUP（P2，非本卡判定依据）**：embedding 文档 reindex 不清理旧分块 →
  PG `chunk` 行与 ES 文档重复堆积（实测 1→2→3 行，`doc.chunk_count` 恒为 1，
  同查询 vector 检索 total 同步 1→2→3 且返回内容/score 完全相同的重复条目）。
  代码位置 `workers/tasks.py` `chunk_index_task`（只 add 不 delete）+ `api/documents.py` reindex 无清理步骤；
  属改动卡 `t_7f451c5f` 之前的既有行为，建议单独立卡修。
- 证据：`evidence/PI-V3_case4_case5.txt`（原始输出合集）、`evidence/PI-V3_result.json`（36 条断言）、
  `evidence/raw/PI-04_*`、`PI-06_*`、`PI-07_*`；KE 回归对照 `tests/e2e_test.py` 8/8 通过
  （`evidence/PI-V3_case4_ke_e2e.txt`；任务书建议的 pytest 形式不适用——该文件是 `__main__` 脚本）。

### t_2ba41218 段（用例2+6）执行备注

- 自建 KB：`22bcb345-8326-479c-958b-51daa2905715`（名 `验证-默认pageindex-VI-PI-4-20261012-035005`，03:50:06Z 建）。
  内部 3 篇文档：`30691711-…`（UI 直传，03:52:16）/ `dd083cf9-…`（UI 直传，04:00:41，用于抓建树中截图）
  两篇 `index_type=pageindex`、`chunk_count=0`、`pageindex_status=ok`；`9c8f8743-…`（curl 显式 embedding，反向对照，`chunk_count=2`）。
  另有诊断 KB `4d43c2ef-…`（单文档，API 默认上传）。状态与时间线全文见 `evidence/PI-V4_state.json`。
- **鉴权路线**：线上页面未登录会跳 `/login`；本段走「本地 API 签发 token（测试账号 `admin`）→ 注入
  `localStorage.kb_token` → 直接进 `/kb/<kb_id>`」，**未走表单登录**。token 只记长度（209），未落盘到 evidence。
- **UI 上传手法**：全程**不点任何 radio**，用 CDP `DOM.setFileInputFiles` 直塞 `.el-upload input[type=file]`；
  同时挂钩 `FormData.prototype.append` + `XMLHttpRequest` 记录实际请求体与响应，
  实测两次上传的 FormData 均为 `[["index_type","pageindex"],["file","<file:pi_default_doc.md>"]]`、`__radioClicks=0`。
- **线上产物与开发文档不一致（文档滞后，非缺陷）**：开发文档（改动卡 t_7f451c5f / body）称线上入口为
  `assets/index-CaTnCPvY.js`；本段实测为 **`assets/index-BHI8vxe6.js`**，`KbDetailView-CcLfGsq-.js`
  （sha256 `c4c9ff349fd02ec4f7c81f0151f2a2ae97f49c43a33b56ac565f4fb42b538f53`）。原因是 `3dc1ddf` 之后
  自动检索卡 `5856436` 又重建过一次前端 dist。默认 pageindex 的字符串证据仍在（见上表用例2行）。
- 🔴 **NEW-FINDING-V4-1（P1，需产品/开发定级）：pageindex 检索/问答间歇性 0 命中（约 1/3），静默空结果无重试**
  - 现象：同 KB、同 query、同参数连续跑，`mode=pageindex` 检索 `total` 会在 2 与 0 之间跳；问答同步 `sources=0`
    并发 SSE `event:error`，文案「未检索到相关 PageIndex 内容，请换一种问法或确认已上传 PageIndex 索引的文档。」
    —— 而该 KB 里确有 2 篇 `pageindex_status=ok` 的文档，**文案误导**。
  - 可复现命令：`bash 03-testing/curl/case_PI-09_ui_chain_pageindex_search.sh`（`RUNS=3`，观察 3 次 total）
    与 `bash 03-testing/curl/case_PI-10_ui_chain_pageindex_chat.sh`。
  - 隔离实验（`evidence/PI-V4_raw/DIAG3_console.txt`）：单文档 KB 3/3 命中；本 KB（2 篇重复文档）2/3；
    **第 2 段对照 KB `32b1101f-…` 1/3** —— 即**非本 KB 特有、非重复文档特有**，pageindex 引擎本身不稳定。
    本段合计 12 次观测中 5 次 0 命中（≈42%）。
  - 机制旁证：0 命中的 run `took_ms` 只有 2–3s（命中 run 3–20s），返回体 `{code:0,total:0}` 既无 `message`
    也无 `error` —— 即 `pageindex_engine.retrieve()` 的选节点 LLM 返回了空/不可解析结果后**静默返回空**，
    代码里没有重试也没有兜底（`pageindex_engine.py` retrieve 无 retry；仅 build 阶段有「带错误信息重试一次」）。
    与 `3dc1ddf` 提交说明里「RETRIEVE_MAX_TOKENS 1024→8192 修 1/6 空结果」属同一缺陷类，**放大预算后仍可复现**。
  - 影响面被改动放大：`3dc1ddf` 让 pageindex 成为**默认上传方式**，`5856436` 又让默认检索走 auto→pageindex 腿，
    于是「默认上传 + 默认检索」链路继承了这条 ~1/3 的空结果率。
- 🟠 **NEW-FINDING-V4-2（P1，用例6 判定依据）：默认上传的 pageindex 文档在 MCP 引用链路上完全不可检索**
  - 主证据：`case_PI-08` run1（KB 内只有 2 篇默认 pageindex 文档）→ hybrid/vector/keyword `total=0/0/0`；
    `MODES=pageindex` 探针 → `total=0, took_ms=0`（静默接受但无分支）。
  - 反向对照（必做项，已做）：同 KB 加 1 篇**显式 embedding**、**同夹具同口令**的文档后，同一脚本同一 query
    → `total=2/2/1`，全部命中 `9c8f8743-…` 且带 `doc_url` + `location`。
    ⇒ 脚本有效；差异只能归因于索引方式。两篇默认 pageindex 文档在 12 次返回中 **0 次**出现。
  - 根因：后端 `mcp_server.py` `search_knowledge` 只把 mode 透传给 `es_client.hybrid_search`
    （仅 hybrid/vector/keyword 分支），**没有 pageindex 分支**；`tools/list` 全响应里 `pageindex` 出现 **0 次**。
    pageindex 文档不写 ES 分块（`chunk_count=0`），因此 ES 侧永远检索不到。
  - 与 P1 决策卡 `t_9013e8b2` 的关系：**同源**（都是「默认上传方式变了、其他链路没跟上」），
    **但发生面不同** —— `t_9013e8b2` 是站内默认检索/问答 0 来源；本项是**智能助手（carefold-agent → kb MCP）**
    引用链路的检索面。本段实测站内默认链路（auto）已能给出 `sources=2`（`leg=pageindex`），
    而 MCP 侧恒为 0 ⇒ **两个面不能互相覆盖**，需产品/开发确认是否并入同卡。
    建议：本项单独立卡（P1），至少要在 MCP 侧「显式拒绝 pageindex 文档」或「补 pageindex 分支」二选一，
    不要让工具静默返回 0 条（会让智能助手在本应命中的问题上给出"没有资料"的结论）。
- ⚪ **观察项（不判 FAIL）**：`case_PI-09` / `case_PI-10` 的 `mode=hybrid`（及不传 mode 的默认 auto）在本 KB 上
  可返回来源（默认 auto `sources=2`），说明第 2 段记录过的「默认问答 0 来源」P1（`t_9013e8b2`）
  在 `5856436` 之后已被 auto 路由**正面覆盖**；本段未复现 0 来源。
- 证据：`evidence/PI-V4_case2_case6.txt`（原始输出汇编）、`evidence/PI-V4_result.json`（逐条断言：
  用例2 = PARTIAL，用例6 = CONFLICT）、`evidence/PI-V4_raw/`（全部 raw + `DIAG*` + `FINAL_*`）。

## 本批记录要求

- 每条 curl 首次执行后：脚本头部写清 用例 ID / 接口 / 入参 / 首次执行时间与结果，并回填上表。
- 复测：入参未变**重放原脚本**，只在报告里追加"时间 + 文件名 + HTTP 码 + PASS/FAIL + 与首次差异"，
  不重新生成命令；入参变了则改原脚本并留变更记录。
- token 一律只记长度，不落盘、不进报告。

---

# AUTO-RETRIEVAL 批次 — 验证「检索/问答默认模式 auto（智能）」（独立验证）

背景：PRD `01-product/PRD-AUTO-RETRIEVAL.md`（AC1–AC11）；实现提交 `5856436`（分支 `feat/default-pageindex`，
HEAD `078a65c` 为其后仅文档提交）。本批由测试工程师独立验证，**不采信开发自测结论**；
最终报告卡 `t_5b376ec9` → `03-testing/TEST_REPORT_AUTO_RETRIEVAL.md`。
拆分链：`t_6cd18e09`（环境/夹具/脚手架）→ `t_4f8b6297`（AC1–AC5 HTTP 主链路）→
`t_94a34185`（AC6–AC8 文案/空库/index-stats 契约）→ `t_4acb1aca`（AC9 MCP + 附加回归）→
`t_5537d8aa`（AC10–AC11 线上浏览器）→ `t_5b376ec9`（汇总报告）。

## 本批复用的脚手架

- `lib/kb_common.sh`、`lib/db_probe.py` 沿用 VI-PI 批次（见上节）；`BASE_URL` 默认 `http://127.0.0.1:9012`。
- **本批新增** `lib/sse_parse.py`（t_4f8b6297）：解析 `/chat` SSE 流 → event 计数 / meta / `sources` 数 / 答案全文 / `notice` / `error`
  事件 / `--needle` 断言，供各 case 脚本直接消费（避免用 shell grep 拼 JSON）。
- **本批新增（t_94a34185，AC6–AC8 段）**：
  - `lib/msg_check.py` — F6 文案**逐字比对器**：内嵌 literal（复制自 PRD §5）↔ `01-product/PRODUCT_DECISIONS.md` ↔ `docs/api.md`
    三方 `==`，并打印 **PRD 原文行号**（`--key msg1..msg5 --actual-file <文件>`）。
  - `lib/db_composition.py` — KB 索引构成**只读独立聚合**（逐文档在 Python 里自己数，**不调用被测** `kb_index_composition()`）。
  - `lib/db_rowcounts.py` — 全库行数**只读**快照（只打印计数，AC8 只读证据）。
  - `lib/index_stats_check.py` — AC8 对账器（三字段 ↔ DB 独立聚合 + `docs/api.md` 口径谓词对齐）。
  - `lib/chat_notice_stub.py` 与 `case_AR-205_degraded_stub.py` — **进程内桩**（TestClient + 真实 Bearer token）：
    分别验证 chat `meta.notice` 承载通道（msg2/msg4）与 pageindex 腿降级的 search `degraded` + chat `notice`（msg5）。
- 环境基线快照：`../evidence/AUTO-RETRIEVAL/00_env_snapshot.md`（commit / 进程 / health / dist md5 / 4 夹具构成）。
- 端口：后端直连 `:9012`，MCP `:9100`；日志 `05-temp/backend_9012.log`、`05-temp/mcp_9100.log`。

## 本批夹具（沿用 `t_efead8b4` 交付，2026-10-12 03:45 UTC 复核，**未重建**）

| 夹具 | kb_id | 构成（emb/pi） | 文档（口令） |
|---|---|---|---|
| `kb_pi` | `665c922d-1760-4fe8-9a4f-3f19ccd622b9` | 0 / 1 | `281598b0-…`（星火-7315） |
| `kb_mix` | `e46ea8f2-c86d-4238-b0d1-ec95594a5f72` | 1 / 1 | `b4193756-…`（C4Q8）+ `ef391719-…`（P9M3-靛蓝） |
| `kb_emb` | `2f28d3dc-0a15-46a2-a952-5c466c1ed965` | 1 / 0 | `4c4f9041-…`（C4Q8） |
| `kb_empty` | `75b017b6-cbc1-4958-bc8c-bef2ec3b700a` | 0 / 0（**务必保留**，AC7 用） | — |

### 本卡（`t_4f8b6297`）新建的 AC1 独立复现 KB（**需保留至 AR-V6 完成**）

| slug | kb_id | 构成（emb/pi） | 文档 | 说明 |
|---|---|---|---|---|
| `ac1_run1` | `82725483-04af-417f-aff1-d6f310b10620` | 0 / 1 | `7cdd1b12-…`（星火-7315） | AC1 第 1 轮（默认上传 + 默认提问） |
| `ac1_run2_wiretrace` | `dc501b69-0bf7-4440-9273-edbfac9a7569` | 0 / 1 | `293cfa05-…`（星火-7315） | AC1 第 2 轮，附 `--trace-ascii` 线上 multipart 抓包（字段仅 `file`） |

> 另：自跑 `tests/e2e_test.py`（AC2 附加回归点）会由套件自身建 "E2E测试库" 并显式 `index_type=embedding` 上传，属套件既有行为。

## 本批用例索引表（框架）

> 行由各**用例卡在首次执行时**填写并存档对应 `case_AR-*.sh`（SOUL：一条用例 = 一条可重放 curl 命令）。
> 下表 AR-V1 段已由 `t_6cd18e09` 填实；下游卡脚本名为**占位约定**，实操以存档文件名为准并回填本表。

| 用例脚本 | 对应用例 | 接口 | 入参指纹（摘要） | 最近一次执行结果 |
|---|---|---|---|---|
| `curl/case_AR-V1-00_health.sh`（t_6cd18e09） | 环境基线 | GET /api/v1/health | 无（无需鉴权） | **2026-10-12 03:45 UTC** HTTP 200 code=0 `degraded`（仅 mineru unreachable）；`evidence/AUTO-RETRIEVAL/raw/case_AR-V1-00_health.out` |
| `curl/case_AR-V1-IS-01..04_kb_{pi,mix,emb,empty}.sh`（t_6cd18e09） | 夹具复核·索引构成 | GET /api/v1/knowledge-bases/{kb_id}/index-stats | 4 个夹具 KB id（kb id 走变量，默认夹具值） | **2026-10-12 03:45 UTC** 4/4 HTTP 200，code=0：0/1/1、1/1/2、1/0/1、0/0/0（与交付一致） |
| `curl/case_AR-V1-DOC-01..04_kb_{pi,mix,emb,empty}.sh`（t_6cd18e09） | 夹具复核·文档清单 | GET /api/v1/knowledge-bases/{kb_id}/documents | 同上 + `page=1&page_size=20` | **2026-10-12 03:45 UTC** 4/4 HTTP 200：total=1/2/1/0；doc `meta.index_type`/`pageindex_status`/`chunk_count` 与 DB 探针一致 |
| `curl/case_AR-101_default_chain.sh`（t_4f8b6297） | AC1 默认链路复现缺陷已修 | POST .../documents（**不传 index_type**）+ 轮询 + POST .../chat（**不传 retrieval_mode**） | 新建 KB `auto验收-AC1-default-*`；file=`05-temp/t_efead8b4_doc_pi_ac1.md`（sha256 `c76e7fb08b60…`，口令 `星火-7315`）；question=`本知识库的验收口令是什么？` top_n=5。`TRACE=1` 追加线上 multipart 抓包 | **2026-10-12 03:51:55–03:53:35 UTC PASS**（两轮独立复现：kb `82725483-…` sources=1 / kb `dc501b69-…` sources=2，答案均含 `星火-7315`；wire-trace 字段仅 `name="file"`，`index_type` 出现 0 次） |
| `curl/case_AR-102a_pi_chat_pageindex.sh`（t_4f8b6297） | AC2 前半 显式 pageindex 问答回归 | POST .../chat（SSE） | kb_pi=`665c922d-…`；`retrieval_mode=pageindex` top_n=5；question 同上 | **2026-10-12 03:49:52 UTC PASS**（HTTP 200, sources=2, 答案含 `星火-7315`, 无 error/notice, TIME=4.837s） |
| `curl/case_AR-102b_emb_search_hybrid.sh`（t_4f8b6297） | AC2 后半 显式 hybrid 检索回归 | POST .../search | kb_emb=`2f28d3dc-…`；`mode=hybrid` top_k=5；query=`部署组件` | **2026-10-12 03:49:55 UTC PASS**（HTTP 200, total=1, doc `4c4f9041`(t_efead8b4_doc_emb.md), match_type=hybrid, score=0.032787, took_ms=13） |
| `curl/case_AR-103_kbemb_auto_vs_hybrid.sh`（t_4f8b6297） | AC3 纯 embedding 库零变化 | POST .../search ×2 + 9012 日志 grep | kb_emb；query=`部署组件` top_k=5；`mode=auto` 与 `mode=hybrid` 各一 | **2026-10-12 03:50:29 UTC PASS**（items 逐条全等 chunk `fb164d7b`/0.032787/hybrid，diff 0 字节；日志 `auto_route=es`, composition 1/0, took_ms=40；pageindex 腿调用标记 0 行） |
| `curl/case_AR-104_mix_auto_federated.sh`（t_4f8b6297） | AC4 混合库不漏检 | POST .../search（+ 1 观察查询）+ 日志 grep | kb_mix=`e46ea8f2-…`；主 query=`验收口令` `mode=auto` top_k=5；观察 query=`部署组件` | **2026-10-12 03:51:51 UTC PASS**（total=4：emb doc `b4193756` 1 条 + pi doc `ef391719` 3 条；`leg={es,pageindex}`；日志 `auto_route=both` took_ms=4842）。观察项 `部署组件`：`auto_route=both` 但 pi 腿 0 命中（相关性，非漏检） |
| `curl/case_AR-105_redline_pageindex.sh`（t_4f8b6297） | AC5 红线回归 | POST .../search | kb_emb；`mode=pageindex` top_k=5；query=`部署组件` | **2026-10-12 03:49:55 UTC PASS**（HTTP 200, `total=0`, `items=[]`, `leg=es` 条数 0，message=既有原文「该知识库下没有使用 PageIndex 索引的文档…」） |
| `curl/case_AR-201_ac6_msg1_no_doc.sh`（t_94a34185） | AC6 文案① + **AC7 空库** | POST .../search（mode=auto）+ POST .../chat（SSE，默认 auto） | kb_empty=`75b017b6-…`；query/question=`本知识库的验收口令是什么？`；search `{"mode":"auto","top_k":10}`，chat `{"top_n":5}`（**不传 retrieval_mode**） | **2026-10-12 04:02–04:03 UTC PASS**（search total=0 items=[] + message 逐字；chat `meta.notice` 逐字 + errors=0；答案 85 字含拒答标记、无夹具口令泄漏） |
| `curl/case_AR-202_ac6_msg2_es_empty.sh`（t_94a34185） | AC6 文案② | POST .../search（+filters）+ POST .../chat（SSE） | kb_emb=`2f28d3dc-…`；search `{"query":"系统部署需要哪些基础设施组件？","mode":"auto","top_k":10,"filters":{"file_type":"pdf"}}`；chat 无关 query（**承载通道桩**） | **2026-10-12 04:01 UTC PASS**（search total=0 + message 逐字；chat 桩验证 `meta.notice` 逐字、errors=0） |
| `curl/case_AR-203_ac6_msg3_pageindex_empty.sh`（t_94a34185） | AC6 文案③ | POST .../search（mode=auto）+ POST .../chat（SSE） | kb_pi=`665c922d-…`；query/question=`量子纠缠在超导电路中的退相干时间如何测量？`（与库内文档无关 → 树索引 0 命中） | **2026-10-12 04:01 UTC PASS**（search total=0 + message 逐字；chat **真实触发** `meta.notice` 逐字、errors=0） |
| `curl/case_AR-204_ac6_msg4_both_empty.sh`（t_94a34185） | AC6 文案④ | POST .../search（+filters）+ POST .../chat（SSE） | kb_mix=`e46ea8f2-…`；search 无关 query + `filters={"file_type":"pdf"}`（两腿同时置空）；chat 无关 query（**承载通道桩**） | **2026-10-12 04:01 UTC PASS**（search total=0 + message 逐字；chat 桩验证 `meta.notice` 逐字、errors=0） |
| `curl/case_AR-205_ac6_msg5_pageindex_degraded.sh`（t_94a34185） | AC6 文案⑤ | POST .../search + .../chat（SSE），**进程内桩** pageindex 腿 | kb_mix；query=`系统部署需要哪些基础设施组件？`；桩 `pageindex_engine.retrieve → ([],7,{"error":...})` | **2026-10-12 04:02 UTC PASS**（search `degraded=["pageindex"]` + message 逐字 + total=1（ES 腿未丢）；chat `meta.notice` 逐字 + errors=0） |
| `curl/case_AR-206_ac8_index_stats_contract.sh`（t_94a34185） | AC8 接口契约 | GET .../{kb}/index-stats ×4 + 不存在 id + GET /openapi.json + `lib/db_composition.py` / `db_rowcounts.py` | 4 夹具 KB id；absent id=`11111111-1111-1111-1111-111111111111` | **2026-10-12 04:02 UTC PASS**（4 KB 三字段 == DB 独立聚合（0/1/1、1/1/2、1/0/1、0/0/0）；absent → 404 code=40401；OpenAPI 两者 default=auto + pattern 逐字；只读：行数快照一致 + 日志窗口 0 条写语句） |
| `curl/case_AR-301_mcp_tools_list.sh`（t_4acb1aca） | AC9-1 MCP 工具清单未受影响 | POST MCP `:9100/mcp` JSON-RPC `tools/list` | 无业务入参；`MCP-Session-Id: ar301-<tag>`；key 从 `infra/.env` 的 `KB_MCP_API_KEY` 读、不打印 | **2026-10-12 04:07:49Z / 04:11:46Z 重跑 PASS**（HTTP 200，6 工具；`search_knowledge.inputSchema.properties.mode={default:"hybrid",type:"string"}`（enum 缺省）；描述行逐字「mode: 检索模式: hybrid(混合) / vector(纯向量) / keyword(纯关键词)，默认 hybrid」；描述+schema+整包 `auto`=0、`智能`=0） |
| `curl/case_AR-302_mcp_call_no_mode.sh`（t_4acb1aca） | AC9-2 不传 mode 与直连 hybrid 一致 | POST MCP `tools/call search_knowledge`（**不传 mode**）+ POST `$BASE_URL/.../search`（`mode=hybrid`） | kb_mix=`e46ea8f2-…`；query=`部署组件`；top_k=5 | **2026-10-12 04:09:04Z / 04:11:15Z 重放 PASS**（MCP HTTP 200，回显 `mode:"hybrid"`，items=1 `b4193756#0`；直连 HTTP 200 items=1 同 chunk；集合 diff=0；content 流 sha256 两侧同为 `93e078c7…`；非空守卫 PASS） |
| `curl/case_AR-303_mcp_no_auth.sh`（t_4acb1aca） | AC9-3 MCP 鉴权未退化 | POST MCP `:9100/mcp`（三种鉴权形态） | ①无 Authorization ②错误 key ③正确 key | **2026-10-12 04:09:16Z / 04:11:15Z 重放 PASS**（401 / 401 / 200 对照；401 体 `{"error":"unauthorized"}`） |
| `curl/case_AR-304_upload_default_pageindex.sh`（t_4acb1aca） | 附加回归 上传默认值仍 pageindex | POST .../documents（**不传 index_type**）+ 轮询 + GET .../index-stats + GET /openapi.json + `lib/db_probe.py doc` | 新建 KB `auto验收-AR4-upload-default-*`；file=`05-temp/ar4_upload_default_<epoch>.md`（口令 `AR4-DEFAULT-<epoch>`） | **2026-10-12 04:09:58Z PASS**（OpenAPI 上传 `index_type.default=pageindex`；接口 `meta.index_type=pageindex`；DB 探针 `index_type=pageindex`、树 4 节点；index-stats 0/1；status=indexed；用后 DELETE doc/kb 各 200、GET kb 404） |
| `curl/case_AR-305_crosskb_auto_isolation.sh`（t_4acb1aca） | 附加回归 跨 KB 隔离不回退（BUG-01） | POST .../search（`mode=auto` / `hybrid`）+ `lib/db_probe.py doc` | ES 腿：kb_emb+`C4Q8`（对照 kb_mix+hybrid+`C4Q8`）；pi 腿：kb_pi+`P9M3-靛蓝`（对照 kb_mix+auto；本库探针 kb_pi+`星火-7315`）；top_k=5 | **2026-10-12 04:10:29Z / 04:11:27Z 重放 PASS**（kb_emb+auto：items=1 全属本库 foreign=0，对照命中别库 `b4193756`；kb_pi+auto：foreign=0，对照命中别库 `ef391719`；本库命中 >0 且 foreign=0；DB 归属核对不匹配=0） |
| `curl/case_AR-306_document_state_unchanged.sh`（t_4acb1aca） | 附加回归 document 状态不受影响 | GET .../{kb}/documents + GET .../{kb}/index-stats（对照 AR-V1 03:45Z 基线 raw） | 4 夹具 KB id；对比字段 id/status/updated_at/chunk_count/version/meta.index_type/indexed_at | **2026-10-12 04:10:49Z / 04:11:28Z 重放 PASS**（4 KB 文档级 diff=0 行、index-stats 0/1/1、1/1/2、1/0/1、0/0/0 全部与基线逐字一致；`kb_empty` 文档级为空对空，不作独立有效证据） |
| （无 curl 脚本）`case_AR-V5-10_*`（t_5537d8aa，占位） | AC10 前端默认选中 | 浏览器（签 token 注入 localStorage）+ DOM/网络抓取 | 问答页/检索页默认「智能（推荐）」；0 命中灰色提示条 | 待填写 |
| （无 curl 脚本）`case_AR-V5-11_*`（t_5537d8aa，占位） | AC11 线上验证 | `https://agent.carefold.ai/kb-management/` 端到端 | 默认选中「智能」+ 默认链路提问有来源 | 待填写 |

### t_4acb1aca 段（AC9 + 附加回归）执行备注

- **新增脚本 6 个 + 重放脚本 1 个**，全部 `chmod +x`、`bash <file>` 可直接重放：
  `case_AR-301_mcp_tools_list.sh`、`case_AR-302_mcp_call_no_mode.sh`、`case_AR-303_mcp_no_auth.sh`、
  `case_AR-304_upload_default_pageindex.sh`、`case_AR-305_crosskb_auto_isolation.sh`、
  `case_AR-306_document_state_unchanged.sh`；重放驱动 `05-temp/t_4acb1aca_replay.sh`。
- **`tests/e2e_test.py` 全绿**（附加回归点）：`backend/.venv/bin/python tests/e2e_test.py` → exit=0，**8/8 步通过**
  （04:09:24Z 结束）；第 4 步仍为 `explicit index_type=embedding`，`tests/` 工作区改动 **0 行**（只跑不改）。
  套件自建 KB `e6f73cbf-…`（`E2E测试库`）+ doc `b73515f6-…`，按仓库既有行为保留。
  原始输出 `evidence/AUTO-RETRIEVAL/raw/t_4acb1aca_e2e_test.out`。
- **重放**：`bash 05-temp/t_4acb1aca_replay.sh` → AR-301/302/303/305/306 **5/5 exit=0 PASS**（入参未变，
  直接重放已存档命令，未重新生成）；日志 `evidence/AUTO-RETRIEVAL/raw/t_4acb1aca_replay.log`。
  AR-304 未重放（会新建并清理 KB）。
- **AR-304 自建数据已清理**：KB `0bdda453-…` + doc `b9d66ff8-…` → DELETE doc 200 / DELETE kb 200 / 清理后 GET kb 404；
  id 记录 `05-temp/ar4_created_ids.txt`。四个夹具库（含 `kb_empty`）**全部保留**。
- **静态佐证**：`git show --stat 5856436` 变更集不含 `backend/mcp_server.py`（出现 0 次）；
  其最后改动 `e756b7a`（01:45Z）为该提交祖先。原始 `evidence/AUTO-RETRIEVAL/raw/t_4acb1aca_git_static_evidence.txt`。
- 分条证据与判定：`evidence/AUTO-RETRIEVAL/AC9_regression.md` / `.json`（整体 PASS/FAIL 在 AR-V6 `t_5b376ec9`）。

## 本批记录要求

- 与上批相同：首次执行即存档 `case_AR-*.sh`（头部注释含用例 ID/接口/入参/首次执行时间与结果、末尾 `-w` 输出 HTTP 码与耗时、`chmod +x`）。
- 复测：入参未变**重放原脚本**，只追加"时间 + 文件名 + HTTP 码 + 结果 + 与首次差异"。
- 本批另有环境基线：`../evidence/AUTO-RETRIEVAL/00_env_snapshot.md`（AR-V1 产出，后续卡直接引用，不重复采集）。
