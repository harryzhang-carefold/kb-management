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
