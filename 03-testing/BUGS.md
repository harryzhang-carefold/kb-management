# BUGS — 缺陷与观察项台账

> 记录规则：每条含 现象 / 复现步骤（可直接重放的命令或脚本绝对相对路径）/ 预期 / 实际 / 严重程度 / 证据。
> 接口类问题一律引用 `03-testing/curl/case_*.sh`，让开发能一条命令复现。

---

## BUG-V4-01 — pageindex 检索/问答间歇性 0 命中（≈1/3），静默空结果、无重试、错误文案误导

- **发现卡**：`t_2ba41218`（VI-PI-4，用例2 A5 子项）
- **发现时间**：2026-10-12T04:02Z 起；04:06–04:08Z 完成隔离实验
- **严重程度**：**P1**（建议产品/开发定级）
- **影响面**：`3dc1ddf` 让 pageindex 成为**默认上传方式**、`5856436` 让默认检索走 `auto → pageindex` 腿，
  因此"默认上传 + 默认检索/问答"链路继承了这条空结果率。用户会看到"问什么都答没资料"。

### 现象
同一 KB、同一 query、同一参数连续调用 `mode=pageindex`：
- 检索 `POST /api/v1/knowledge-bases/{kb}/search` 的 `data.total` 在 `2` 与 `0` 之间跳；
- 问答 `POST /api/v1/knowledge-bases/{kb}/chat`（`retrieval_mode=pageindex`）`sources` 同步为 `0`，
  并发 `event: error`，文案：
  `未检索到相关 PageIndex 内容，请换一种问法或确认已上传 PageIndex 索引的文档。`
  —— **而该 KB 里确有 2 篇 `index_type=pageindex`、`pageindex_status=ok` 的文档，文案误导**。

### 复现步骤
```bash
cd /home/harry.zhang/kb-management
# 检索侧：主查询 ×3，观察 3 次 total
bash 03-testing/curl/case_PI-09_ui_chain_pageindex_search.sh
# 问答侧：主查询 ×3，观察 3 次 sources
bash 03-testing/curl/case_PI-10_ui_chain_pageindex_chat.sh
# 隔离实验（单文档 KB / 本 KB / 第 2 段对照 KB 各 3 次）——脚本在 05-temp（诊断用，非交付）
bash 05-temp/t_2ba41218_diag3.sh
```
默认 KB 为 `22bcb345-8326-479c-958b-51daa2905715`（本段自建），可用 `KB_ID=` 覆盖。

### 预期
同参数重复调用应稳定命中（`total >= 1` / `sources >= 1`）。这是**检索功能**，不是抽样统计：
同一份文档、同一个问题，不应有时答得出、有时答"没有资料"。

### 实际（本次实测）
| 对象 | 3 次 `total`/`sources` | 命中率 |
|---|---|---|
| `case_PI-09`（本 KB，2 篇 pageindex 文档） | `2 / 0 / 0` | 1/3 |
| `case_PI-10`（本 KB，同上） | `0 / 2 / 0` | 1/3 |
| DIAG3 单文档 KB `4d43c2ef-…` | `2 / 2 / 3` | 3/3 |
| DIAG3 本 KB（重复文档） | `2 / 0 / 2` | 2/3 |
| DIAG3 **第 2 段对照 KB** `32b1101f-…` | `0 / 0 / 2` | 1/3 |

合计 12 次观测、5 次 0 命中（≈42%）。⇒ **非本 KB 特有、非重复文档特有**，pageindex 引擎本身不稳定。

### 机制旁证
- 0 命中的 run `took_ms` 只有 2–3s（命中 run 3–20s）；
- 返回体 `{"code":0,"total":0,"took_ms":…}` **既无 `message` 也无 `error`** —— 即
  `backend/app/services/pageindex_engine.py::retrieve()` 里选节点的 LLM 返回空 / 解析失败后**静默返回空**；
  retrieve 阶段**没有重试、没有兜底**（仅 build 阶段有"带错误信息重试一次"）；
