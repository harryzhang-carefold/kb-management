# TEST_CASES — PageIndex 检索（feat/pageindex）

环境：后端 http://127.0.0.1:9012/api/v1，前端 http://127.0.0.1:9013/kb-management/
测试账号：每轮注册新账号（testpi_*）
测试文档：
- 03-testing/testdata/ops_manual.md（~2.3KB，5 个 h1 章节 + 子节，多节点树）
- 03-testing/testdata/one_node.md（~211B，无 heading 单段，用于单节点/退化场景）
- 大文档：ops_manual 内容重复拼接至 ~90KB（> MAX_DOC_CHARS 32000 → 多分片建树）

## AC-1 上传 pageindex 文档 + 异步索引完成
- 步骤：注册 → 建 KB → POST /documents (index_type=pageindex) → 轮询 GET /documents/{id} 至 status=indexed
- 预期：status=indexed；meta.index_type=pageindex；meta.pageindex_status=ok；meta.pageindex_tree 存在且 node_count>1；chunk_count=0（互斥：不走向量索引）
- 接口：curl case_101.sh / case_102.sh

## AC-2 search mode=pageindex 返回相关段落
- 步骤：POST /knowledge-bases/{kb}/search {query:"模型服务不可用时应该怎么排查？", mode:pageindex}
- 预期：200；items 非空；每条含 document_id/content/score/match_type=pageindex；命中 ops_manual.md 且 content 含"故障排查"相关内容；document_id 指向 pageindex 文档

## AC-3 chat retrieval_mode=pageindex 流式回答 + 引用正确
- 步骤：POST /knowledge-bases/{kb}/chat {question:"队列积压超过多少条会触发告警？", retrieval_mode:pageindex}
- 预期：SSE 流式（多 token 事件）；sources 事件 ≥1 条且含 5 字段；回答含 [1] 等引用标注且内容与文档一致（200 条阈值）

## AC-4 回归：hybrid/vector/keyword 原路径不受影响
- 步骤：同一 KB 分别 POST search mode=hybrid / vector / keyword
- 预期：均 200 正常返回 items（embedding 端点不可达时 vector 按原逻辑退化为 keyword，不 5xx）
- 代码级证据：git diff 确认 es_client.hybrid_search / embedding 路径零改动（红线）

## AC-5 前端 PageIndex 模式选择可用
- 步骤：浏览器打开 9013/kb-management → 登录 → KB 详情页上传时选择 PageIndex（radio）→ 搜索页选 PageIndex 模式搜索 → 问答页选 PageIndex 问答
- 预期：三个选择器均可选中且生效（上传走 index_type=pageindex；搜索/问答请求带 pageindex 参数并返回结果）

## EDGE-1 大文档建树（多分片）
- 步骤：上传 ~90KB 无 heading 文档（index_type=pageindex），等待建树完成
- 预期：Celery 任务在 time_limit=900 内完成或明确失败；完成后 meta.pageindex_status ∈ {ok, degraded}，树 piece_count>1；API 全程不阻塞（上传请求 <1s 返回）

## EDGE-2 树退化（单节点文档）
- 步骤：one_node.md（211B 单段无 heading）以 pageindex 上传；建树后 search + chat
- 预期：建树成功（status=ok 或 degraded，不崩溃）；检索能返回该段内容或明确提示；不产生脏数据

## EDGE-3 LLM 不可用时的错误提示
- 步骤：对已有 pageindex 树的 KB 发起 pageindex 检索，此时 LLM 端点不可达（模拟：临时不可行则用"无索引文档 KB"路径替代验证 + 代码审查证据）
- 预期：检索返回 error 标记 + 友好提示，不回退 ES、不 5xx；chat 返回 error 事件 + 提示消息，不空答
- 替代验证：无 pageindex 文档 KB 的检索/问答（items=[] + message；SSE error 事件）—— 该路径与 LLM 失败共用"不静默回退"逻辑（pageindex_engine.retrieve 的 except 分支返回 {error: ...}，rag_engine 统一转 error 事件）

## EDGE-4 边界补充
- 非法 mode=badmode → 422
- embedding 文档调 pageindex/rebuild → 400 类型保护
- pageindex 文档 reindex → 按 index_type 重建成功
- 无 pageindex 文档 KB 做 pageindex 检索/问答 → 空 + 提示（不静默回退，v2 验收重点）
