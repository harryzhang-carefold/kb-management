# BUGFIX — BUG-01（P1）检索 vector/hybrid 模式跨知识库泄露

**任务**：t_f4aac859（云天明在 VERIFY-4 回归 t_b973a77e 中发现，已定位到代码行）
**开发**：章北海  2026-10-12
**分支**：`feat/default-pageindex`（当前部署线；本地提交，未 push）**commit**：本次提交 `fix(search): 修复 vector/hybrid 跨知识库泄露 (t_f4aac859 BUG-01)`
**严重程度**：P1 —— 多租户数据隔离红线（`kb_chunks` 单索引共享，隔离完全依赖 `kb_id` filter）

---

## 0. 一句话结论

`hybrid_search()` 的 kNN 请求体里有一个**没有 kb_id 过滤的顶层 `query`（`match_all`）**，而 ES 8 对 `knn` 与顶层 `query` 的命中**取并集**——本 KB 的 kNN 真命中不足 `size=top_k` 时，全索引其它知识库的 chunk（`_score=0.0`）被并入结果填满条数。已删除该顶层 query（过滤只由 `knn.filter` 承担），并加了一层 "命中 kb_id 必须等于查询 kb_id" 的防御性校验。修复后 `case_BUG-01.sh`（vector / hybrid）双双 `PASS（foreign_docs=0）`，仓库 e2e、检索三模式、双向隔离共 16/16 检查全过。

---

## 1. 根因（定位 + ES 层直证）

### 1.1 代码位置

`backend/app/utils/es_client.py:146-157`（修复前），`hybrid_search()` 的 kNN 分支：

```python
body = {
    "size": top_k,
    "query": {"match_all": {"boost": 0}},      # ← 无 kb_id 过滤：命中全索引所有 chunk
    "knn": {"field": "embedding", ..., "filter": base_filter},   # ← 只有 kNN 这一路被过滤
}
```

同文件的 BM25 分支（走 `bool.filter = base_filter`）没有这个问题 → `mode=keyword` 干净，`mode=vector`/`hybrid` 泄露。`hybrid` 的 RRF 融合会把这一条跨界命中带进最终结果。

### 1.2 ES 层证据（`05-temp/t_f4aac859_es_evidence.py`，只读查询，2026-10-12）

以 **kb_id=`d04021d3-…`**（泄露片段 `r2_second.md` 的真实归属库，7 chunk）为 filter 目标，用该库一个真实 chunk 的 384 维 embedding 作 query_vector，`size=top_k=10`：

| 请求体 | 返回条数 | 非本 KB 条数 | score=0 条数 | total_hits | 返回里的 kb_id |
|---|---|---|---|---|---|
| OLD（`query:match_all` + `knn`） | 10 | **3** | **3** | 32 | 本 KB + **d3862f54…**（他库） |
| NEW（仅 `knn`+`knn.filter`） | 7 | **0** | 0 | 7 | 仅本 KB |
| 仅 `match_all`（无过滤） | 10 | **9** | 0 | 32 | 本 KB + 他库 |

- 泄露机制直接可见：**score=0 的 3 条正是 `match_all` 并进来的他库 chunk**（"score=0.0 是指纹"）。
- 召回对比：`NEW ⊆ OLD` 为真，`OLD-NEW = 3`（全是那 3 条填充项）、`NEW-OLD = 0` → **真命中一条没丢**，删掉的只是 score=0 的跨库填充。
- 边界说明：以 kb_id=`d3862f54-…`（当前 18 chunk）为 filter 目标时 OLD 已不再泄露——因为 kNN 真命中（10 条）已填满 `size`，score=0 的填充项排不进 top-10。**这也解释了为什么该缺陷会随数据量变化时隐时现**（数据少的 KB 必中）。
- 索引全貌：`kb_chunks` 单索引内当前 9 个不同 `kb_id`（32 chunk），**隔离完全依赖 `kb_id` filter**。

---

## 2. 改动（diff 摘要）

`backend/app/utils/es_client.py`（唯一改动的代码文件）：

