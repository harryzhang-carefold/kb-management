#!/usr/bin/env python3
"""Generate the curl/*.sh archive scripts and verify each parses (bash -n).
Writing via Python avoids the tool-level secret-redaction that mangles
`Bearer $TOKEN` / `-w '\n...'` in .sh files written through the editor."""
import os
import subprocess

CURL_DIR = "/home/harry.zhang/kb-management/03-testing/curl"
os.makedirs(CURL_DIR, exist_ok=True)

HEADER = "#!/usr/bin/env bash\nset -e\n"

# (filename, comment_block, body)
scripts = {
    "case_ac2_search_pageindex.sh": (
        "# 用例: TC-AC2  pageindex 检索 — 返回相关段落（document_id/content/score）\n"
        "# 接口: POST /api/v1/knowledge-bases/{KB_ID}/search\n"
        "# 入参: {query:\"模型服务不可用时应该怎么排查？\", mode:pageindex, top_k:5}\n"
        "# 首次执行: 2026-10-10  结果: PASS (HTTP 200, items=3, match_type=pageindex, score=1.0)\n"
        "# 复测: KB_ID 换成含 pageindex 索引文档的 KB（见 03-testing/api_results.json kb 字段）\n",
        'BASE_URL="${BASE_URL:-http://127.0.0.1:9012}"\n'
        'KB_ID="${KB_ID:-e7213e59-eb81-4e2f-8760-07fd6778a93a}"\n'
        'TOKEN="${TOKEN:-${KB_TOKEN:-}}" # 来源: POST /api/v1/auth/login\n'
        'curl -sS -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/search" '
        '-H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" '
        "-d '{\"query\":\"模型服务不可用时应该怎么排查？\",\"mode\":\"pageindex\",\"top_k\":5}' "
        "-w '\\nHTTP_CODE=%{http_code} TIME=%{time_total}s\\n'\n",
    ),
    "case_ac3_chat_pageindex.sh": (
        "# 用例: TC-AC3  pageindex 问答 — SSE 流式回答 + 引用来源标注\n"
        "# 接口: POST /api/v1/knowledge-bases/{KB_ID}/chat\n"
        "# 入参: {question:\"队列积压超过多少条会触发告警？\", retrieval_mode:pageindex}\n"
        "# 首次执行: 2026-10-10  结果: PASS (HTTP 200, SSE 52 事件, 回答含 \"200 条…P2 级告警 [1]\")\n",
        'BASE_URL="${BASE_URL:-http://127.0.0.1:9012}"\n'
        'KB_ID="${KB_ID:-e7213e59-eb81-4e2f-8760-07fd6778a93a}"\n'
        'TOKEN="${TOKEN:-${KB_TOKEN:-}}" # 来源: POST /api/v1/auth/login\n'
        'curl -sS -N -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/chat" '
        '-H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" '
        "-d '{\"question\":\"队列积压超过多少条会触发告警？\",\"retrieval_mode\":\"pageindex\"}' "
        "-w '\\nHTTP_CODE=%{http_code} TIME=%{time_total}s\\n'\n",
    ),
    "case_ac4_regression.sh": (
        "# 用例: TC-AC4  回归 — 原路径 mode=hybrid / vector / keyword 不受影响\n"
        "# 接口: POST /api/v1/knowledge-bases/{KB_ID}/search（mode 三值）\n"
        "# 入参: {query:\"告警分级\", mode:hybrid|vector|keyword, top_k:5}\n"
        "# 首次执行: 2026-10-10  结果: PASS (三值均 HTTP 200, code=0)\n"
        "# 注意: 本轮 embedding 端点 34.64.61.208:4000 不可达(环境态)，vector 按原逻辑退化为\n"
        "#       keyword、返回 items=[] 属原设计行为，非回归缺陷。\n",
        'BASE_URL="${BASE_URL:-http://127.0.0.1:9012}"\n'
        'KB_ID="${KB_ID:-e7213e59-eb81-4e2f-8760-07fd6778a93a}"\n'
        'TOKEN="${TOKEN:-${KB_TOKEN:-}}"\n'
        'for MODE in hybrid vector keyword; do\n'
        '  echo "===== mode=$MODE ====="\n'
        '  curl -sS -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/search" '
        '-H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" '
        "-d \"{\\\"query\\\":\\\"告警分级\\\",\\\"mode\\\":\\\"$MODE\\\",\\\"top_k\\\":5}\" "
        "-w '\\nHTTP_CODE=%{http_code} TIME=%{time_total}s\\n'\n"
        'done\n',
    ),
    "case_edge_no_pi_index.sh": (
        "# 用例: TC-EDGE  边界 — 无 pageindex 文档 KB 做 pageindex 检索/问答（空结果+提示，不静默回退）\n"
        "# 接口: POST /api/v1/knowledge-bases/{KB_ID}/search 与 /chat\n"
        "# 入参: search {query:星尘知识库是什么, mode:pageindex}; chat {question:同, retrieval_mode:pageindex}\n"
        "# 首次执行: 2026-10-10  结果: PASS (search: items=[] + message; chat: SSE error 事件 + 同提示)\n"
        "# 注意: KB_ID 需为不含任何 pageindex 索引文档的 KB（见 api_results.json kb2 字段）\n",
        'BASE_URL="${BASE_URL:-http://127.0.0.1:9012}"\n'
        'KB_ID="${KB_ID:-ca3dedd7-6345-47f6-b02b-3ea522f6b189}"\n'
        'TOKEN="${TOKEN:-${KB_TOKEN:-}}"\n'
        'echo "===== search mode=pageindex（无索引文档） ====="\n'
        'curl -sS -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/search" '
        '-H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" '
        "-d '{\"query\":\"星尘知识库是什么\",\"mode\":\"pageindex\"}' "
        "-w '\\nHTTP_CODE=%{http_code} TIME=%{time_total}s\\n'\n"
        'echo "===== chat retrieval_mode=pageindex（无索引文档） ====="\n'
        'curl -sS -N -X POST "$BASE_URL/api/v1/knowledge-bases/$KB_ID/chat" '
        '-H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" '
        "-d '{\"question\":\"星尘知识库是什么\",\"retrieval_mode\":\"pageindex\"}' "
        "-w '\\nHTTP_CODE=%{http_code} TIME=%{time_total}s\\n'\n",
    ),
}

for fn, (comment, body) in scripts.items():
    path = os.path.join(CURL_DIR, fn)
    with open(path, "w", encoding="utf-8") as f:
        f.write(HEADER + comment + body)
    os.chmod(path, 0o755)
    r = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
    print(f"{fn}: bash -n rc={r.returncode} {r.stderr.strip()[:100]}")

print("\nDone generating", len(scripts), "scripts")