- 与 `3dc1ddf` 提交说明「`RETRIEVE_MAX_TOKENS` 1024→8192 修 1/6 空结果」属**同一缺陷类**，放大预算后仍可复现。
- 对照：`pageindex_status=ok`、`tree.status=ok`、`node_count=3`、`full_text_chars=776` —— 索引侧一切正常，
  失败发生在检索侧的 LLM 选节点。

### 证据
- `03-testing/evidence/PI-V4_case2_case6.txt`（A5-1 / A5-2 / A5-3 段）
- `03-testing/evidence/PI-V4_result.json` → `case2.checks[C2-8, C2-9]`（verdict=FAIL）
- `03-testing/evidence/PI-V4_raw/PI-09_console.txt`、`PI-10_console.txt`、`DIAG3_console.txt`
- 截图：`PI-V4_ui_indexed.png`（同一 KB 的文档确实已建树 ok）

### 备注（与既有卡的关系）
与第 2 段 findings `PI-V2-F1`（同参重放 1/4 命中、变体问法 3/5 命中）**同一现象**，
本次把样本扩到 12 次并补上了隔离实验与机制旁证，确认不是 KB 差异而是引擎稳定性问题。

---

## BUG-V4-02 — 默认上传的 pageindex 文档在 MCP（智能助手引用链路）上完全不可检索

- **发现卡**：`t_2ba41218`（VI-PI-4，**用例6 判定依据**）
- **发现时间**：2026-10-12T04:01:51Z（run1）/ 04:08:00Z（反向对照 run2）
- **严重程度**：**P1**（建议产品/开发定级；与决策卡 `t_9013e8b2` **同源但发生面不同**）
- **影响面**：所有用 MCP 检索知识库的智能助手（carefold-agent → kb MCP）**看不到任何默认上传的文档**。

### 现象
`category`：默认索引方式改动（`embedding → pageindex`）后，MCP 侧工具契约没有同步 ——
`search_knowledge` 既没有 pageindex 分支，也没有对 pageindex 文档显式拒绝，而是**静默返回 0 条**。

### 复现步骤
```bash
cd /home/harry.zhang/kb-management
# run1：KB 内只有默认上传的 pageindex 文档 → 3 种 mode 全 0
bash 03-testing/curl/case_PI-08_mcp_search_knowledge.sh
# 反向对照：同一 KB 加 1 篇显式 embedding、同夹具同口令的文档
bash 03-testing/curl/case_PI-11_ui_chain_embedding_control.sh
bash 03-testing/curl/case_PI-08_mcp_search_knowledge.sh        # 同脚本同 query → 应 ≥1
# 根因取证：MCP 是否支持 mode=pageindex
MODES=pageindex bash 03-testing/curl/case_PI-08_mcp_search_knowledge.sh
bash 05-temp/t_2ba41218_mcp_toolslist.sh                        # tools/list schema
```
key 从 `infra/.env` 的 `KB_MCP_API_KEY` 读取，脚本只回显长度、不打印明文。

### 预期
默认方式上传的文档，在智能助手（MCP）引用链路上应可被检索到并返回可点击引用（`doc_url` + `location`）；
若产品上不支持，工具应**显式报错/明确拒绝**，让助手能区分"没有资料"和"没能力检索这类资料"。

### 实际
- run1（KB：2 篇 pageindex 文档，`chunk_count=0`，`pageindex_status=ok`）
  → MCP `search_knowledge` `total` = hybrid **0** / vector **0** / keyword **0**，`items=[]`。
- `MODES=pageindex` 探针 → `total=0`、`took_ms=0`、**无 error**（静默空结果）。
- 反向对照 run2（同 KB 追加 1 篇显式 embedding、**同内容同口令**的文档 `9c8f8743-…`）
  → `total` = hybrid **2** / vector **2** / keyword **1**，**全部命中 embedding 副本**，
  且带 `doc_url`（`…/doc/<id>?chunk=1&token=…`）与 `location`。
