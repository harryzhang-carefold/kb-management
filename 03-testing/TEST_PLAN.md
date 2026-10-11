# TEST_PLAN — kb-management PageIndex 检索（feat/pageindex）

**测试**：云天明  2026-10-10
**任务**：t_553f17d8
**分支**：feat/pageindex（commit 383e596，已按用户要求 checkout 验证）

## 1. 测试依据

- 00-management-PAGEINDEX_BRIEF.md（验收标准 5 条，2026-10-10 口径变更为"按文档二选一"）
- 02-development/DEV_REPORT.md（开发自验 27/27 证据 + 已知问题）
- 代码审查：pageindex_engine.py / rag_engine.py / search.py / chat.py / documents.py / schemas.py / 前端三视图 + api/index.ts

## 2. 测试范围

| 层 | 覆盖 |
|---|---|
| 后端 API | 上传(index_type) / 检索(mode=pageindex) / 问答(retrieval_mode=pageindex, SSE) / reindex / rebuild / 回归 hybrid/vector/keyword |
| 异步任务 | Celery 建树（parse→pageindex 链式触发）、reindex 重建 |
| 前端 | 9013 dev 服务器实测：上传 radio / 搜索 radio / 问答 radio / 重建按钮 |
| 边界 | 大文档多分片建树超时行为、单节点文档（树退化）、LLM 不可用错误提示 |

**不在范围**：embedding 端点（34.64.61.208:4000）外部不可达导致的向量索引 failed —— 属环境态，非代码缺陷；回归按"原路径行为不变 + 代码零改动"双证据验证。

## 3. 环境

- 后端 9012（uvicorn + celery worker，PID 3115356/3115705，含 id 修复代码）
- 前端 9013（vite dev，本轮启动）
- PG 9011 / ES 9200 / MinIO 9002 / Redis kb-dev-redis:6390 均正常
- LLM vllm-qwen3.8-27b @34.121.9.233:4000 可达（health=ok）
- embedding / mineru 不可达（已知环境态）

## 4. 用例（详见 TEST_CASES.md）

- AC-1~AC-5：验收标准 5 条
- REG-1~REG-3：hybrid/vector/keyword 回归
- EDGE-1~EDGE-3：大文档建树 / 单节点退化 / LLM 不可用提示
- 共 11 条。接口类用例的 curl 命令存档于 03-testing/curl/。

## 5. 通过判据

- 5 条验收标准全部 PASS 且无 P0/P1 BUG → 测试结论 PASS
- 任一验收标准 FAIL 或存在 P0 → FAIL