1. **删除 kNN 请求体的顶层 `"query": {"match_all": {"boost": 0}}`**，只保留 `knn` + `knn.filter = base_filter`（+ 注释写明 ES 8 的 `knn`×`query` 并集语义与本次根因，防回归）。
2. **防御性第二层**：kNN 与 BM25 两个分支在组装命中项前各加一道
   `if h["_source"].get("kb_id") != kb_id: logger.warning(...); continue`
   ——即使将来查询体再度回归，也不会把非本 KB 的 chunk 交给上层（检索 API / RAG / MCP）。
3. 返回结构、三种模式语义、`_rrf_fuse` 均未改动。

行为差异（有意）：`vector` 模式的 `items` 不再包含 `score=0.0` 的全库填充项，因此当本 KB 真命中不足 `top_k` 时条数会少于 `top_k`（此前是被他库 chunk 填满的假满足）。

---

## 3. 自测与验收证据（全部真实运行，2026-10-12 UTC）

部署后端 `127.0.0.1:9012`（2026-10-12 03:12 重启，见 §4），公网入口 `https://agent.carefold.ai/kb-management`。

### 3.1 任务书复现命令（回归验收口径）

```
$ bash /home/harry.zhang/myapp/03-testing/curl/case_BUG-01.sh            # mode=vector
[kb-docs] HTTP=200 count=7
[search] HTTP=200 mode=vector hit_docs=2 foreign_docs=0
[verdict] PASS —— 检索命中全部属于本 KB，未发现跨库泄露
SUMMARY case=BUG-01 mode=vector foreign_docs=0 verdict=PASS              (exit 0)

$ BUG_MODE=hybrid bash /home/harry.zhang/myapp/03-testing/curl/case_BUG-01.sh
[search] HTTP=200 mode=hybrid hit_docs=2 foreign_docs=0
[verdict] PASS —— 检索命中全部属于本 KB，未发现跨库泄露
SUMMARY case=BUG-01 mode=hybrid foreign_docs=0 verdict=PASS              (exit 0)
```

修复前同命令基线（同一环境）：`mode=vector` → `hit_docs=2 foreign_docs=1 verdict=BUG_REPRODUCED`；`mode=hybrid` → 同样 `foreign_docs=1`（泄露 `document_id=4263d0db-…` / `r2_second.md`，ES 内真实 `kb_id=d04021d3-…`，`score=0.0`）。

### 3.2 双向隔离 × 三模式自测（`05-temp/t_f4aac859_verify.py`）

对 **KB A（`d3862f54-…`，被测库）** 与 **KB B（`d04021d3-…`，泄露片段归属库）** 各跑 `vector`/`hybrid`/`keyword`，断言"每个命中的 document_id ∈ 该 KB 文档集合"：

```
SUMMARY verdict=PASS checks=16 failures=0

kbA vector : items=10 foreign=0 score_zero=0 min=0.7390 max=0.7800
kbA hybrid : items=10 foreign=0 score_zero=0 min=0.0154 max=0.0328
kbA keyword: items=10 foreign=0 score_zero=0 min=0.9451 max=0.9731
kbB vector : items=7  foreign=0 score_zero=0 min=0.5326 max=0.6117
kbB hybrid : items=7  foreign=0 score_zero=0 min=0.0149 max=0.0164
kbB keyword: items=0  foreign=0（BM25 对该 query 无命中，与修复前一致）
```

（`keyword` 分支未改动；其命中集合、打分逻辑与修复前一致。）

### 3.3 仓库既有回归

```
$ backend/.venv/bin/python tests/e2e_test.py
🎉 E2E TEST PASSED — 全部 8 步通过        (health→建库→上传→索引→检索→RAG SSE→会话)
```

### 3.4 防御层未被触发（证明是查询体修复在起作用）

重启后 `05-temp/backend_9012.log` 中 `dropped foreign chunk` 告警计数 **0** —— 说明泄露是在 ES 查询层被消除的，Python 侧兜底没有"掩蔽"问题。

---

## 4. 部署

| 项 | 值 |
|---|---|
| 服务 | kb 后端 API 9012（host 进程，`backend/.venv` uvicorn） |
| 动作 | 重启加载修复后的 `es_client.py`（2026-10-12 03:12:11 UTC） |
| 启动方式 | **systemd user 常驻单元** `kb-backend-9012.service`（transient，`Restart=always`，`WorkingDirectory=/home/harry.zhang/kb-management`，日志 append 到 `05-temp/backend_9012.log`） |
| 健康 | `GET http://127.0.0.1:9012/api/v1/health` → 200；`/kb-management/api/` 经 nginx-test 公网同样 200 |
| 占用 | RSS 149MB / cgroup 118MB（与修复前同量级，无新增容器/端口） |
| 未改动 | nginx 配置（红线：另一条验证线已 PASS）、Celery、MCP 9100、前端 dist、embedding |