- 两篇默认 pageindex 文档（`30691711-…`、`dd083cf9-…`）在 run1+run2 共 **12 次返回里 0 次出现**。

### 根因
- `backend/mcp_server.py` 的 `search_knowledge` 把 `mode` 直接透传给
  `es_client.hybrid_search`（其只处理 `hybrid / vector / keyword`），**没有 pageindex 分支**；
- `pageindex` 文档不写 ES 分块（`chunk_count=0`），ES 侧永远检索不到；
- MCP `tools/list` 全响应中 `pageindex` 出现 **0 次**（其余工具也没有）→ 工具契约层面根本没有这个概念。

### 证据
- `03-testing/evidence/PI-V4_case2_case6.txt`（B7 / B8 / B7+ 段）
- `03-testing/evidence/PI-V4_result.json` → `case6`（verdict=`CONFLICT`，C6-2/C6-5a 为冲突项）
- `03-testing/evidence/PI-V4_raw/PI-08_run1_console.txt`、`PI-08_run2_console.txt`、
  `PI-08_mode_pi_console.txt`、`MCP_tools_list_console.txt`、`FINAL_state_console.txt`

### 与 `t_9013e8b2` 的关系（需产品/开发确认）
- **同源**：都是"默认上传方式改了、下游链路没跟上"。
- **发生面不同**：`t_9013e8b2` 是**站内**默认检索/问答 0 来源；本项是**智能助手（MCP）引用链路**的检索面。
- 本段实测**站内默认链路（auto）已能给出 `sources=2`（`metadata.leg=pageindex`）**，而 MCP 侧恒为 0
  ⇒ 两个面**不能互相覆盖**，`t_9013e8b2` 的修复不会顺带修好本项。
- 建议：**本项单独立卡（P1）**；修法二选一 —— 在 MCP 侧补 pageindex 分支（走 `pageindex_engine.retrieve`），
  或显式拒绝 pageindex 文档并回明确错误。**不要让工具静默返回 0 条**。

---

## 观察项（不判 FAIL，无需修复，仅留痕）

### OBS-V4-1 — 问答 0 来源时的错误文案误导
`event: error` 文案固定为「未检索到相关 PageIndex 内容，请换一种问法或确认已上传 PageIndex 索引的文档。」，
但在 BUG-V4-01 的场景下 KB 里**确实有** pageindex 文档（`pageindex_status=ok`）。
建议文案区分"没有 pageindex 文档"与"有文档但本次未选中节点"。
证据：`PI-V4_raw/PI-10_chat_pageindex_run1.sse` / `run3.sse`。

### OBS-V4-2 — 线上入口 js 指纹与开发文档不一致（文档滞后，非缺陷）
开发文档称线上入口为 `assets/index-CaTnCPvY.js`；本段实测 **`assets/index-BHI8vxe6.js`**
（`KbDetailView-CcLfGsq-.js`，sha256 `c4c9ff349fd02ec4f7c81f0151f2a2ae97f49c43a33b56ac565f4fb42b538f53`）。
原因：`3dc1ddf` 之后自动检索卡 `5856436` 又重建过一次前端 dist。默认 pageindex 的字符串证据仍在。
建议：后续卡引用线上指纹时以实测为准。证据：`PI-V4_raw/A6_online_entry.txt`。

### OBS-V4-3 — `t_2ba41218` 在自建 KB 内留下 3 篇测试文档
KB `22bcb345-8326-479c-958b-51daa2905715`（`验证-默认pageindex-VI-PI-4-20261012-035005`）内含
2 篇 pageindex（`30691711-…`、`dd083cf9-…`）+ 1 篇显式 embedding（`9c8f8743-…`）；
另有诊断单文档 KB `4d43c2ef-399d-4fe3-bf08-d0a1d0b8403f`。
均为**自建** KB、未触碰任何业务 KB；后续如需清理请连同 KB 一起软删，勿误当存量数据。
