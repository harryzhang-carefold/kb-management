"""文档分块（chunking）：Markdown 结构感知切分。

策略（v2，2026-09-21 随 MinerU 解析升级）：
1. 剥离 YAML front-matter（元数据由 Document.meta 承载，不进 chunk）。
2. 识别结构块：标题段、完整表格（不可分割，超长按行切并重复表头）、
   代码块、普通段落。
3. 标题与其后第一个内容块绑定，避免标题孤立在上一块末尾。
4. 块间累积到 chunk_size 收块；overlap 保留上一块尾部 chunk_overlap 字符。

兼容旧参数 chunk_size=500 / overlap=50。
"""
import re
import uuid
from typing import Optional


def count_tokens(text: str) -> int:
    """粗略 token 计数（中文按字符，英文按单词近似）。"""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    words = len(re.findall(r"[a-zA-Z0-9]+", text))
    return cjk + words


# ----------------------------------------------------------------------
# 结构块识别
# ----------------------------------------------------------------------

def _strip_front_matter(text: str) -> str:
    """剥离开头的 YAML front-matter（--- ... ---）。"""
    if text.startswith("---"):
        m = re.match(r"^---\s*\n.*?\n---\s*\n?", text, re.DOTALL)
        if m:
            return text[m.end():]
    return text


def _split_blocks(text: str) -> list[tuple[str, str]]:
    """把 Markdown 文本切分为 (kind, content) 结构块列表。

    kind ∈ {heading, table, code, para}
    表格块 = 连续以 | 开头的行（含表头分隔行），保证不可被切断。
    """
    lines = text.splitlines()
    blocks: list[tuple[str, str]] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # 代码块 ```
        if stripped.startswith("```"):
            j = i + 1
            while j < n and not lines[j].strip().startswith("```"):
                j += 1
            j = min(j + 1, n)
            blocks.append(("code", "\n".join(lines[i:j])))
            i = j
            continue

        # 表格：连续以 | 开头的行
        if stripped.startswith("|"):
            j = i
            while j < n and lines[j].strip().startswith("|"):
                j += 1
            blocks.append(("table", "\n".join(lines[i:j])))
            i = j
            continue

        # 标题
        if re.match(r"^#{1,6}\s", stripped):
            blocks.append(("heading", line))
            i += 1
            continue

        # 普通段落：累积到空行
        j = i
        buf = []
        while j < n:
            s = lines[j].strip()
            if not s or s.startswith("```") or s.startswith("|") \
                    or re.match(r"^#{1,6}\s", s):
                break
            buf.append(lines[j])
            j += 1
        blocks.append(("para", "\n".join(buf)))
        i = j

    return blocks


def _split_long_table(table: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """表格过长时按行切分，每块重复表头 + 分隔行。"""
    lines = [ln for ln in table.splitlines() if ln.strip()]
    if len(lines) <= 2:
        return [table]
    header = lines[0]
    separator = lines[1]
    rows = lines[2:]

    # 估算表头开销（字符）
    head_cost = len(header) + len(separator) + 2

    pieces: list[str] = []
    cur_rows: list[str] = []
    cur_len = head_cost

    for row in rows:
        row_len = len(row) + 1
        if cur_rows and cur_len + row_len > chunk_size:
            pieces.append(_build_table(header, separator, cur_rows))
            # overlap：保留尾部若干行
            keep = max(0, min(len(cur_rows), chunk_overlap // max(row_len, 1)))
            cur_rows = cur_rows[-keep:]
            cur_len = head_cost + sum(len(r) + 1 for r in cur_rows)
        cur_rows.append(row)
        cur_len += row_len

    if cur_rows:
        pieces.append(_build_table(header, separator, cur_rows))
    return pieces or [table]


def _build_table(header: str, separator: str, rows: list[str]) -> str:
    return "\n".join([header, separator] + rows)


# ----------------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------------

def chunk_text(full_text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[dict]:
    """
    将全文（Markdown）切分为分块列表。
    返回: [{chunk_id, chunk_index, content, token_count}]
    """
    if not full_text or not full_text.strip():
        return []

    body = _strip_front_matter(full_text)
    blocks = _split_blocks(body)
    if not blocks:
        return []

    # 将结构块转换为可累积单元：
    # - 表格 > chunk_size → 拆成多块（各为独立单元）
    # - 标题 → 与其后第一个单元绑定（合并为一个单元）
    units: list[str] = []
    k = 0
    while k < len(blocks):
        kind, content = blocks[k]
        content = content.strip()
        if not content:
            k += 1
            continue

        if kind == "table":
            if len(content) > chunk_size:
                units.extend(_split_long_table(content, chunk_size, chunk_overlap))
            else:
                units.append(content)
            k += 1
            continue

        if kind == "heading":
            # 绑定后续第一个非空块
            if k + 1 < len(blocks):
                nkind, ncontent = blocks[k + 1]
                ncontent = ncontent.strip()
                if nkind == "table" and len(ncontent) > chunk_size:
                    # 表格要拆分：标题绑定第一片
                    pieces = _split_long_table(ncontent, chunk_size, chunk_overlap)
                    units.append(f"{content}\n\n{pieces[0]}")
                    units.extend(pieces[1:])
                elif nkind == "code" or ncontent:
                    combined = f"{content}\n\n{ncontent}"
                    if len(combined) <= chunk_size:
                        units.append(combined)
                    else:
                        units.append(content)
                        units.append(ncontent)
                k += 2
                continue
            else:
                units.append(content)
                k += 1
                continue

        # para / code
        if len(content) > chunk_size:
            # 超长段落/代码块硬切
            step = max(chunk_size - chunk_overlap, 1)
            for i in range(0, len(content), step):
                units.append(content[i:i + chunk_size])
        else:
            units.append(content)
        k += 1

    # 累积单元到 chunk_size 收块（单元本身不跨块拆开）
    # 表格单元（以 | 开头）不可被 overlap 截断：新块开头是表格单元时直接开始，不带 overlap
    chunks: list[str] = []
    current = ""
    for unit in units:
        if not unit:
            continue
        if current and len(current) + len(unit) + 2 > chunk_size:
            chunks.append(current)
            if unit.lstrip().startswith("|"):
                # 表格单元必须保持完整，不做 overlap
                current = unit
            else:
                overlap = current[-chunk_overlap:] if chunk_overlap > 0 else ""
                current = (overlap + "\n\n" + unit).strip()
        else:
            current = (current + "\n\n" + unit).strip()
    if current:
        chunks.append(current)

    # 构建结果
    results = []
    for i, content in enumerate(chunks):
        content = content.strip()
        if not content:
            continue
        results.append({
            "chunk_id": str(uuid.uuid4()),
            "chunk_index": i,
            "content": content,
            "token_count": count_tokens(content),
        })
    return results
