#!/usr/bin/env bash
# 追加「裁定汇总」到首执记录（上面的原始输出保持不动）
cd /home/harry.zhang/kb-management || exit 1
cat >> 03-testing/evidence/PI-V2_case1_case3.txt <<'EOF'


==================== 裁定汇总（本段 t_32351222） ====================
用例1 (PI-01 默认上传不传 index_type):  PASS
  证据: HTTP 200 / code=0 / index_type=pageindex / pageindex_status=ok(非降级) /
        tree.status=ok / model=deepseek-flash / node_count=3 / build_ms=64107 /
        doc.status=indexed / openapi default=pageindex
  注: A6「root.title != 夹具 markdown 标题」字面不满足（root.title 恰等于夹具 H1），
      但该断言已被证明无区分度（降级树 root.title 同样取 H1）。判 PASS 依据为 4 条独立反降级证据，
      详见 03-testing/evidence/PI-V2_findings.md 与 PI-V2_result.json。

用例3 (该文档 pageindex 检索/问答可用):
  - 检索 search (mode=pageindex):   FAIL
      首执 HTTP 200 但 total=0 / items=[] / 无条目含 PI-TOKEN-7412（message 字段缺省 → 库内确有 pageindex 文档）
      同参重放 4 次 total=[0,0,1,0] → 1/4 命中；变体问法 5 条 3/5 命中 → 非确定性
  - 问答 chat (retrieval_mode=pageindex):  PASS
      SSE meta→token×50→sources→done；sources=1；答案含 PI-TOKEN-7412 且带 [1] 引用；重放 2 次 sources=1/2
  - 用例3 整体裁定: FAIL（检索子项未满足硬断言）

观察项（不判 FAIL）:  同一文档不传 retrieval_mode → sources=0 + meta.notice，
  与开发自测口径一致（DEV_REPORT §5 P1）；属已上报既有 P1 产品决策错配（决策卡 t_9013e8b2），非本次回归。

结构化逐条断言: 03-testing/evidence/PI-V2_result.json
发现/BUG 记录:   03-testing/evidence/PI-V2_findings.md
重放记录:        03-testing/evidence/raw/PI-V2_replays.txt
===================================================================
EOF
echo "[ok] 已追加裁定汇总"