> 为什么改成 systemd 单元：此前 9012 是**在其他 agent 会话的 systemd scope 内**用 `nohup` 起的，scope 随该会话结束会回收 → 服务随时可能消失（交付环境不可复现）。改为独立 user 单元后，`Restart=always` 保证常驻；恢复手册见 `DEPLOY.md §5`。

---

## 5. "是否还有其它同类风险点"结论（任务书第 3 条）

排查范围：`backend/app/**`、`backend/mcp_server.py` 中所有 ES 调用与 KB 过滤。

| 调用点 | 现状 | 结论 |
|---|---|---|
| `es_client.hybrid_search()` kNN 分支 | 本次修复（仅 `knn.filter`）+ 结果层 kb_id 校验 | **已修** |
| `es_client.hybrid_search()` BM25 分支 | 原本就是 `bool.filter=base_filter`；本次补结果层 kb_id 校验 | 安全（加固） |
| `es_client.delete_document()` / `delete_kb()` | `delete_by_query` 按 `document_id` / `kb_id` | 安全（按显式 id，UUID 全局唯一） |
| `es_client.count(kb_id=None)` | 无 kb_id 时用 `match_all` 统计**整索引** | **无调用点**（`grep` 全仓 `es_client.count` = 0 处；仅内部 `_existing_dim` 直接用 `es.index.count`）→ 属**潜在**风险，若将来把它暴露成 API 会给出跨租户总量；本次不改（无调用点，避免扩大改动面），登记为观察项 |
| RAG 问答（`services/rag_engine.py`） | 走 `hybrid_search(mode="hybrid")` | 随本次修复一并消除 |
| MCP 工具 `search_knowledge`（`mcp_server.py:386`） | 走 `hybrid_search` | 随本次修复一并消除 |
| PageIndex 检索（`services/pageindex_engine.py:612`） | SQL 层 `Document.kb_id == kb_id` 起查，树来自该文档 meta | 安全（无 ES 参与） |
| 其它 `es.search` 调用点 | 全仓只有 `es_client.py` 内两处（本次已核查） | 无遗漏 |

**结论：ES 检索侧的同类风险点只有本次这一处（另有一处无调用点的 `count()` 潜在项，已登记）；无其它未加过滤的 `match_all`/`query`。**

---

## 6. 已知问题 / 交下游

1. **`count(kb_id=None)` 潜在项**（§5）：当前无调用点，未改；若后续新增"全库统计"类接口，必须显式要求 kb_id。
2. **同分支并行任务**：`feat/default-pageindex` 上同时有 t_7f451c5f（上传默认索引方式改 pageindex）在改 `documents.py`/`pageindex_engine.py`/`KbDetailView.vue` 并重部署前端。本次提交**只含** `backend/app/utils/es_client.py` + 本文档 + `DEV_REPORT.md`/`DEPLOY.md` 追加段，**未触碰**其文件，也**未 push**（避免与其推送冲突）。
3. **Celery 进程仍寄生在别的 agent 会话 scope 内**（`05-temp/backend_9012.log` 之外，PID 3043762/3043869/3043870）→ 该会话结束时 worker 会被回收，异步解析/建树中断。本次**未动**（避免双 worker 抢同一队列），已登记台账；建议后续统一到 `kb-celery.service` 常驻单元。
4. `mode=vector` 结果不再有 `score=0.0` 填充项（见 §2），若前端/调用方曾依赖"永远返回 top_k 条"的错觉，需按"真命中数"渲染（当前前端按条数渲染，无影响）。
5. 证据脚本在 `05-temp/`（不进 git）：`t_f4aac859_es_evidence.py`、`t_f4aac859_verify.py`、输出 `t_f4aac859_es_layer_evidence.txt`、`t_f4aac859_verify_out.json`；测试侧用例与日志见 `/home/harry.zhang/myapp/03-testing/curl/case_BUG-01.sh`、`03-testing/nginx_upload_verify/logs/bug01_cross_kb_leak{,_hybrid}.txt`。
