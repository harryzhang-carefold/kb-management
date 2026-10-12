# VI-PI-2（t_32351222）发现记录 — 用例1 + 用例3

时间：2026-10-12 03:29–03:41 UTC ｜ 分支 `feat/default-pageindex` ｜ HEAD `74287fa` ｜ 改动基线 commit `3dc1ddf`
环境：后端 http://127.0.0.1:9012 ｜ LLM `deepseek-flash` ｜ 自建 KB `32b1101f-efd6-467c-900a-255c75656791`
文档：`034cc16f-d230-4fca-beb1-04da2337cc2d`（`pi_default_doc.md`，sha256 `11321dc6870f…`）

裁定小结：**用例1 = PASS ｜ 用例3 = FAIL**（检索子项 FAIL，问答子项 PASS）
结构化逐条断言见 `PI-V2_result.json`；首执全文见 `PI-V2_case1_case3.txt`；重放记录见 `raw/PI-V2_replays.txt`。

---

## 用例1（PI-01）— PASS

不传 `index_type` 上传 → 实测落 pageindex 且**非降级**：

    HTTP 200 / code=0 / document_id 034cc16f… / task_id 278b62c5…
    meta.index_type        = pageindex
    meta.pageindex_status  = ok            ← degraded 才是规则降级树
    tree.status            = ok / model = deepseek-flash
    tree.node_count        = 3 / build_ms = 64107 / full_text_chars = 776
    tree.root              = node_id n1, title "智能制造产线巡检手册", start 0, end 776, children ×2
    doc.status             = indexed / chunk_count = 0（设计互斥：pageindex 不写向量分块）
    openapi upload index_type default = pageindex（原文片段见 raw/openapi_upload_fragment.json）

### 关于断言 A6（反降级旁证）的裁定 —— 需要 orchestration 知晓

任务书写的是「`tree.root.title` ≠ 夹具的 markdown 标题」。**字面不满足**：
夹具 H1 = `# 智能制造产线巡检手册`，实测 `tree.root.title` = `智能制造产线巡检手册`，两者相同。

但该断言**被证明没有区分度**：降级头规则树（`pageindex_engine.py:219-313`）的 root.title 同样取 H1
（`doc_title = heads[title_idx][2]`，`_heading_degraded_tree` 实测 root.title 也是 H1）。即：无论降不降级，
root.title 都等于 H1 —— 这条字面检查无法区分两者。

反降级改由 4 条更强、可复核的独立证据支撑：

1. `meta.pageindex_status == "ok"` / `tree.status == "ok"` —— 降级路径会写 `degraded`（`pageindex_engine.py:518-519,553-554`）。
2. `node_count = 3` —— 夹具含 4 个 `##` + 3 个 `###`；heading 规则树应≥7 个节点（1 根 + 4 一级 + 3 二级，见 `make_node` 逻辑）。实测 3 个 → 明显是 LLM 归并。
3. 子节点标题 `["文档标题、总则与班前点检", "班中抽检异常上报、附则与术语表"]` —— **不是夹具任何 heading 文本**，是 LLM 归纳出的合并小节名。
4. 各节点 `summary` 是压缩改写（root.summary 提到「附则与术语表」、把原文 `A 线` 写成 `A线`）；而降级树 `summary = _first_content(原文片段)` 逐字摘录（`pageindex_engine.py:275,313`）。另 `build_ms = 64107`（64s）为真实 LLM 调用量级。

**裁定**：A6 字面不满足**不**据此判 FAIL；用例1 判 PASS。建议后续把该断言改写成
「node_count 与 heading 数不符 / 子节点标题非 heading / summary 非逐字摘录」三条中的任一。

---

## PI-V2-F1（严重程度：中高，P2；若默认 pageindex 检索是产品主入口建议升 P1 由产品拍板）

**标题**：`mode=pageindex` 检索对措辞敏感 —— 最直接问法 5 次执行仅 1 次命中；同一问法经 chat 通道 3/3 命中

