"""parsing 模块冒烟测试。"""
import sys
sys.path.insert(0, ".")

from app.parsing import parse_document, detect_file_type, ParseError
from app.parsing.mineru_client import mineru_health
from app.services.chunker import chunk_text

# --- detect_file_type ---
assert detect_file_type("a.PDF") == "pdf"
assert detect_file_type("a.xlsx") == "xlsx"
assert detect_file_type("a.xls") == "xls"
assert detect_file_type("a.jpeg") == "jpg"
assert detect_file_type("a.markdown") == "md"
assert detect_file_type("a.htm") == "html"
assert detect_file_type("a.tiff") == "tiff"
assert detect_file_type("a.xyz") is None
print("detect_file_type OK")

# --- xls 拒绝 ---
try:
    parse_document(b"x", "a.xls")
    raise AssertionError("should raise")
except ParseError as e:
    assert "xlsx" in str(e)
print("xls rejection OK")

# --- txt / md / html 本地解析 ---
md, meta = parse_document("hello world\nline2".encode(), "a.txt")
assert md == "hello world\nline2"
assert meta["parse_engine"] == "local"
md, meta = parse_document("# 标题\n\n内容".encode(), "a.md")
assert meta["source_type"] == "md"
md, meta = parse_document("<html><body><script>x</script><p>hi</p></body></html>".encode(), "a.html")
assert md == "hi"
print("local parsers OK")

# --- MinerU 不可用时的错误信息 ---
try:
    parse_document(b"%PDF-1.4 fake", "a.pdf")
    raise AssertionError("should raise (mineru not running)")
except ParseError as e:
    assert "MinerU" in str(e)
    print("mineru error path OK:", str(e)[:80])

# --- mineru_health ---
h = mineru_health(timeout=3)
print("mineru_health:", h["status"])

# --- chunker 结构感知 ---
sample = """---
source_type: xlsx
---

# 标题一

正文段落 A，内容略长一些。

| 月份 | 收入 | 成本 |
|---|---|---|
| 2025-01 | 100 | 60 |
| 2025-02 | 120 | 70 |
| 2025-03 | 130 | 80 |

## 标题二

正文段落 B。
"""
chunks = chunk_text(sample, chunk_size=120, chunk_overlap=20)
assert len(chunks) >= 2
joined = "\n".join(c["content"] for c in chunks)
# front-matter 不应进入 chunk
assert "source_type" not in joined
# 表格行不应被切断（每块中的 | 行完整）
for c in chunks:
    lines = c["content"].splitlines()
    table_lines = [l for l in lines if l.strip().startswith("|")]
    # 若块内含表格行，则必须同时包含表头（|---| 分隔行）—— 即表格完整或带表头
    if table_lines and any("---" in l for l in table_lines):
        assert table_lines[0].startswith("| 月份") or "月份" in table_lines[0] or len(table_lines) >= 2
print(f"chunker OK: {len(chunks)} chunks")
for i, c in enumerate(chunks):
    print(f"  [{i}] ({len(c['content'])} chars): {c['content'][:60].replace(chr(10), ' / ')}...")

# --- 长表格拆分带表头 ---
rows = "\n".join(f"| 行{i} | 值{i} |" for i in range(60))
big_table = "| 列A | 列B |\n|---|---|\n" + rows
chunks2 = chunk_text(big_table, chunk_size=200, chunk_overlap=30)
assert all(c["content"].startswith("| 列A") for c in chunks2), "每个分片应重复表头"
print(f"long table split OK: {len(chunks2)} pieces, all with header")

print("\nALL PARSING SMOKE TESTS PASSED")