**复现**（一条命令即可复播，入参未变）：

    bash 03-testing/curl/case_PI-02_search_pageindex.sh      # 首执 total=0
    bash 03-testing/evidence/raw/replay_pi02_pi03.sh          # 同参重放 4 次 + chat 2 次

**预期**（本卡 PI-02 硬断言）：HTTP 200 且 `total >= 1`、至少一条 `items[].content` 含 `PI-TOKEN-7412`。

**实际**：
- 首执：HTTP 200，`{"items":[],"total":0,"took_ms":1440}`，无条目含口令 → S2/S3 FAIL。
- 同参重放 4 次：`total = [0, 0, 1, 0]` → 1/4 命中（命中那次 took_ms=12819，未命中约 2.3–3.6s）。
- 变体问法 5 条：`total/含口令条目` = q1 0/0、q2 0/0、q3 1/1、q4 3/2、q5 3/2 → 命中率 3/5。
- 同一 KB、同一文档、**同一问法** 走 chat（`retrieval_mode=pageindex`）：首执 + 2 次重放 = **3/3 命中**，sources = 1/1/2，答案含 `PI-TOKEN-7412` 并带 `[1]` 引用。
- 关键反证：0 命中那次响应里**没有** `message` 字段（说明 `docs_considered >= 1`，即 KB 内确有已建树的 pageindex 文档），且同文档 `pageindex_status=ok`。故 0 命中不是「库里没有 pageindex 文档」而是**选节点阶段返空**。

**证据**：`evidence/PI-V2_case1_case3.txt`（PI-02 段）、`evidence/raw/PI-02_search_main.json`、
`evidence/raw/PI-02_search_q1..5.json`、`evidence/raw/PI-02_replay_main_1..4.json`、`evidence/raw/PI-V2_replays.txt`。

**根因假设（未定位，仅供开发参考）**：`retrieve()` 为单次 LLM 选节点（`temperature=0.0` + `json_mode`，
`RETRIEVE_MAX_TOKENS=8192`）；未命中时 LLM 返回空 `selected`。另外 `_extract_json` 解析失败时也会**静默**得到空
`selected=[]`（`pageindex_engine.py:665-667`，该路径无重试）——两种情况在响应上不可区分。建议开发侧在
`retrieve()` 打印 raw/selected 后，用同一条 query 复现定位（本卡约束不改代码、不重启服务，未做此改动）。

**影响**：本次改动已把上传默认索引改为 pageindex。若用户用自然语言提问、措辞与节点标题不共享字面词，
检索可能返回空结果（而对同一 KB 的 chat 通道稳定命中，用户观感上会很突兀）。对比开发自测（DEV_REPORT 证据2）
其问法（核心组件/环境要求/验收口令）与节点标题共享字面词 → 自测 5/5 命中；本次用不共享字面词的问法即暴露抖动。

---

## PI-V2-F3（严重程度：低，任务书口径偏差，非产品缺陷）

任务书写「断言事件序列含 `meta → sources → token（多次）→ done`」，**与实现不符**。
实测：`meta → token×50 → sources → done`（`chat.py:84-100`：`sources` 与 `done` 同在 done 分支先后 yield）。
本仓既有存档 `curl/case_ac3_chat_pageindex.sh` 也记录为 `meta→token×33→sources→done`。
本卡 B1 按「四类事件齐备 + 顺序符合实现」判 PASS，并留痕。

---

## 观察项（不判本卡 FAIL）— 默认 retrieval_mode 的 sources

同一文档不传 `retrieval_mode`（走 schema 默认 `auto`）：`sources = []`（0 条），并发来 `meta.notice`：
「未在 PageIndex 索引中检索到相关内容。请换一种问法（树索引对文档标题与小节更敏感）。」

- 与开发自测口径（DEV_REPORT §5 P1，t_7f451c5f 段：*默认（不传 retrieval_mode）sources=0*）**一致**。
- 属**已上报的既有 P1 产品决策错配**（决策卡 t_9013e8b2，assignee luoji），**非本次改动的回归**，不在本卡修复范围。
